"""Local, stdlib-only spoken punctuation/editing commands.

Runs on transcribed text before it's typed (opt-in via the
`voice_commands` config flag — see app.py). Two independent behaviors:
- PUNCTUATION: whole-word replacement of spoken punctuation names with
  symbols ("comma" -> ",").
- is_undo: an exact-match (after normalizing) transcript that means
  "delete what I just typed" instead of being typed literally.
"""

import re

# Symbols that attach to the previous word -- the space before the spoken
# word is swallowed ("hello comma world" -> "hello, world").
_ATTACHED = {
    "period": ".", "full stop": ".", "comma": ",", "question mark": "?",
    "exclamation mark": "!", "exclamation point": "!", "colon": ":",
    "semicolon": ";",
}
# Line breaks -- standalone, surrounding spaces are left alone.
_STANDALONE = {"new paragraph": "\n\n", "new line": "\n", "newline": "\n"}
PUNCTUATION = {**_ATTACHED, **_STANDALONE}
UNDO_PHRASES = {"scratch that", "undo that", "delete that"}


def _alternation(words):
    # Longest phrase first so "new paragraph" matches before "new line" would.
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_ATTACHED_RE = re.compile(r"\s*\b(" + _alternation(_ATTACHED) + r")\b",
                          re.IGNORECASE)
_STANDALONE_RE = re.compile(r"\b(" + _alternation(_STANDALONE) + r")\b",
                            re.IGNORECASE)


def is_undo(text: str) -> bool:
    return text.strip().strip(".,!?").lower() in UNDO_PHRASES


def apply_punctuation(text: str) -> str:
    text = _ATTACHED_RE.sub(lambda m: _ATTACHED[m.group(1).lower()], text)
    text = _STANDALONE_RE.sub(lambda m: _STANDALONE[m.group(1).lower()], text)
    return text


if __name__ == "__main__":
    assert apply_punctuation("hello comma world period") == "hello, world."
    assert apply_punctuation("new paragraph next") == "\n\n next"
    assert apply_punctuation("go to a new line here") == "go to a \n here"
    assert is_undo("scratch that") and is_undo("Undo that.")
    assert not is_undo("I love scratch built pasta")
    print("commands self-check OK")
