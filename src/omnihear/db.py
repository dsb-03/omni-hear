"""SQLite transcription history for omnihear."""

import os
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
"""


def db_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
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
            self._conn.execute(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self):
        cols = {r["name"] for r in
                self._conn.execute("PRAGMA table_info(transcriptions)")}
        for col in ("cpu_percent", "memory_mb", "avg_logprob", "no_speech_prob",
                    "compression_ratio"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE transcriptions ADD COLUMN {col} REAL")

    def close(self):
        with self._lock:
            self._conn.close()

    def insert(self, text: str, audio_seconds: float, transcribe_ms: float,
               model: str, cpu_percent: float | None = None,
               memory_mb: float | None = None, avg_logprob: float | None = None,
               no_speech_prob: float | None = None,
               compression_ratio: float | None = None):
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcriptions"
                " (text, audio_seconds, transcribe_ms, model, cpu_percent, memory_mb,"
                "  avg_logprob, no_speech_prob, compression_ratio)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (text, audio_seconds, transcribe_ms, model, cpu_percent, memory_mb,
                 avg_logprob, no_speech_prob, compression_ratio),
            )
            self._conn.commit()

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
