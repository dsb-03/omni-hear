"""Bodhan AI Indic-Transcribe as an alternative speech engine (beta).

`asr_backend = "indic"` swaps faster-whisper for Bodhan AI's open-weight
Indic-Transcribe models (IIT Madras / AI4Bharat; a Canary-1B-v2 fine-tune,
~1.2B parameters): `bodhan-ai/indic-transcribe-flex` (27 languages, native /
mixed / romanized output, language auto-detect) or `-core` (25 languages,
native script, needs a fixed language).

Optional and heavy: PyTorch + transformers are NOT in requirements.txt. They
are installed by hand (INSTALL_HINT) and imported only inside load(), so this
module stays stdlib-only at import time — config.py and doctor.py import its
constants. The Hugging Face repos are gated: accept the license on the model
page and log in (`hf auth login`, or HF_TOKEN) before the first download.

Memory: on CPU the model's Linear layers are dynamically quantized to int8
at load time (`indic_quantize = "auto"`), roughly halving RAM versus fp16;
on CUDA it runs in fp16. Quantization is best-effort: if it fails the model
runs unquantized and a warning is printed. Nothing quantized is written to
disk or redistributed.

Loading follows the model card: the repo ships an `indic_transcribe` Python
module with an `IndicTranscribe` class, which is imported from the
downloaded snapshot (the same trust as `trust_remote_code`). A repo without
it but with a `.nemo` checkpoint is loaded through NVIDIA NeMo if installed.
The exact constructor/transcribe signatures are matched by introspection,
since they are not documented beyond the card's example.

GGUF (`indic_model` = a path to a `.gguf` file): GgufEngine runs a ggml
conversion (e.g. indic-transcribe-flex Q5_K_M, ~850 MB) through transcribe.cpp
(github.com/handy-computer/transcribe.cpp; Indic-Transcribe support is PR
#245) via its pure-Python ctypes bindings (`transcribe_cpp`), so the model
stays loaded between dictations and no PyTorch is needed. The shared library
(`libtranscribe.so`, built with -DTRANSCRIBE_BUILD_SHARED=ON) is found via
`indic_library`, $TRANSCRIBE_LIBRARY or the bindings' own discovery. The
compute backend is the library's "auto" choice (GPU if it was built with one;
$TRANSCRIBE_BACKEND=cpu forces CPU). transcribe.cpp's canary has no language
auto-detect, so a fixed `language` is required. Output script maps to the
PR's controls: native = itn off, mixed = itn on, roman = "<lang>-Latn".
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
import tempfile
import threading
import wave

DEFAULT_MODEL = "bodhan-ai/indic-transcribe-flex"
QUANTIZE_MODES = ("auto", "int8", "fp16", "off")   # off = float32
OUTPUT_SCRIPTS = ("native", "mixed", "roman")       # flex only
REQUIRED_MODULES = ("torch", "transformers", "huggingface_hub",
                    "sentencepiece", "soundfile")
INSTALL_HINT = "pip install torch torchaudio transformers sentencepiece soundfile"
SAMPLE_RATE = 16000
# The model is trained/served on clips of up to 30 s; longer audio is cut
# into windows at the quietest point near each boundary.
MAX_SECONDS = 30.0



def install_command() -> str:
    """The pip command for the Python omnihear runs on (the .deb's venv in
    /opt/omnihear on Linux, which needs sudo)."""
    cmd = f"{sys.executable} -m {INSTALL_HINT}"
    return ("sudo " + cmd) if sys.prefix.startswith("/opt/omnihear") else cmd


GGUF_MODULE = "transcribe_cpp"


def is_gguf(model: str) -> bool:
    return str(model or "").lower().endswith(".gguf")


def gguf_install_command() -> str:
    cmd = (f"{sys.executable} -m pip install "
           "<transcribe.cpp checkout>/bindings/python")
    return ("sudo " + cmd) if sys.prefix.startswith("/opt/omnihear") else cmd


def missing_modules() -> list[str]:
    return [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]


def resolve_precision(quantize: str, device: str) -> str:
    """'int8' | 'fp16' | 'bf16' | 'fp32' for a quantize mode on a device."""
    q = (quantize or "auto").lower()
    if q == "off":
        return "fp32"
    if q == "auto":
        return "fp16" if device == "cuda" else "int8"
    if q == "int8" and device == "cuda":
        return "fp16"   # dynamic int8 quantization is CPU-only in PyTorch
    if q == "fp16" and device != "cuda":
        return "bf16"   # fp16 matmuls are slow/unsupported on most CPUs
    return q


class Info:
    """The bits of faster-whisper's TranscriptionInfo app.py reads."""

    def __init__(self, language, probability):
        self.language = language
        self.language_probability = probability


