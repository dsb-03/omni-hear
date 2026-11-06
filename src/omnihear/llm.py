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
    url = base_url()
    if url is None:
        return None
    req = urllib.request.Request(
        url + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except (OSError, ValueError, urllib.error.URLError):
        return None


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


def generate(prompt: str, model: str, timeout: float,
             system: str | None = None) -> str | None:
    body = {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": KEEP_ALIVE, "options": {"temperature": 0.2}}
    if system:
        body["system"] = system
    out = _post("/api/generate", body, timeout)
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


def polish(text: str, model: str, budget_s: float) -> str | None:
    """LLM cleanup of one dictation within budget_s seconds; None if it is
    slow, unavailable, or its answer doesn't look like an edit of `text`."""
    out = generate(text, model, budget_s, system=POLISH_SYSTEM)
    if not out:
        return None
    out = tidy_output(out)
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
    os.environ["OLLAMA_HOST"] = "example.com:11434"
    assert base_url() is None and generate("x", "m", 1) is None
    os.environ["OLLAMA_HOST"] = "0.0.0.0:9999"
    assert base_url() == "http://127.0.0.1:9999"
    del os.environ["OLLAMA_HOST"]
    assert base_url() == "http://127.0.0.1:11434"
    print("llm self-check OK")
