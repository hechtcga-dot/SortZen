"""Remembered AI answers (SQLite), keyed by a file's contents, so the same file is never paid for twice."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_answers (
    key TEXT PRIMARY KEY,
    destination TEXT,
    sure INTEGER NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    content INTEGER NOT NULL DEFAULT 0,
    service TEXT NOT NULL DEFAULT '',
    time REAL NOT NULL
);
"""


@dataclass(frozen=True)
class AIAnswer:
    destination: str | None         # None: the AI found no folder that fits
    sure: int                       # 0-100, as the AI said
    why: str = ""
    content: bool = False           # the AI saw the beginning of the file (second pass)
    service: str = ""


def answer_key(record) -> str:
    """The file's contents identify it; a cloud-only file falls back to its name and size."""
    return record.fingerprint or f"name:{record.name.lower()}:{record.size}"


class AIAnswers:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        return conn

    def get_many(self, keys: list[str]) -> dict[str, AIAnswer]:
        found = {}
        if not keys:
            return found
        conn = self._connect()
        try:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                rows = conn.execute(f"SELECT key, destination, sure, why, content, service FROM ai_answers "
                                    f"WHERE key IN ({','.join('?' * len(chunk))})", chunk)
                for key, destination, sure, why, content, service in rows:
                    found[key] = AIAnswer(destination, sure, why, bool(content), service)
        finally:
            conn.close()
        return found

    def save(self, answers: dict[str, AIAnswer]) -> None:
        conn = self._connect()
        try:
            conn.executemany("INSERT OR REPLACE INTO ai_answers VALUES (?, ?, ?, ?, ?, ?, ?)",
                             [(k, a.destination, a.sure, a.why, int(a.content), a.service, time.time())
                              for k, a in answers.items()])
            conn.commit()
        finally:
            conn.close()

    def forget_all(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM ai_answers")
            conn.commit()
        finally:
            conn.close()