def _call(fn, *args, **kwargs):
    """Call fn with only the keyword arguments its signature names."""
    try:
        params = inspect.signature(fn).parameters
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    except (TypeError, ValueError):
        kwargs = {}
    return fn(*args, **kwargs)


def _parse(result):
    """(text, language-or-None) from whatever the model's transcribe returns."""
    if isinstance(result, (list, tuple)) and result and not isinstance(result[0], str):
        result = result[0]
    elif isinstance(result, (list, tuple)) and result:
        if (len(result) == 2 and isinstance(result[1], str)
                and len(result[1]) <= 8):
            return result[0], result[1]   # (text, lang)
        result = result[0]
    if isinstance(result, str):
        return result, None
    if isinstance(result, dict):
        text = next((result[k] for k in ("text", "transcript", "transcription",
                                         "pred_text") if k in result), "")
        lang = next((result[k] for k in ("lang", "language", "language_id",
                                         "source_lang") if result.get(k)), None)
        return str(text or ""), lang
    text = next((getattr(result, k) for k in ("text", "transcript", "pred_text")
                 if isinstance(getattr(result, k, None), str)), "")
    lang = next((getattr(result, k) for k in ("lang", "language", "source_lang")
                 if isinstance(getattr(result, k, None), str)), None)
    return text, lang


