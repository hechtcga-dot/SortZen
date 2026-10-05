"""The catalog: the categories files are sorted into, shown and edited as one tree.

Categories come from the destination folders (and the folders being tidied), one per
folder, nested like the folders. Program folders are left out. Users' edits are kept in
settings ("catalog"): display names, extra folders, categories never used as destinations,
categories merged into others, and feedback. Notes are the folder notes.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from ..engine.overview import CODE_EXTS, PROGRAM_MARKER_EXTS, PROGRAM_MARKERS
from ..repositories.file_index import path_key
from ..scanning.file_types import is_queue_folder

FEEDBACK = {"right": "Looks right", "too_broad": "Too broad: split it", "too_narrow": "Too narrow: merge it",
            "wrong_name": "Wrong name", "comment": "Comment"}
EXAMPLES = 5
MAX_DEPTH = 6               # deeper folders count towards their category, without categories of their own


@dataclass
class Category:
    path: str                           # its main folder: what identifies it
    name: str
    parent: str | None
    folders: list[str]                  # the main folder, then any extra folders
    files: int = 0                      # files in it and its subfolders
    direct: list[str] = field(default_factory=list)     # names of the files directly in it
    note: str = ""
    rules: int = 0
    chosen: int = 0                     # files users chose this folder for (placed by hand or in the plan)
    hidden: bool = False                # never a destination
    merged_into: str | None = None
    feedback: list[dict] = field(default_factory=list)
    children: list[str] = field(default_factory=list)

    @property
    def examples(self) -> list[str]:
        return self.direct[:EXAMPLES]

    @property
    def last_feedback(self) -> str:
        return self.feedback[-1]["kind"] if self.feedback else ""


def looks_like_program(folder: str) -> bool:
    """A folder of code, setup files or a built program: kept whole, never a category."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return False
    names = {e.name.lower() for e in entries}
    if names & (PROGRAM_MARKERS | {".git", "node_modules"}):
        return True
    exts = [os.path.splitext(e.name)[1].lower() for e in entries if e.is_file(follow_symlinks=False)]
    if any(x in PROGRAM_MARKER_EXTS for x in exts):
        return True
    code = sum(1 for x in exts if x in CODE_EXTS)
    return (code >= 5 and code >= 0.4 * len(exts)) or (".exe" in exts and ".dll" in exts)


def build(roots: list[str], edits: dict, notes: dict, rules: list, records=None,
          chosen: dict | None = None) -> list[Category]:
    """Every category, parents before children. ``records`` (remembered files) give counts and examples
    without opening anything; without them the folders are listed. ``chosen`` are users' choices of
    folder by file."""
    chosen_counts: dict[str, int] = {}
    for destination in (chosen or {}).values():
        if destination:
            chosen_counts[path_key(destination)] = chosen_counts.get(path_key(destination), 0) + 1
    note_by_key = {path_key(k): v for k, v in notes.items()}
    names = {path_key(k): v for k, v in (edits.get("names") or {}).items()}
    extra = {path_key(k): list(v) for k, v in (edits.get("extra") or {}).items()}
    hidden = {path_key(p) for p in edits.get("hidden") or []}
    merged = {path_key(k): v for k, v in (edits.get("merged") or {}).items()}
    feedback = {path_key(k): list(v) for k, v in (edits.get("feedback") or {}).items()}
    direct: dict[str, list[str]] = {}
    if records is not None:
        for r in records:
            direct.setdefault(path_key(os.path.dirname(r.path)), []).append(r.name)
    found: dict[str, Category] = {}
    order: list[str] = []

    def add(folder: str, parent: str | None, depth: int) -> int:
        key = path_key(folder)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            entries = []
        files = direct.get(key) if records is not None else \
            [e.name for e in entries if e.is_file(follow_symlinks=False) and not e.name.startswith((".", "~$"))]
        category = Category(folder, names.get(key, os.path.basename(folder) or folder), parent,
                            [folder] + extra.get(key, []), note=note_by_key.get(key, ""), hidden=key in hidden,
                            merged_into=merged.get(key), feedback=feedback.get(key, []),
                            direct=sorted(files or []))
        category.rules = sum(1 for r in rules if path_key(r.destination) == key)
        category.chosen = chosen_counts.get(key, 0)
        found[key] = category
        order.append(key)
        total = len(category.direct)
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or e.name.startswith((".", "$")) or is_queue_folder(e.name):
                continue
            if looks_like_program(e.path) or depth >= MAX_DEPTH:
                total += _count(e.path, direct, records)
                continue
            category.children.append(e.path)
            total += add(e.path, folder, depth + 1)
        category.files = total
        return total

    for root in roots:
        if os.path.isdir(root) and path_key(root) not in found:
            add(root, None, 0)
    return [found[k] for k in order]


def _count(folder: str, direct: dict, records) -> int:
    if records is not None:
        key = path_key(folder)
        return sum(len(v) for k, v in direct.items() if k == key or k.startswith(key.rstrip(os.sep) + os.sep))
    return sum(len(files) for _, _, files in os.walk(folder))


def with_feedback(edits: dict, folder: str, kind: str, text: str = "") -> dict:
    """Edits with one more piece of feedback on a category."""
    edits = dict(edits)
    feedback = {k: list(v) for k, v in (edits.get("feedback") or {}).items()}
    key = next((k for k in feedback if path_key(k) == path_key(folder)), os.path.abspath(folder))
    feedback.setdefault(key, []).append({"kind": kind, "text": (text or "").strip(), "time": time.time()})
    edits["feedback"] = feedback
    return edits
