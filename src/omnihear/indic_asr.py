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


def _write_wav(audio) -> str:
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    fd, path = tempfile.mkstemp(prefix="omnihear-", suffix=".wav")
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

    def transcribe(self, audio, language=None):
        """(text, Info) for 16 kHz mono float32 audio. `language` is an
        ISO code, or None to let the model detect it (flex only)."""
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


def load(cfg: dict) -> IndicEngine:
    return IndicEngine(cfg.get("indic_model") or DEFAULT_MODEL,
                       device=cfg.get("device", "cpu"),
                       quantize=cfg.get("indic_quantize", "auto"),
                       output=cfg.get("indic_output", "native"))
