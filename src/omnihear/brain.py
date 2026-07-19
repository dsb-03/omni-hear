"""Common Brain: local learning from user corrections (beta feature).

Learns word/phrase corrections, applies them to future transcripts, and
feeds learned vocabulary to Whisper as hotwords / initial_prompt.
All data stays in the local history.db. No network.
"""

import difflib
import re
from datetime import datetime

_WORD_RE = re.compile(r"[\w']+|[^\w\s]", re.UNICODE)


def _metaphone(word: str) -> str | None:
    try:
        from metaphone import doublemetaphone
    except ImportError:
        return None
    key = doublemetaphone(word)[0]
    return key or None


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _match_case(template: str, word: str) -> str:
    if template.isupper():
        return word.upper()
    if template[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


class Brain:
    """Shares the HistoryDB connection/lock — no second DB file."""

    def __init__(self, db, min_count: int = 2):
        self.db = db
        self.min_count = min_count

    def _exec(self, sql, params=()):
        with self.db._lock:
            cur = self.db._conn.execute(sql, params)
            self.db._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self.db._lock:
            return [dict(r) for r in self.db._conn.execute(sql, params)]

    # -- learning ---------------------------------------------------------

    def learn_correction(self, original: str, corrected: str,
                         transcription_id: int | None = None) -> list[tuple[str, str]]:
        """Diff original vs corrected text; store replaced phrases. Returns learned pairs."""
        a, b = _tokens(original), _tokens(corrected)
        sm = difflib.SequenceMatcher(a=[t.lower() for t in a],
                                     b=[t.lower() for t in b])
        pairs = []
        ts = datetime.now().isoformat(timespec="seconds")
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "replace":
                continue
            orig = " ".join(a[i1:i2]).lower()
            corr = " ".join(b[j1:j2])
            if not orig or not corr or orig == corr.lower():
                continue
            pairs.append((orig, corr))
            self._exec(
                "INSERT INTO corrections (original, corrected, metaphone, last_ts,"
                " transcription_id) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(original, corrected) DO UPDATE SET"
                " count = count + 1, last_ts = excluded.last_ts",
                (orig, corr, _metaphone(orig), ts, transcription_id))
            for w in _tokens(corr):
                if len(w) > 2 and w.isalpha():
                    self.add_word(w, manual=False)
        return pairs

    def add_word(self, word: str, manual: bool = True):
        ts = datetime.now().isoformat(timespec="seconds")
        self._exec(
            "INSERT INTO vocab (word, metaphone, manual, last_ts)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(word) DO UPDATE SET count = count + 1,"
            " manual = max(manual, excluded.manual), last_ts = excluded.last_ts",
            (word, _metaphone(word), int(manual), ts))

    def delete_word(self, word: str):
        self._exec("DELETE FROM vocab WHERE word = ?", (word,))

    def delete_correction(self, cid: int):
        self._exec("DELETE FROM corrections WHERE id = ?", (cid,))

    # -- applying ---------------------------------------------------------

    def apply(self, text: str) -> str:
        """Replace learned mishearings in a fresh transcript."""
        rules = self._query(
            "SELECT original, corrected FROM corrections WHERE count >= ?"
            " ORDER BY count DESC", (self.min_count,))
        for r in rules:
            pat = re.compile(r"\b" + re.escape(r["original"]) + r"\b",
                             re.IGNORECASE)
            text = pat.sub(lambda m: _match_case(m.group(0), r["corrected"]),
                           text)
        # phonetic pass: swap unknown words that sound like learned vocab
        vocab = {v["word"].lower(): v for v in self._query(
            "SELECT word, metaphone, count FROM vocab"
            " WHERE count >= ? OR manual = 1", (self.min_count,))}
        by_key: dict[str, str] = {}
        for w, v in vocab.items():
            if v["metaphone"]:
                by_key.setdefault(v["metaphone"], v["word"])
        if by_key:
            def swap(m):
                w = m.group(0)
                if w.lower() in vocab or len(w) <= 2:
                    return w
                cand = by_key.get(_metaphone(w) or "")
                if cand and difflib.SequenceMatcher(
                        a=w.lower(), b=cand.lower()).ratio() > 0.75:
                    return _match_case(w, cand)
                return w
            text = re.compile(r"[A-Za-z']+").sub(swap, text)
        return text

    # -- whisper hints ----------------------------------------------------

    def _top_words(self, n: int) -> list[str]:
        return [r["word"] for r in self._query(
            "SELECT word FROM vocab ORDER BY manual DESC, count DESC LIMIT ?",
            (n,))]

    def hotwords(self) -> str | None:
        words = self._top_words(50)
        return " ".join(words) or None

    def initial_prompt(self) -> str | None:
        words = self._top_words(20)
        if not words:
            return None
        prompt = "Vocabulary: " + ", ".join(words) + "."
        return prompt[:200]

    # -- dashboard --------------------------------------------------------

    def stats(self) -> dict:
        (n_corr,) = self._query(
            "SELECT COUNT(*) AS n FROM corrections")[0].values()
        (n_vocab,) = self._query("SELECT COUNT(*) AS n FROM vocab")[0].values()
        (applied,) = self._query(
            "SELECT COALESCE(SUM(count - 1), 0) AS n FROM corrections")[0].values()
        return {"corrections": n_corr, "words": n_vocab, "reinforced": applied}

    def list_words(self, limit: int = 200) -> list[dict]:
        return self._query(
            "SELECT word, count, manual FROM vocab"
            " ORDER BY manual DESC, count DESC LIMIT ?", (limit,))

    def list_corrections(self, limit: int = 200) -> list[dict]:
        return self._query(
            "SELECT id, original, corrected, count, last_ts FROM corrections"
            " ORDER BY count DESC, id DESC LIMIT ?", (limit,))


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from .db import HistoryDB

    with tempfile.TemporaryDirectory() as td:
        brain = Brain(HistoryDB(Path(td) / "t.db"), min_count=2)
        pairs = brain.learn_correction(
            "please email jon doe about omni here",
            "please email Jon Doh about Omnihear")
        assert ("doe", "Doh") in pairs and ("omni here", "Omnihear") in pairs, pairs
        assert brain.apply("tell omni here") == "tell omni here"  # count 1 < 2
        brain.learn_correction("ping omni here now", "ping Omnihear now")
        out = brain.apply("I love omni here")
        assert out == "I love Omnihear", out
        brain.add_word("Kubernetes")
        assert "Kubernetes" in (brain.hotwords() or "")
        assert brain.initial_prompt().startswith("Vocabulary:")
        s = brain.stats()
        assert s["corrections"] == 2 and s["words"] >= 2, s
        print("brain self-check OK")
