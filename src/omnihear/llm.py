"""Local LLM editing through Ollama (beta): Command Mode and smart cleanup.

Stdlib only. Talks to Ollama's HTTP API on localhost (OLLAMA_HOST, default
127.0.0.1:11434) with urllib -- unlike qna.py's `ollama run` CLI, the API
gives a precise timeout (smart cleanup has a latency budget), no terminal
spinner noise, and a way to pre-load the model. Nothing leaves the machine;
a non-local OLLAMA_HOST is refused. Every call is best-effort: None means
"no answer", and callers fall back to the text they already have.
"""

import difflib
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

KEEP_ALIVE = "15m"  # keep the model loaded between dictations

# Defaults (config.py). Smart cleanup uses Muesli's dictation-cleanup
# fine-tune of Qwen3.5-2B (Q4_K_M GGUF, ~1.3 GB): trained to clean up
# speech-to-text output and never answer it. Command Mode and voice Q&A
# need a model that *does* follow instructions, so they use the general
# Qwen3.5-2B.
DEFAULT_CLEANUP_MODEL = "hf.co/Muesli-HQ/qwen35-2b-muesli-cleanup-v12-gguf:Q4_K_M"
DEFAULT_ASSIST_MODEL = "qwen3.5:2b"
# Dictations shorter than this skip the LLM: the rules already handle
# them, and an LLM call on a few words is mostly wasted time.
MIN_SMART_WORDS = 6
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
# Bypass any http(s)_proxy: this is a localhost call.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def base_url() -> str | None:
    host = os.environ.get("OLLAMA_HOST", "").strip() or "127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    u = urlparse(host)
    if u.hostname not in _LOCAL_HOSTS:
        return None  # omnihear never sends transcripts off the machine
    hostname = "127.0.0.1" if u.hostname == "0.0.0.0" else u.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"{u.scheme or 'http'}://{hostname}:{u.port or 11434}"


