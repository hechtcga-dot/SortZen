"""Turns ticked plan rows into move requests, and describes a move before it happens."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..engine.plan import SORT_INSIDE, Plan
from ..mover import MoveRequest
from ..repositories.file_index import path_key
from .plan_view import PlanRow


@dataclass
class MovePreview:
    files: int = 0
    folders: int = 0                    # kept-together folders, moved whole
    files_in_folders: int = 0
    destinations: list[tuple[str, int, bool]] = field(default_factory=list)    # (folder, items, new)
    renamed: list[str] = field(default_factory=list)            # names that get " (2)"
    emptied: list[str] = field(default_factory=list)            # "sort inside" folders left empty, then removed
    problems: int = 0                                           # rows with a problem shown in the plan

    @property
    def items(self) -> int:
        return self.files + self.folders


def _inside(key: str, folder: str) -> bool:
    return key.startswith(folder.rstrip(os.sep) + os.sep)


def requests(rows: list[PlanRow]) -> list[MoveRequest]:
    """One request per ticked row that moves; files inside a folder that moves whole go with it."""
    moving = [r for r in rows if r.moves]
    folders = [path_key(r.path) for r in moving if r.is_folder]
    found, seen = [], set()
    for r in moving:
        key = path_key(r.path)
        if key in seen or any(_inside(key, f) for f in folders):
            continue
        seen.add(key)
        found.append(MoveRequest(r.path, r.destination))
    return found


def emptied_folders(plan: Plan, moving: list[MoveRequest], roots: list[str]) -> list[str]:
    """"Sort inside" folders that will hold no files once the move is done (added folders never count)."""
    root_keys = {path_key(r) for r in roots}
    keys = {path_key(m.path) for m in moving}
    folders = [path_key(m.path) for m in moving if os.path.isdir(m.path)]
    found = []
    for f in plan.folders:
        if f.outcome != SORT_INSIDE or path_key(f.path) in root_keys or not os.path.isdir(f.path):
            continue
        left = False
        for folder, _, names in os.walk(f.path):
            folder_key = path_key(folder)
            if folder_key in keys or any(folder_key == d or _inside(folder_key, d) for d in folders):
                continue
            if any(path_key(os.path.join(folder, n)) not in keys for n in names):
                left = True
                break
        if not left:
            found.append(f.path)
    return found


def preview(plan: Plan, rows: list[PlanRow], roots: list[str]) -> MovePreview:
    moving = requests(rows)
    by_path = {path_key(r.path): r for r in rows}
    result = MovePreview()
    counts: dict[str, int] = {}
    for m in moving:
        row = by_path[path_key(m.path)]
        if row.is_folder:
            result.folders += 1
            result.files_in_folders += row.files
        else:
            result.files += 1
        counts[m.destination] = counts.get(m.destination, 0) + 1
        if row.problems:
            result.problems += 1
        if any("already there" in p for p in row.problems):
            result.renamed.append(row.name)
    result.destinations = sorted(((d, n, not os.path.isdir(d)) for d, n in counts.items()), key=lambda x: -x[1])
    result.emptied = emptied_folders(plan, moving, roots)
    return result
