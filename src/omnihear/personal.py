"""Personalization: personal dictionary, snippets and per-app styles.

Stdlib only (metaphone, already a base dep, is used opportunistically for
sound-alike matching -- the same optional import as brain.py). Everything
lives in tables of the local history.db and is read fresh on every
transcription, so dashboard edits apply immediately without a restart.

- Dictionary: words the user wants spelled exactly ("Kubernetes", "GitHub",
  their own name), each with optional spoken forms ("omni hear"). Fed to
  Whisper as hints (pinned words first) and applied after transcription.
- Snippets: a spoken trigger ("insert my address") that expands to stored
  text. Matched only against the WHOLE utterance after normalization, so
  ordinary prose never fires one.
- App styles: none / casual / formal, per focused app (see focus.py), with
  "*" as the fallback for every other app.
"""

import difflib
import re
from datetime import datetime

from .brain import _match_case, _metaphone

STYLES = ("none", "casual", "formal")
DEFAULT_APP = "*"  # app_styles row used when the app has no style of its own

MAX_WORD = 100
MAX_ALIASES = 10
MAX_TRIGGER = 100
MAX_SNIPPET = 5000
MAX_ENTRIES = 1000

# Dropped while normalizing a snippet trigger, so "um, insert my address"
# still fires "insert my address".
_FILLERS = {"um", "uh", "er", "erm", "hmm", "uhm", "umm"}
_NORM_RE = re.compile(r"[^\w']+", re.UNICODE)


def normalize_trigger(text: str) -> str:
    words = [w.strip("'") for w in _NORM_RE.split(text.lower())]
    return " ".join(w for w in words if w and w not in _FILLERS)


def _parse_aliases(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for a in value:
        a = " ".join(str(a).split())
        if a and len(a) <= MAX_WORD and a.lower() not in (x.lower() for x in out):
            out.append(a)
    return out[:MAX_ALIASES]


def _phrase_re(phrase: str) -> re.Pattern:
    """Whole-phrase, case-insensitive, tolerant of extra spaces/hyphens
    between the words of a multi-word phrase."""
    parts = [re.escape(p) for p in phrase.split()]
    return re.compile(r"(?<![\w'])" + r"[\s-]+".join(parts) + r"(?![\w'])",
                      re.IGNORECASE)


def _split_re(word: str) -> re.Pattern | None:
    """For a single-token dictionary word of 5+ letters, also match it when
    Whisper splits it ("omni hear", "git-hub" -> "Omnihear", "GitHub")."""
    if len(word) < 5 or not word.isalpha():
        return None
    body = r"[\s-]?".join(re.escape(c) for c in word)
    return re.compile(r"(?<![\w'])" + body + r"(?![\w'])", re.IGNORECASE)


def _canon(word: str, matched: str) -> str:
    # An all-lowercase entry ("kubectl") follows the transcript's case at a
    # sentence start; anything with deliberate capitals is used verbatim.
    return _match_case(matched, word) if word.islower() else word


# -- styles -------------------------------------------------------------

_I_WORDS = {"i", "i'm", "i'll", "i've", "i'd"}
_SENTENCE_START_RE = re.compile(r"([.!?]\s+)([a-z])")


def apply_style(text: str, style: str, keep=()) -> str:
    """Rule-based tone. `keep` holds words (dictionary entries) whose case
    must never be touched."""
    if not text or style not in ("casual", "formal"):
        return text
    keep_l = {k.lower() for k in keep}
    if style == "formal":
        text = re.sub(r"(?<![\w'])(i)(?=(?:'(?:m|ll|ve|d))?(?![\w']))",
                      "I", text)
        text = text[:1].upper() + text[1:]
        text = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(),
                                      text)
        if text[-1:].isalnum():
            text += "."
        return text
    # casual: drop one trailing full stop (not "...", "?" or "!") and
    # lowercase the capital Whisper puts on the first word -- unless that
    # word looks like a name (capitalized again later, or a dictionary word).
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    m = re.match(r"([A-Z][a-z']*)(?![\w])", text)
    if m:
        first = m.group(1)
        later = re.search(r"(?<=\s)" + re.escape(first) + r"(?![\w'])", text)
        if (first.lower() not in _I_WORDS and first.lower() not in keep_l
                and not later):
            text = first.lower() + text[len(first):]
    return text