def _write_wav(audio, directory=None) -> str:
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    fd, path = tempfile.mkstemp(prefix="omnihear-", suffix=".wav", dir=directory)
    with os.fdopen(fd, "wb") as f, wave.open(f, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return path


def split_windows(audio, max_seconds: float = MAX_SECONDS):
    """Cut audio longer than max_seconds at the quietest 100 ms frame in the
    last 5 s of each window."""
    import numpy as np
    limit = int(max_seconds * SAMPLE_RATE)
    frame = SAMPLE_RATE // 10
    out, start = [], 0
    while len(audio) - start > limit:
        lo = start + limit - 5 * SAMPLE_RATE
        region = audio[lo:start + limit]
        n = len(region) // frame
        energy = (region[:n * frame].reshape(n, frame) ** 2).mean(axis=1)
        cut = lo + int(np.argmin(energy)) * frame + frame // 2
        out.append(audio[start:cut])
        start = cut
    out.append(audio[start:])
    return out


def _torch_module(impl):
    """The nn.Module inside the loaded wrapper (for quantization/eval)."""
    import torch
    if isinstance(impl, torch.nn.Module):
        return impl
    for name in ("model", "asr_model", "_model", "net", "module"):
        m = getattr(impl, name, None)
        if isinstance(m, torch.nn.Module):
            return m
    return None


class IndicEngine:
    """A loaded Indic-Transcribe model. Not thread-safe by itself; app.py
    only calls it from its single worker thread (and loads/unloads it under
    its model lock)."""

    def __init__(self, repo: str, device: str = "cpu", quantize: str = "auto",
                 output: str = "native"):
        missing = missing_modules()
        if missing:
            raise RuntimeError(
                "the Indic engine needs " + ", ".join(missing) +
                f" — install with: {install_command()}")
        import torch
        from huggingface_hub import snapshot_download

        self.repo = repo or DEFAULT_MODEL
        self.device = device if device == "cuda" and torch.cuda.is_available() else "cpu"
        if device == "cuda" and self.device == "cpu":
            print("omnihear: CUDA not available to PyTorch; Indic engine on CPU.")
        self.precision = resolve_precision(quantize, self.device)
        self.output = output if output in OUTPUT_SCRIPTS else "native"
        self._file_input = False   # model wants a path, not an array
        self._lock = threading.Lock()

        try:
            self.path = snapshot_download(self.repo)
        except Exception as e:
            msg = str(e)
            if any(s in msg for s in ("401", "403", "gated", "Gated", "restricted")):
                raise RuntimeError(
                    f"{self.repo} is gated: accept its license on "
                    f"huggingface.co/{self.repo}, then `hf auth login` "
                    "(or set HF_TOKEN)") from e
            raise
        self.impl, self.kind = self._load()
        self._optimize(torch)

    # -- loading ------------------------------------------------------
    def _load(self):
        if (os.path.exists(os.path.join(self.path, "indic_transcribe.py"))
                or os.path.isdir(os.path.join(self.path, "indic_transcribe"))):
            sys.path.insert(0, self.path)
            try:
                mod = importlib.import_module("indic_transcribe")
            finally:
                sys.path.remove(self.path)
            cls = getattr(mod, "IndicTranscribe")
            opts = dict(device=self.device,
                        dtype=self._torch_dtype(), torch_dtype=self._torch_dtype())
            if hasattr(cls, "from_pretrained"):
                return _call(cls.from_pretrained, self.path, **opts), "indic"
            return _call(cls, self.path, **opts), "indic"
        nemo = [f for f in os.listdir(self.path) if f.endswith(".nemo")]
        if nemo:
            if importlib.util.find_spec("nemo") is None:
                raise RuntimeError(f"{self.repo} is a NeMo checkpoint — "
                                   "pip install 'nemo_toolkit[asr]'")
            from nemo.collections.asr.models import ASRModel
            model = ASRModel.restore_from(os.path.join(self.path, nemo[0]),
                                          map_location=self.device)
            return model, "nemo"
        raise RuntimeError(f"{self.repo}: no indic_transcribe module or .nemo "
                           "checkpoint in the repo; not a supported model")

    def _torch_dtype(self):
        import torch
        return {"fp16": torch.float16, "bf16": torch.bfloat16}.get(
            self.precision, torch.float32)

    def _optimize(self, torch):
        module = _torch_module(self.impl)
        if module is None:
            if self.precision != "fp32":
                print(f"omnihear: could not reach the model's weights; Indic "
                      f"engine runs without {self.precision}.")
                self.precision = "fp32"
            return
        module.eval()
        try:
            if self.precision == "int8":
                # PyTorch >= 2.10 warns that torch.ao quantization is
                # deprecated (moving to torchao); if a future release drops
                # it, the except below falls back to float32.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    torch.ao.quantization.quantize_dynamic(
                        module, {torch.nn.Linear}, dtype=torch.qint8,
                        inplace=True)
            elif self.precision in ("fp16", "bf16"):
                module.to(self._torch_dtype())
        except Exception as e:
            print(f"omnihear: {self.precision} conversion failed ({e}); "
                  "Indic engine runs in float32.")
            module.float()
            self.precision = "fp32"

    # -- inference ----------------------------------------------------
    def _run(self, piece, language):
        fn = self.impl.transcribe
        src = piece
        path = None
        if self._file_input:
            path = src = _write_wav(piece)
        try:
            if self.kind == "nemo":
                kw = {}
                if language:
                    kw = dict(source_lang=language, target_lang=language)
                return _call(fn, [src], **kw, batch_size=1, verbose=False)
            return _call(fn, src, lang=language, language=language,
                         output_script=self.output, script=self.output,
                         output_mode=self.output, sample_rate=SAMPLE_RATE,
                         sr=SAMPLE_RATE)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def transcribe(self, audio, language=None, vocabulary=None):
        """(text, Info) for 16 kHz mono float32 audio. `language` is an
        ISO code, or None to let the model detect it (flex only).
        `vocabulary` is unused (no hint input on this runtime)."""
        import torch
        texts, detected = [], None
        with self._lock, torch.inference_mode():
            for piece in split_windows(audio):
                if len(piece) < SAMPLE_RATE // 10:
                    continue
                try:
                    result = self._run(piece, language)
                except Exception:
                    if self._file_input:
                        raise
                    # First call with an array failed: the model may only
                    # take file paths (as on its card). Remember and retry.
                    self._file_input = True
                    result = self._run(piece, language)
                text, lang = _parse(result)
                if text.strip():
                    texts.append(text.strip())
                detected = detected or lang
        lang = language or detected
        return " ".join(texts), Info(lang, 1.0 if lang else 0.0)


