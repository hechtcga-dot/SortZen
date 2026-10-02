"""Exact copies: files with the same contents, the copy to keep, and why. Never touches files.

Copies are found by size and content fingerprint. The copy kept is the one in an organised
place (a destination folder, then a subfolder that stays or is kept together), then one
without a copy number in its name, then the oldest, then the one with the shortest path.
Every group keeps exactly one copy; files left out, cloud-only files, Google link files and
empty files are never counted.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from ..scanning.file_types import GOOGLE_LINKS
from ..scanning.records import FileRecord
from .plan import KEEP_TOGETHER, STAYS, Plan

COPY_MARK = re.compile(r"( \(\d+\)| - copy( \(\d+\))?|^copy of .*| copy)$")


@dataclass
class Copy:
    path: str
    root: str                       # the added folder it is in
    modified_ns: int
    keep: bool = False
    ticked: bool = False            # queued for deletion unless unticked
    reasons: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class CopyGroup:
    fingerprint: str
    size: int
    copies: list[Copy]

    @property
    def kept(self) -> Copy:
        return next(c for c in self.copies if c.keep)

    @property
    def extras(self) -> list[Copy]:
        return [c for c in self.copies if not c.keep]

    @property
    def name(self) -> str:
        return self.kept.name

    def keep_instead(self, path: str) -> None:
        """Keep another copy; the one kept before becomes an extra (ticked)."""
        for c in self.copies:
            c.keep = c.path == path
            c.ticked = not c.keep and (c.ticked or not c.note)
            if c.keep:
                c.reasons = ["You chose this copy"]


def has_copy_mark(name: str) -> bool:
    return bool(COPY_MARK.search(os.path.splitext(name)[0].lower()))


def find_copies(records: list[FileRecord], plan: Plan, is_left_out=lambda path: False) -> list[CopyGroup]:
    groups: dict[tuple[int, str], list[FileRecord]] = defaultdict(list)
    for r in records:
        if r.fingerprint and r.size > 0 and not r.cloud_only and r.ext not in GOOGLE_LINKS \
                and not is_left_out(r.path):
            groups[(r.size, r.fingerprint)].append(r)
    outcomes = {os.path.normcase(f.path): f.outcome for f in plan.folders}
    found = []
    for (size, fp), members in groups.items():
        if len(members) < 2:
            continue
        place = {r.path: _place(r, outcomes) for r in members}
        ranked = sorted(members, key=lambda r: (-_order(place[r.path]), has_copy_mark(r.name), r.modified_ns,
                                                len(r.path), r.path.lower()))
        keeper = ranked[0]
        copies = []
        for r in ranked:
            c = Copy(r.path, r.root, r.modified_ns, keep=r is keeper)
            if place[r.path] == KEEP_TOGETHER:
                c.note = "Inside a folder that is kept together"
            c.ticked = not c.keep and not c.note
            copies.append(c)
        copies[0].reasons = _why(keeper, ranked[1:], place)
        found.append(CopyGroup(fp, size, copies))
    found.sort(key=lambda g: (-g.size * len(g.extras), g.name.lower()))
    return found


def _place(record: FileRecord, outcomes: dict[str, str]) -> str:
    """"destination", STAYS, KEEP_TOGETHER or "loose" for where a copy sits."""
    if record.role == "destination":
        return "destination"
    folder = os.path.normcase(os.path.dirname(record.path))
    root = os.path.normcase(record.root)
    while len(folder) > len(root):
        outcome = outcomes.get(folder)
        if outcome in (STAYS, KEEP_TOGETHER):
            return outcome
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return "loose"


def _order(place: str) -> int:
    return {"destination": 3, KEEP_TOGETHER: 2, STAYS: 2}.get(place, 0)


def _why(keeper: FileRecord, others: list[FileRecord], place: dict[str, str]) -> list[str]:
    reasons = []
    if _order(place[keeper.path]) > max(_order(place[o.path]) for o in others):
        reasons.append("It's in an organised folder")
    if not has_copy_mark(keeper.name) and any(has_copy_mark(o.name) for o in others):
        reasons.append("Its name has no copy number")
    if keeper.modified_ns < min(o.modified_ns for o in others):
        reasons.append("It's the oldest copy")
    return reasons or ["The copy with the shortest path"]
