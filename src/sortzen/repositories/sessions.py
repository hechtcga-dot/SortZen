"""Organizing sessions: one JSON file each in ``sessions`` in per-user storage.

A session remembers its name, its folders, the step it reached and which files are done, so it can
be reopened and carried on. Saved with a write-then-rename so a crash never leaves a half-written file.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CHOOSE, DUPLICATES, CATALOG, REVIEW, MOVED = "choose", "duplicates", "catalog", "review", "moved"
STAGES = (CHOOSE, DUPLICATES, CATALOG, REVIEW, MOVED)


@dataclass
class Session:
    name: str
    file: str = ""                  # its file name in the sessions folder
    created: float = 0.0
    updated: float = 0.0
    stage: str = CHOOSE
    sources: list = field(default_factory=list)         # [{"path", "mode"}]
    destinations: list = field(default_factory=list)
    keep_rule: str = "newest"       # which copy of a duplicate is kept
    copies_queued: int = 0          # extra copies moved into "To delete" in Step 2
    done: list = field(default_factory=list)            # files whose labels users confirmed
    settled: list = field(default_factory=list)         # files SortZen settled by itself as it learned
    to_review: list = field(default_factory=list)       # files sent to Review without labels
    later: list = field(default_factory=list)           # skipped or unticked: they come back at the end
    passed: list = field(default_factory=list)          # skipped again: they go to Review as they are
    apart: list = field(default_factory=list)           # files that don't belong with the others: one by one
    answered: int = 0               # batches answered in Step 3
    batches_at_start: int = 0
    settled_batches: int = 0
    review_batch: int = 0           # the Review batch shown last
    reviewed: list = field(default_factory=list)        # files whose Review batch was confirmed
    new_folders: list = field(default_factory=list)     # folders made in Review, made on disk when files move in
    moved: int = 0

    @property
    def catalogued(self) -> set[str]:
        """Files Step 3 has finished with."""
        from .file_index import path_key

        return {path_key(p) for p in (*self.done, *self.settled, *self.to_review, *self.passed)}


class SessionStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def sessions(self) -> list[Session]:
        """Every saved session, the latest used first."""
        found = []
        if self.folder.is_dir():
            for path in self.folder.glob("*.json"):
                session = self._read(path)
                if session is not None:
                    found.append(session)
        return sorted(found, key=lambda s: -s.updated)

    def new(self, name: str) -> Session:
        name = " ".join((name or "").split()) or "Organizing session"
        stem = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:40] or "session"
        file, n = f"{stem}.json", 2
        while (self.folder / file).exists():
            file, n = f"{stem}-{n}.json", n + 1
        now = time.time()
        session = Session(name, file, now, now)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        session.updated = time.time()
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / session.file
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(session), indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)

    def load(self, file: str) -> Session | None:
        return self._read(self.folder / file)

    def delete(self, file: str) -> None:
        try:
            (self.folder / file).unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _read(path: Path) -> Session | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("name"):
            return None
        known = {f.name for f in fields(Session)}
        session = Session(**{k: v for k, v in data.items() if k in known})
        session.file = path.name
        if session.stage not in STAGES:
            session.stage = CHOOSE
        return session
