"""Local voice Q&A (beta feature).

Retrieval-augmented answers over the user's own transcription history:
db.search_relevant() pulls relevant past transcriptions as context, and a
locally-running Ollama model turns (context + spoken question) into an
answer that gets typed instead of the raw question. Stdlib-only -- shells
out to the `ollama` CLI the same best-effort way feedback.py shells out to
notify-send/paplay: if Ollama isn't installed, isn't running, or times out,
callers fall back to typing the raw transcribed question. No audio or
transcript content leaves the device.
"""

import shutil
import subprocess

TIMEOUT = 30  # LLM generation is slower than this codebase's other subprocess calls


def available() -> bool:
    return shutil.which("ollama") is not None


def build_prompt(question: str, snippets: list[str]) -> str:
    if not snippets:
        return question
    context = "\n".join(f"- {s}" for s in snippets)
    return (
        "You are a voice assistant. Use the context below, drawn from the "
        "user's own past dictations, if it's relevant to the question. "
        "Answer concisely in plain text, no markdown.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )


def ask(prompt: str, model: str) -> str | None:
    try:
        out = subprocess.run(
            ["ollama", "run", model],
            input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def answer(question: str, snippets: list[str], model: str) -> str | None:
    if not question or not available():
        return None
    return ask(build_prompt(question, snippets), model)


if __name__ == "__main__":
    p = build_prompt("when is my flight", ["I booked a 6am flight to Denver"])
    assert "6am flight to Denver" in p and "when is my flight" in p
    assert build_prompt("hello", []) == "hello"
    print("qna self-check OK")