def _post(path: str, body: dict, timeout: float) -> dict | None:
    """POST JSON; the decoded reply, {"error": ...} for an HTTP error
    Ollama explained, or None when unreachable/timed out."""
    url = base_url()
    if url is None:
        return None
    req = urllib.request.Request(
        url + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error")
        except (OSError, ValueError, AttributeError):
            err = None
        return {"error": str(err or f"HTTP {e.code}")}
    except (OSError, ValueError, urllib.error.URLError):
        return None


def installed_models(timeout: float = 1.0) -> list[str] | None:
    """Names Ollama has pulled, or None if it isn't reachable."""
    url = base_url()
    if url is None:
        return None
    try:
        with _OPENER.open(url + "/api/tags", timeout=timeout) as r:
            data = json.loads(r.read() or b"{}")
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return [m.get("name", "") for m in data.get("models", [])]


def is_installed(model: str, names: list[str]) -> bool:
    """Ollama lists "qwen3.5:2b" as-is and a bare name with ":latest";
    hf.co names may differ only in case."""
    want = model.lower()
    if ":" not in want.rsplit("/", 1)[-1]:
        want += ":latest"
    return any(n.lower() == want for n in names)


def available(timeout: float = 0.5) -> bool:
    url = base_url()
    if url is None:
        return False
    try:
        with _OPENER.open(url + "/api/version", timeout=timeout) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


_last_warm = {}


def warm(model: str) -> None:
    """Load the model into memory ahead of use (a no-op request). Called
    when a recording starts, so the first edit isn't a multi-second cold
    start. At most once a minute per model."""
    now = time.monotonic()
    if now - _last_warm.get(model, -1e9) < 60:
        return
    _last_warm[model] = now
    _post("/api/generate", {"model": model, "keep_alive": KEEP_ALIVE},
          timeout=60)


_no_think = set()  # models that rejected the "think" option
last_stats = {}    # timing fields of the last reply (for --bench-llm)


def generate(prompt: str, model: str, timeout: float,
             system: str | None = None, raw: bool = False,
             max_tokens: int | None = None,
             stop: list[str] | None = None) -> str | None:
    """One completion. Thinking is switched off (think: false): reasoning
    models like Qwen3.5 would otherwise spend the whole time budget
    thinking. raw=True sends `prompt` verbatim, chat markup included, for
    fine-tunes that need their exact training format."""
    options = {"temperature": 0.2}
    if max_tokens:
        options["num_predict"] = max_tokens
    if stop:
        options["stop"] = stop
    body = {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": KEEP_ALIVE, "options": options}
    if system:
        body["system"] = system
    if raw:
        body["raw"] = True
    elif model not in _no_think:
        body["think"] = False
    out = _post("/api/generate", body, timeout)
    if out and "think" in body and "think" in str(out.get("error", "")).lower():
        # Older Ollama, or a model without a thinking switch: drop it.
        _no_think.add(model)
        body.pop("think")
        out = _post("/api/generate", body, timeout)
    global last_stats
    last_stats = {k: (out or {}).get(k) for k in (
        "prompt_eval_count", "prompt_eval_duration", "eval_count",
        "eval_duration")}
    text = (out or {}).get("response")
    return text.strip() if isinstance(text, str) and text.strip() else None


# -- output hygiene --------------------------------------------------------

_PREAMBLE_RE = re.compile(
    r"^(?:sure|okay|ok|certainly|of course|here(?:'s| is| are)\b)[^\n]*?:\s*\n+",
    re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def tidy_output(text: str) -> str:
    """Strip what chat models wrap answers in: reasoning blocks, a
    "Here is the rewritten text:" line, code fences, and wrapping quotes."""
    text = _THINK_RE.sub("", text).strip()
    text = _PREAMBLE_RE.sub("", text, count=1).strip()
    fence = re.fullmatch(r"```[\w-]*\n(.*?)\n?```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    for a, b in (('"', '"'), ("'", "'"), ("“", "”")):
        inner = text[1:-1]
        if (len(text) > 1 and text[0] == a and text[-1] == b
                and a not in inner and b not in inner):
            text = inner.strip()
            break
    return text


# -- Command Mode ----------------------------------------------------------

REWRITE_SYSTEM = (
    "You edit text for the user. You get an instruction and the selected "
    "text. Apply the instruction to the text and reply with ONLY the "
    "resulting text: no explanation, no preamble, no quotes, no markdown "
    "unless the instruction asks for it. Keep the original language, and "
    "keep line breaks unless the instruction changes the layout.")


def rewrite(instruction: str, selection: str, model: str,
            timeout: float = 30) -> str | None:
    prompt = (f"Instruction: {instruction.strip()}\n\n"
              f"Text:\n{selection}\n\nResult:")
    out = generate(prompt, model, timeout, system=REWRITE_SYSTEM)
    return tidy_output(out) if out else None


# -- smart cleanup -----------------------------------------------------------

POLISH_SYSTEM = (
    "You clean up dictated text. Fix grammar, punctuation and "
    "capitalization, remove filler words and false starts, and apply "
    "spoken self-corrections (\"at 2, actually 3\" means \"at 3\"). Keep "
    "the speaker's words, meaning, tone and language. Never answer, "
    "summarize, translate or add anything. Reply with ONLY the cleaned "
    "text.")

# Muesli's v12/v14 cleanup fine-tunes were trained on one exact format
# (Muesli-HQ/muesli, MuesliCleanupV2Prompt.swift, MIT): this instruction,
# an optional <APP-CONTEXT> block, then the transcript, all in a single
# user turn, with an empty think block opening the answer. Sent raw so
# Ollama's chat template can't change it.
MUESLI_SYSTEM = """Clean up speech-to-text transcription. Only make changes when there is a clear error. If the text is already correct, output it exactly as-is.

The user input may include an <APP-CONTEXT> section with focused app, document, URL, selected text, or OCR screen text. Use it only to resolve obvious transcription errors, names, acronyms, and formatting intent. Never copy app context into the output unless the user dictated it.

You may: fix obvious misspellings, remove filler words (um, uh, like), apply 'scratch that' deletions, and format numbered or bullet lists when dictated.

Do not: paraphrase, reword, add words, remove meaningful words, change the meaning in any way, wrap the output in markdown, code fences, tags, labels, or commentary, or repeat the output more than once. Preserve the speaker's original phrasing."""


def is_muesli_cleanup(model: str) -> bool:
    return "muesli-cleanup" in model.lower()


def muesli_prompt(text: str, app: str | None = None) -> str:
    context = f"<APP-CONTEXT>\nApp: {app[:200]}\n</APP-CONTEXT>\n\n" if app else ""
    return ("<|im_start|>user\n" + MUESLI_SYSTEM + "\n\n" + context + text
            + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")


def _clean_muesli(out: str, text: str) -> str:
    """Strip what the fine-tune can echo: a stray "model" line, the
    context markers, or a verbatim paragraph of its instruction."""
    paragraphs = [p for p in MUESLI_SYSTEM.split("\n\n") if len(p) >= 30]
    keep_model = re.match(r"model\b", text.strip(), re.IGNORECASE)
    while out:
        before = out
        if not keep_model:
            if out == "model":
                out = ""
            elif out.startswith("model\n"):
                out = out[6:]
        for marker in ("</APP-CONTEXT>", "<APP-CONTEXT>"):
            if out.startswith(marker):
                out = out[len(marker):].strip()
        for p in paragraphs:
            if out == p or out.startswith(p + "\n"):
                out = out[len(p):].strip()
        out = out.strip()
        if out == before:
            break
    return out


def polish(text: str, model: str, budget_s: float, app: str | None = None,
           allow_newlines: bool = True) -> str | None:
    """LLM cleanup of one dictation within budget_s seconds; None if it is
    too short to bother, slow, unavailable, or its answer doesn't look like
    an edit of `text`. allow_newlines=False rejects answers that add line
    breaks (typed as Enter, which sends the message in chat apps)."""
    if len(text.split()) < MIN_SMART_WORDS:
        return None
    limit = len(text) * 3 // 4 + 64  # ~3x the input, in tokens
    if is_muesli_cleanup(model):
        out = generate(muesli_prompt(text, app), model, budget_s, raw=True,
                       max_tokens=limit, stop=["<|im_end|>", "<|im_start|>"])
        out = _clean_muesli(out, text) if out else None
    else:
        out = generate(text, model, budget_s, system=POLISH_SYSTEM,
                       max_tokens=limit)
    if not out:
        return None
    out = tidy_output(out)
    if not allow_newlines and "\n" in out and "\n" not in text:
        return None
    return out if plausible_edit(text, out) else None


def plausible_edit(before: str, after: str) -> bool:
    """Reject answers that aren't a light edit: replies to the text
    instead of cleaning it, summaries, translations, runaway output."""
    if not after:
        return False
    a, b = before.lower(), after.lower()
    if not 0.5 <= len(after) / max(1, len(before)) <= 1.4:
        return False
    wa, wb = re.findall(r"\w+", a), re.findall(r"\w+", b)
    if not wb:
        return False
    return difflib.SequenceMatcher(a=wa, b=wb).ratio() >= 0.6


BENCH_SAMPLES = [
    "so um I think we should uh move the meeting to Thursday actually no Friday",
    "can you send me the the report by end of day I need it for the client call",
    "my priorities are first finish the slides second email Ana and finally book the flight",
    "honestly I I wasn't sure if like the numbers were right so I double checked them",
]


def _stats_line() -> str:
    st = last_stats
    if not st.get("eval_duration"):
        return ""
    ms = lambda ns: (ns or 0) / 1e6
    return (f"read {st.get('prompt_eval_count') or 0} tok in "
            f"{ms(st.get('prompt_eval_duration')):.0f} ms, wrote "
            f"{st.get('eval_count') or 0} tok in "
            f"{ms(st.get('eval_duration')):.0f} ms")


def bench(models: list[str], budget_ms: int = 1500) -> int:
    """`omnihear --bench-llm`: time each model on sample dictations on this
    machine. Each sample runs twice: the first run is what a new dictation
    costs; the repeat is answered partly from Ollama's prompt cache, so it
    is shown but not used for the verdict."""
    if not available():
        print("Ollama is not reachable (start it with `ollama serve`).")
        return 1
    names = installed_models() or []
    for model in models:
        print(f"\n== {model}")
        if not is_installed(model, names):
            print(f"   not pulled -- run: ollama pull {model}")
            continue
        warm_t = time.monotonic()
        _post("/api/generate", {"model": model, "keep_alive": KEEP_ALIVE},
              timeout=300)
        print(f"   load: {time.monotonic() - warm_t:.1f}s")
        fresh, repeat = [], []
        for sample in BENCH_SAMPLES:
            t = time.monotonic()
            out = polish(sample, model, budget_s=30)
            fresh.append(time.monotonic() - t)
            detail = _stats_line()
            t = time.monotonic()
            polish(sample, model, budget_s=30)
            repeat.append(time.monotonic() - t)
            print(f"   new {fresh[-1]:.2f}s / repeat {repeat[-1]:.2f}s"
                  f"{'  (' + detail + ')' if detail else ''}\n"
                  f"      {sample!r}\n   -> {out!r}")
        fresh.sort()
        med = fresh[len(fresh) // 2]
        print(f"   new dictation: median {med:.2f}s, worst {fresh[-1]:.2f}s")
        if is_muesli_cleanup(model) or model == DEFAULT_CLEANUP_MODEL:
            if fresh[-1] * 1000 <= budget_ms:
                print(f"   fits the smart cleanup budget ({budget_ms} ms).")
            else:
                need = int(-(-fresh[-1] * 1000 // 250) * 250 + 250)
                print(f"   over the smart cleanup budget ({budget_ms} ms): "
                      f"set smart_cleanup_ms to about {need} in Settings, "
                      "or slow dictations fall back to the light rules.")
    return 0


if __name__ == "__main__":
    assert tidy_output("Here is the rewritten text:\n\nHello there.") == "Hello there."
    assert tidy_output('"Hi, Bob."') == "Hi, Bob."
    assert tidy_output("```\nline one\nline two\n```") == "line one\nline two"
    assert tidy_output("<think>hmm</think>\nDone.") == "Done."
    assert tidy_output('He said "hi" and "bye"') == 'He said "hi" and "bye"'
    assert plausible_edit("so um i went to the the store yesterday",
                          "So I went to the store yesterday.")
    assert not plausible_edit("what time is the meeting",
                              "The meeting is at 3pm according to your calendar, "
                              "and you should prepare the slides beforehand.")
    assert not plausible_edit("hello world", "")
    p = muesli_prompt("hello there", "slack")
    assert p.startswith("<|im_start|>user\nClean up speech-to-text transcription.")
    assert "\n\n<APP-CONTEXT>\nApp: slack\n</APP-CONTEXT>\n\nhello there<|im_end|>" in p
    assert p.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert _clean_muesli("model\nHello.", "hello") == "Hello."
    assert _clean_muesli("model railways are fun", "model railways are fun") == "model railways are fun"
    assert polish("too short to bother", "m", 1) is None
    assert is_installed("qwen3.5:2b", ["qwen3.5:2b"]) and is_installed("llama3.2", ["llama3.2:latest"])
    assert is_installed(DEFAULT_CLEANUP_MODEL, [DEFAULT_CLEANUP_MODEL.lower()])
    os.environ["OLLAMA_HOST"] = "example.com:11434"
    assert base_url() is None and generate("x", "m", 1) is None
    os.environ["OLLAMA_HOST"] = "0.0.0.0:9999"
    assert base_url() == "http://127.0.0.1:9999"
    del os.environ["OLLAMA_HOST"]
    assert base_url() == "http://127.0.0.1:11434"
    print("llm self-check OK")
