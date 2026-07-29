"""SQLite transcription history for omnihear."""

import os
import re
import sqlite3
import sys
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    text TEXT NOT NULL,
    audio_seconds REAL,
    transcribe_ms REAL,
    model TEXT,
    cpu_percent REAL,
    memory_mb REAL,
    avg_logprob REAL,
    no_speech_prob REAL,
    compression_ratio REAL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original TEXT NOT NULL,
    corrected TEXT NOT NULL,
    metaphone TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    last_ts TEXT,
    transcription_id INTEGER,
    embedding BLOB,
    UNIQUE(original, corrected)
);
CREATE TABLE IF NOT EXISTS vocab (
    word TEXT PRIMARY KEY,
    metaphone TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    manual INTEGER NOT NULL DEFAULT 0,
    last_ts TEXT
);
"""

# Full-text index over transcriptions, used for local retrieval (RAG context
# and voice Q&A). Kept separate from SCHEMA and applied best-effort: some
# minimal sqlite3 builds omit FTS5, and losing retrieval must never break
# core history storage.
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS transcriptions_fts USING fts5(
    text, content='transcriptions', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS transcriptions_ai AFTER INSERT ON transcriptions BEGIN
  INSERT INTO transcriptions_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS transcriptions_ad AFTER DELETE ON transcriptions BEGIN
  INSERT INTO transcriptions_fts(transcriptions_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS transcriptions_au AFTER UPDATE ON transcriptions BEGIN
  INSERT INTO transcriptions_fts(transcriptions_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO transcriptions_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

# Function words dropped before building an FTS query -- OR-ing them in
# would match almost every row and drown out the terms that actually carry
# topical signal (this is retrieval, not the substring history search box).
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "and", "or", "but", "not", "no",
    "so", "if", "it", "its", "this", "that", "these", "those", "i", "me",
    "my", "we", "us", "our", "you", "your", "he", "him", "his", "she",
    "her", "they", "them", "their", "do", "does", "did", "have", "has",
    "had", "with", "as", "by", "from", "about", "into", "up", "out",
    "can", "will", "would", "should", "could", "what", "when", "where",
    "who", "how", "just", "like",
}


def db_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "omnihear" / "history.db"


class HistoryDB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._fts_available = self._init_fts()
            self._conn.commit()

    def _init_fts(self) -> bool:
        """Create the FTS5 index (if the sqlite3 build supports it) and
        backfill any rows inserted before it existed. Returns availability."""
        try:
            self._conn.executescript(_FTS_SCHEMA)
        except sqlite3.OperationalError:
            return False
        indexed = self._conn.execute(
            "SELECT COUNT(*) AS n FROM transcriptions_fts").fetchone()["n"]
        total = self._conn.execute(
            "SELECT COUNT(*) AS n FROM transcriptions").fetchone()["n"]
        if indexed < total:
            self._conn.execute(
                "INSERT INTO transcriptions_fts(rowid, text)"
                " SELECT id, text FROM transcriptions"
                " WHERE id NOT IN (SELECT rowid FROM transcriptions_fts)")
        return True

    def _migrate(self):
        cols = {r["name"] for r in
                self._conn.execute("PRAGMA table_info(transcriptions)")}
        for col in ("cpu_percent", "memory_mb", "avg_logprob", "no_speech_prob",
                    "compression_ratio"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE transcriptions ADD COLUMN {col} REAL")
        if "corrected_text" not in cols:
            self._conn.execute(
                "ALTER TABLE transcriptions ADD COLUMN corrected_text TEXT")

    def close(self):
        with self._lock:
            self._conn.close()

    def insert(self, text: str, audio_seconds: float, transcribe_ms: float,
               model: str, cpu_percent: float | None = None,
               memory_mb: float | None = None, avg_logprob: float | None = None,
               no_speech_prob: float | None = None,
               compression_ratio: float | None = None):
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO transcriptions"
                " (text, audio_seconds, transcribe_ms, model, cpu_percent, memory_mb,"
                "  avg_logprob, no_speech_prob, compression_ratio)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (text, audio_seconds, transcribe_ms, model, cpu_percent, memory_mb,
                 avg_logprob, no_speech_prob, compression_ratio),
            )
            self._conn.commit()
            return cur.lastrowid

    def set_corrected(self, row_id: int, text: str):
        with self._lock:
            self._conn.execute(
                "UPDATE transcriptions SET corrected_text = ? WHERE id = ?",
                (text, row_id))
            self._conn.commit()

    def get(self, row_id: int) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM transcriptions WHERE id = ?",
                (row_id,)).fetchone()
        return dict(r) if r else None

    def search_relevant(self, query: str, limit: int = 5,
                        exclude_id: int | None = None) -> list[dict]:
        """Keyword-retrieve past transcriptions relevant to `query` (FTS5
        bm25 ranking). Used for RAG context and voice Q&A. Returns []
        if FTS5 isn't available or the query has no usable tokens --
        callers must treat retrieval as best-effort, not required."""
        if not self._fts_available:
            return []
        tokens = re.findall(r"[A-Za-z0-9']+", query.lower())
        tokens = [t for t in tokens if t not in _STOPWORDS][:24]
        if not tokens:
            return []
        limit = max(1, min(int(limit), 50))
        match = " OR ".join(f'"{t}"' for t in tokens)
        # Two-step: FTS5's bm25() must be ordered against the virtual table
        # directly (rank breaks across a JOIN), so rank ids first, then
        # fetch the full rows -- fetch a few extra in case exclude_id drops one.
        try:
            with self._lock:
                ranked = self._conn.execute(
                    "SELECT rowid FROM transcriptions_fts"
                    " WHERE transcriptions_fts MATCH ?"
                    " ORDER BY bm25(transcriptions_fts) LIMIT ?",
                    (match, limit + 1)).fetchall()
                ids = [r["rowid"] for r in ranked if r["rowid"] != exclude_id][:limit]
                if not ids:
                    return []
                placeholders = ",".join("?" * len(ids))
                rows = self._conn.execute(
                    f"SELECT id, text, ts FROM transcriptions"
                    f" WHERE id IN ({placeholders})", ids).fetchall()
        except sqlite3.OperationalError:
            return []
        by_id = {r["id"]: dict(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def search(self, q: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        sql = "SELECT * FROM transcriptions"
        params: list = []
        if q:
            sql += " WHERE text LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            totals = self._conn.execute(
                "SELECT COUNT(*) AS n,"
                " COALESCE(SUM(audio_seconds), 0) AS audio_seconds,"
                " COALESCE(AVG(transcribe_ms), 0) AS avg_transcribe_ms,"
                " COALESCE(AVG(cpu_percent), 0) AS avg_cpu_percent,"
                " COALESCE(AVG(memory_mb), 0) AS avg_memory_mb,"
                " COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1), 0)"
                "   AS words"
                " FROM transcriptions"
            ).fetchone()
            per_day = self._conn.execute(
                "SELECT substr(ts, 1, 10) AS day,"
                " COUNT(*) AS n,"
                " COALESCE(SUM(audio_seconds), 0) AS audio_seconds,"
                " COALESCE(AVG(transcribe_ms), 0) AS avg_transcribe_ms,"
                " COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1), 0)"
                "   AS words"
                " FROM transcriptions GROUP BY day ORDER BY day DESC LIMIT 30"
            ).fetchall()
        return {
            "totals": dict(totals),
            "per_day": [dict(r) for r in reversed(per_day)],
        }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        db = HistoryDB(Path(td) / "t.db")
        assert db._fts_available, "FTS5 should be available in this build"
        db.insert("please book a flight to Denver next week", 3.0, 50.0, "base.en")
        db.insert("remind me to email Jon about the Denver trip", 2.0, 40.0, "base.en")
        db.insert("what's the weather like today", 1.5, 30.0, "base.en")
        hits = db.search_relevant("when is the Denver flight", limit=5)
        texts = [h["text"] for h in hits]
        assert any("flight to Denver" in t for t in texts), texts
        assert not any("weather" in t for t in texts), texts
        assert db.search_relevant("   ") == []
        db.close()
    print("db self-check OK")