class GgufEngine:
    """An Indic-Transcribe GGUF loaded through transcribe.cpp's bindings.
    Same interface as IndicEngine. One session, reused; app.py calls it from
    its single worker thread only."""

    def __init__(self, path: str, output: str = "native", library: str = ""):
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise RuntimeError(f"GGUF model not found: {path}")
        if library:
            library = os.path.expanduser(library)
            if not os.path.isfile(library):
                raise RuntimeError(f"indic_library not found: {library}")
            # Read by the bindings when they first load the library.
            os.environ["TRANSCRIBE_LIBRARY"] = library
        if importlib.util.find_spec(GGUF_MODULE) is None:
            raise RuntimeError("GGUF models need transcribe.cpp's Python "
                               f"bindings — {gguf_install_command()}")
        try:
            import transcribe_cpp
        except Exception as e:  # library not found / ABI mismatch
            raise RuntimeError(
                f"could not load transcribe.cpp ({e}); build it with "
                "-DTRANSCRIBE_BUILD_SHARED=ON and set indic_library to "
                "build/.../libtranscribe.so") from e
        self.repo = path
        self.output = output if output in OUTPUT_SCRIPTS else "native"
        self.precision = "gguf"
        self._lock = threading.Lock()
        self.model = transcribe_cpp.Model(path)
        try:
            self.session = self.model.session()
            caps = self.model.capabilities
            self.languages = tuple(caps.languages)
            self.auto_language = bool(caps.supports_language_detect)
            max_ms = int(caps.max_audio_ms or 0)
            self.max_seconds = (min(MAX_SECONDS, max_ms / 1000)
                                if max_ms > 1000 else MAX_SECONDS)
            # Mixed output needs the Indic itn slot (transcribe.cpp only
            # advertises "itn" on Indic-Transcribe GGUFs); romanized needs
            # "<lang>-Latn" codes in the file's language list, which the
            # language gate checks (convert-indic-canary.py adds them).
            self._itn = self.model.supports("itn")
            self._vocab = self.model.supports("vocabulary")
            self.base_languages = tuple(l for l in self.languages
                                        if not l.endswith("-Latn"))
            self._warned = set()
        except Exception:
            self.close()
            raise
        try:
            self.precision = "gguf on " + str(self.model.device.name)
        except Exception:
            pass
        modes = ["native"] + (["mixed"] if self._itn else [])
        if any(l.endswith("-Latn") for l in self.languages):
            modes.append("roman")
        self.modes = tuple(modes)
        langs = self.base_languages
        print(f"omnihear: GGUF output scripts: {', '.join(self.modes)}; "
              f"languages: {', '.join(langs[:30]) or '?'}"
              + (f" (+{len(langs) - 30} more)" if len(langs) > 30 else ""))
        if not self._itn:
            # Files from transcribe.cpp's convert-indic-canary.py carry the
            # Indic prompt slot (itn is advertised) and the 27 Indic codes.
            # Without the slot the model gets stock Canary's 9-token prompt,
            # not the 10-token one it was trained on, and output degrades.
            print("omnihear: WARNING: this .gguf is not a transcribe.cpp "
                  "Indic-Transcribe conversion (no romanized/itn prompt slot"
                  + (f", {len(langs)} languages instead of 27" if len(langs) > 40
                     else "") + "); expect poor transcripts. Use a file made "
                  "with transcribe.cpp's scripts/convert-indic-canary.py.")

    def _warn_once(self, key, msg):
        if key not in self._warned:
            self._warned.add(key)
            print("omnihear: " + msg)

    def close(self):
        for obj in (getattr(self, "session", None), getattr(self, "model", None)):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass

    def _run_options(self, language):
        if not language:
            if not self.auto_language:
                raise RuntimeError(
                    "this GGUF model can't detect the language — set a fixed "
                    "language in Settings (e.g. hi for Hindi/Hinglish)")
            return {}
        if self.languages and language not in self.languages:
            raise RuntimeError(f"language {language!r} is not in this model "
                               f"({', '.join(self.base_languages)})")
        opts = {"language": language}
        output = self.output
        if output == "roman" and f"{language}-Latn" not in self.languages:
            output = "mixed" if self._itn else "native"
            self._warn_once("roman", (
                f"this .gguf has no romanized mode for {language!r} (its "
                f"language list has no '{language}-Latn'); using {output}. "
                "Re-convert with transcribe.cpp's "
                "scripts/convert-indic-canary.py to get it."))
        if output == "mixed" and not self._itn:
            output = "native"
            self._warn_once("mixed", "this .gguf has no mixed-script mode; "
                            "using native")
        if output == "roman":
            opts["language"] = f"{language}-Latn"
        elif self._itn:
            opts["itn"] = "on" if output == "mixed" else "off"
        return opts

    def transcribe(self, audio, language=None, vocabulary=None):
        import numpy as np
        import transcribe_cpp
        opts = self._run_options(language)
        # Debugging: OMNIHEAR_DUMP_AUDIO=<dir> saves each piece exactly as
        # sent to the model (16 kHz mono WAV), to replay with transcribe-cli.
        dump = os.environ.get("OMNIHEAR_DUMP_AUDIO")
        if vocabulary and self._vocab:
            opts["vocabulary"] = list(vocabulary)[:50]
        texts, detected = [], None
        with self._lock:
            for piece in split_windows(audio, self.max_seconds):
                if len(piece) < SAMPLE_RATE // 10:
                    continue
                pcm = np.ascontiguousarray(piece, dtype=np.float32)
                if dump:
                    os.makedirs(os.path.expanduser(dump), exist_ok=True)
                    path = _write_wav(pcm, os.path.expanduser(dump))
                    print(f"omnihear: audio saved to {path} "
                          f"({len(pcm) / SAMPLE_RATE:.1f}s, peak "
                          f"{float(np.abs(pcm).max()) if pcm.size else 0:.2f}; "
                          f"options {opts})")
                try:
                    result = self.session.run(pcm, timestamps="none", **opts)
                except transcribe_cpp.OutputTruncated as e:
                    # Includes OutputRepetition: the model looped or hit the
                    # length cap. Keep what it produced before that.
                    result = e.partial_result
                    print(f"omnihear: {type(e).__name__}; keeping the partial "
                          f"transcript ({result.text.strip()!r})" if result
                          else f"omnihear: {type(e).__name__}, no partial text")
                    if result is None:
                        continue
                if result.text.strip():
                    texts.append(result.text.strip())
                detected = detected or (result.language or None)
        lang = language or detected
        if lang and lang.endswith("-Latn"):
            lang = lang[:-5]
        return " ".join(texts), Info(lang, 1.0 if lang else 0.0)


def load(cfg: dict):
    model = cfg.get("indic_model") or DEFAULT_MODEL
    if is_gguf(model):
        return GgufEngine(model, output=cfg.get("indic_output", "native"),
                          library=cfg.get("indic_library", ""))
    return IndicEngine(cfg.get("indic_model") or DEFAULT_MODEL,
                       device=cfg.get("device", "cpu"),
                       quantize=cfg.get("indic_quantize", "auto"),
                       output=cfg.get("indic_output", "native"))
