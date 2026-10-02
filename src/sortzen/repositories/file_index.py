"""Remembered scan results (SQLite), so unchanged files are never read twice.

One row per file, keyed by its normalised path. A row is reused when the file's size,
date changed and cloud state still match.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..scanning.records import FileRecord

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    key TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    root TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    fingerprint TEXT,
    cloud_only INTEGER NOT NULL DEFAULT 0,
    details TEXT NOT NULL DEFAULT '{}',
    text TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS files_root ON files(root);
CREATE INDEX IF NOT EXISTS files_fingerprint ON files(fingerprint);
"""
_COLUMNS = ("path", "root", "role", "name", "ext", "kind", "size", "modified_ns", "fingerprint", "cloud_only",
            "details", "text", "error")


def path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _record(row) -> FileRecord:
    values = dict(zip(_COLUMNS, row))
    values["cloud_only"] = bool(values["cloud_only"])
    values["details"] = json.loads(values["details"] or "{}")
    return FileRecord(**values)


class FileIndex:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """One connection for a whole scan, used on the scanning thread only."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                conn.executescript(SCHEMA)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def known(conn, root_key: str) -> dict[str, FileRecord]:
        rows = conn.execute(f"SELECT key, {', '.join(_COLUMNS)} FROM files WHERE root = ?", (root_key,))
        return {row[0]: _record(row[1:]) for row in rows}

    @staticmethod
    def save(conn, record: FileRecord) -> None:
        values = [getattr(record, c) for c in _COLUMNS]
        values[_COLUMNS.index("cloud_only")] = int(record.cloud_only)
        values[_COLUMNS.index("details")] = json.dumps(record.details, ensure_ascii=False)
        conn.execute(f"INSERT OR REPLACE INTO files (key, {', '.join(_COLUMNS)}) VALUES ({', '.join('?' * 14)})",
                     [path_key(record.path), *values])

    @staticmethod
    def forget_missing(conn, root_key: str, seen: set[str]) -> int:
        gone = [k for (k,) in conn.execute("SELECT key FROM files WHERE root = ?", (root_key,)) if k not in seen]
        conn.executemany("DELETE FROM files WHERE key = ?", [(k,) for k in gone])
        return len(gone)

    def records(self, root) -> list[FileRecord]:
        with self.session() as conn:
            return sorted(self.known(conn, path_key(root)).values(), key=lambda r: r.path.lower())

    def with_fingerprint(self, fingerprint: str) -> list[FileRecord]:
        with self.session() as conn:
            rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM files WHERE fingerprint = ?", (fingerprint,))
            return [_record(row) for row in rows]