class Personal:
    """Shares the HistoryDB connection/lock (like Brain)."""

    def __init__(self, db):
        self.db = db

    def _exec(self, sql, params=()):
        with self.db._lock:
            cur = self.db._conn.execute(sql, params)
            self.db._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self.db._lock:
            return [dict(r) for r in self.db._conn.execute(sql, params)]

    @staticmethod
    def _now():
        return datetime.now().isoformat(timespec="seconds")

    # -- dictionary -----------------------------------------------------

    def list_words(self) -> list[dict]:
        rows = self._query(
            "SELECT word, sounds_like, pinned, created_ts FROM dictionary"
            " ORDER BY pinned DESC, word COLLATE NOCASE")
        for r in rows:
            r["sounds_like"] = _parse_aliases(r["sounds_like"])
            r["pinned"] = bool(r["pinned"])
        return rows

    def add_word(self, word: str, sounds_like=(), pinned: bool = False):
        """Add or update an entry. Returns an error string or None."""
        word = " ".join(str(word or "").split())
        if not word:
            return "word is empty"
        if len(word) > MAX_WORD:
            return f"word is longer than {MAX_WORD} characters"
        aliases = [a for a in _parse_aliases(sounds_like)
                   if a.lower() != word.lower()]
        exists = self._query("SELECT 1 FROM dictionary WHERE word = ?", (word,))
        if not exists and self._count("dictionary") >= MAX_ENTRIES:
            return f"dictionary is full ({MAX_ENTRIES} words)"
        # word is COLLATE NOCASE: re-adding "github" as "GitHub" respells it.
        self._exec(
            "INSERT INTO dictionary (word, sounds_like, pinned, created_ts)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(word) DO UPDATE SET"
            " word = excluded.word, sounds_like = excluded.sounds_like,"
            " pinned = excluded.pinned",
            (word, ", ".join(aliases), int(bool(pinned)), self._now()))
        return None

    def delete_word(self, word: str):
        self._exec("DELETE FROM dictionary WHERE word = ?", (word,))

    def _count(self, table):
        return self._query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def hint_words(self) -> list[str]:
        """Dictionary words for Whisper hints, pinned first."""
        return [r["word"] for r in self._query(
            "SELECT word FROM dictionary ORDER BY pinned DESC, created_ts")]

    def apply_dictionary(self, text: str) -> str:
        entries = self.list_words()
        if not text or not entries:
            return text
        # Longest spoken forms first, so "omni hear app" beats "omni hear".
        rules = []
        for e in entries:
            for phrase in [e["word"]] + e["sounds_like"]:
                rules.append((len(phrase), phrase, e["word"]))
        for _, phrase, word in sorted(rules, key=lambda r: -r[0]):
            text = _phrase_re(phrase).sub(lambda m: _canon(word, m.group(0)), text)
        for e in entries:
            rx = _split_re(e["word"])
            if rx:
                text = rx.sub(lambda m: _canon(e["word"], m.group(0)), text)
        # Sound-alike pass (needs metaphone; skipped silently without it).
        known = {e["word"].lower() for e in entries}
        by_key = {}
        for e in entries:
            if " " not in e["word"] and len(e["word"]) > 3:
                k = _metaphone(e["word"])
                if k:
                    by_key.setdefault(k, e["word"])
        if by_key:
            def swap(m):
                w = m.group(0)
                if w.lower() in known or len(w) <= 3:
                    return w
                cand = by_key.get(_metaphone(w) or "")
                if cand and difflib.SequenceMatcher(
                        a=w.lower(), b=cand.lower()).ratio() > 0.75:
                    return _canon(cand, w)
                return w
            text = re.sub(r"[A-Za-z']+", swap, text)
        return text

    def export_text(self) -> str:
        lines = ["# omnihear personal dictionary",
                 "# One word per line. '*' in front pins it;",
                 "# '= a, b' lists how it sounds when Whisper gets it wrong."]
        for e in self.list_words():
            line = ("*" if e["pinned"] else "") + e["word"]
            if e["sounds_like"]:
                line += " = " + ", ".join(e["sounds_like"])
            lines.append(line)
        return "\n".join(lines) + "\n"

    def import_text(self, text: str, replace: bool = False) -> dict:
        parsed = []
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            pinned = line.startswith("*")
            line = line.lstrip("*").strip()
            word, _, aliases = line.partition("=")
            parsed.append((word.strip(), aliases, pinned))
        if replace:
            self._exec("DELETE FROM dictionary")
        added, errors = 0, []
        for word, aliases, pinned in parsed:
            err = self.add_word(word, aliases, pinned)
            if err:
                errors.append(f"{word or '(empty)'}: {err}")
            else:
                added += 1
        return {"added": added, "errors": errors[:20]}

    # -- snippets -------------------------------------------------------

    def list_snippets(self) -> list[dict]:
        return self._query(
            "SELECT id, trigger, text, uses, created_ts FROM snippets"
            " ORDER BY trigger")

    def save_snippet(self, trigger: str, text: str, sid: int | None = None):
        """Create (or, with sid, edit) a snippet. Returns an error or None."""
        norm = normalize_trigger(trigger or "")
        text = str(text or "")
        if not norm:
            return "trigger phrase is empty"
        if len(norm) > MAX_TRIGGER:
            return f"trigger is longer than {MAX_TRIGGER} characters"
        if not text.strip():
            return "snippet text is empty"
        if len(text) > MAX_SNIPPET:
            return f"snippet text is longer than {MAX_SNIPPET} characters"
        clash = self._query("SELECT id FROM snippets WHERE trigger = ?", (norm,))
        if clash and clash[0]["id"] != sid:
            return f'"{norm}" is already a snippet trigger'
        if sid is None:
            if self._count("snippets") >= MAX_ENTRIES:
                return f"too many snippets ({MAX_ENTRIES})"
            self._exec("INSERT INTO snippets (trigger, text, created_ts)"
                       " VALUES (?, ?, ?)", (norm, text, self._now()))
        else:
            self._exec("UPDATE snippets SET trigger = ?, text = ? WHERE id = ?",
                       (norm, text, sid))
        return None

    def delete_snippet(self, sid: int):
        self._exec("DELETE FROM snippets WHERE id = ?", (sid,))

    def match_snippet(self, utterance: str) -> str | None:
        """Expansion if the whole utterance is a trigger, else None."""
        norm = normalize_trigger(utterance or "")
        if not norm:
            return None
        rows = self._query("SELECT id, text FROM snippets WHERE trigger = ?",
                           (norm,))
        if not rows:
            return None
        self._exec("UPDATE snippets SET uses = uses + 1 WHERE id = ?",
                   (rows[0]["id"],))
        return rows[0]["text"]

    # -- app styles -----------------------------------------------------

    def styles(self) -> dict:
        return {r["app"]: r["style"] for r in self._query(
            "SELECT app, style FROM app_styles")}

    def set_style(self, app: str, style: str):
        app = (app or "").strip().lower()
        if not app or len(app) > MAX_WORD:
            return "app name is empty or too long"
        if style not in STYLES:
            return "style must be one of: " + ", ".join(STYLES)
        self._exec("INSERT INTO app_styles (app, style) VALUES (?, ?)"
                   " ON CONFLICT(app) DO UPDATE SET style = excluded.style",
                   (app, style))
        return None

    def clear_style(self, app: str):
        self._exec("DELETE FROM app_styles WHERE app = ?",
                   ((app or "").strip().lower(),))

    def style_for(self, app: str | None) -> str:
        styles = self.styles()
        if app and app.lower() in styles:
            return styles[app.lower()]
        return styles.get(DEFAULT_APP, "none")


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from .db import HistoryDB

    with tempfile.TemporaryDirectory() as td:
        p = Personal(HistoryDB(Path(td) / "t.db"))
        assert p.add_word("Omnihear", "omni hear, omni here", pinned=True) is None
        assert p.add_word("GitHub") is None
        assert p.add_word("kubectl") is None
        assert p.add_word("") == "word is empty"
        assert p.hint_words()[0] == "Omnihear"
        out = p.apply_dictionary("I pushed omni here to github and git hub")
        assert out == "I pushed Omnihear to GitHub and GitHub", out
        assert p.apply_dictionary("Kubectl get pods") == "Kubectl get pods"
        assert p.apply_dictionary("my omnihearing aid") == "my omnihearing aid"
        assert p.add_word("github") is None  # respell in place, no duplicate
        assert [w["word"] for w in p.list_words()].count("github") == 1
        exported = p.export_text()
        assert "*Omnihear = omni hear, omni here" in exported, exported
        res = p.import_text("# c\n*Ana\nPyTorch = pie torch\n\n", replace=True)
        assert res == {"added": 2, "errors": []}, res
        assert p.apply_dictionary("train it in pie torch") == "train it in PyTorch"

        assert p.save_snippet("Insert my address.", "1 Main St\nSpringfield") is None
        assert p.save_snippet("insert my address", "dup") is not None
        assert p.match_snippet("Um, insert my address!") == "1 Main St\nSpringfield"
        assert p.match_snippet("please insert my address now") is None
        assert p.list_snippets()[0]["uses"] == 1

        assert apply_style("Hey, are you free at 3.", "casual") == "hey, are you free at 3"
        assert apply_style("John said hi to John.", "casual") == "John said hi to John"
        assert apply_style("I think so.", "casual") == "I think so"
        assert apply_style("Ana is here.", "casual", keep=["Ana"]) == "Ana is here"
        assert apply_style("Wait...", "casual") == "wait..."
        assert apply_style("i think i'm done. see you", "formal") == "I think I'm done. See you."
        assert apply_style("Is it?", "formal") == "Is it?"
        assert p.style_for("slack") == "none"
        p.set_style("*", "formal")
        p.set_style("Slack", "casual")
        assert p.style_for("slack") == "casual" and p.style_for("code") == "formal"
        assert p.style_for(None) == "formal"
        assert p.set_style("x", "loud") is not None
        print("personal self-check OK")
