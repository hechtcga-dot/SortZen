"""Batches: files shown together, one batch per screen, the surest first. Never touches files.

- ``catalog_batches`` gathers the files being sorted into batches that one answer settles: the
  same kind of name, a shared word or files that look alike, then files SortZen would give the
  same labels and send to the same folder, then files with no clear label by kind.
- ``review_batches`` gathers files by the labels they carry, and where they go, for checking.

A batch's certainty is how sure SortZen is of its labels (and, less, of its folder); batches are
ordered surest first so users clear the easy ones and SortZen learns before the hard ones.
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field

from ..scanning.file_types import kind_of
from .groups import KIND_PLURAL, find_groups

MAX_BATCH = 40              # files on one screen at most; bigger groups are split
LABEL_SHARE = 0.5           # a label suggested for a batch is guessed for at least this share of its files
APPLIED = 50                # a guess this sure counts as the file's label


@dataclass
class Batch:
    key: str
    title: str
    paths: list[str]
    labels: list[tuple[str, int]] = field(default_factory=list)    # suggested labels, surest first
    certainty: int = 0
    why: str = ""                   # what the files have in common
    destinations: list[str] = field(default_factory=list)


def _labels(paths: list[str], guesses: dict[str, list[tuple[str, int]]]) -> list[tuple[str, int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for p in paths:
        for label, percent in guesses.get(p, []):
            if percent >= APPLIED:
                found[label].append(percent)
    wanted = [(label, round(sum(v) / len(v))) for label, v in found.items() if len(v) >= LABEL_SHARE * len(paths)]
    return sorted(wanted, key=lambda lp: (-lp[1], lp[0]))


def _certainty(paths: list[str], guesses: dict, sureness: dict[str, int]) -> int:
    if not paths:
        return 0
    total = 0.0
    for p in paths:
        top = max((pc for _, pc in guesses.get(p, [])), default=0)
        total += 0.7 * top + 0.3 * sureness.get(p, 0)
    return round(total / len(paths))


def _chunks(paths: list[str], size: int) -> list[list[str]]:
    return [paths[i:i + size] for i in range(0, len(paths), size)] or [[]]


def catalog_batches(suggestions: list, guesses: dict[str, list[tuple[str, int]]], vectors: dict | None,
                    display=lambda p: p, max_size: int = MAX_BATCH) -> list[Batch]:
    """Every file in ``suggestions`` (the plan's files being sorted) in exactly one batch, surest first.
    ``guesses``: labels by path, (label, percent)."""
    by_path = {s.path: s for s in suggestions}
    sureness = {s.path: (s.percent if s.destination else 0) for s in suggestions}
    raw: list[tuple[str, str, str, list[str]]] = []          # key, title, why, paths
    used: set[str] = set()
    for g in find_groups(suggestions, vectors, max_groups=None):
        raw.append((g.key, g.title, g.title, list(g.paths)))
        used.update(g.paths)
    rest: dict[tuple, list[str]] = defaultdict(list)
    for s in suggestions:
        if s.path in used:
            continue
        labels = tuple(sorted(label for label, pc in guesses.get(s.path, []) if pc >= APPLIED))
        if labels:
            rest[("labels", labels, s.destination or "")].append(s.path)
        elif s.destination and s.destination != s.current_folder:
            rest[("folder", s.destination)].append(s.path)
        else:
            rest[("kind", kind_of(os.path.splitext(s.path)[1].lower()))].append(s.path)
    for key, paths in rest.items():
        n = len(paths)
        if key[0] == "labels":
            title = f"{n} file{'s' if n != 1 else ''} SortZen would label {', '.join(key[1])}"
            why = "SortZen guesses the same labels" + (f" and folder ({display(key[2])})" if key[2] else "")
        elif key[0] == "folder":
            title = f"{n} file{'s' if n != 1 else ''} going to {display(key[1])}"
            why = "SortZen would send them to the same folder"
        else:
            plural = KIND_PLURAL.get(key[1], "files") if n != 1 else "file"
            title = f"{n} {plural} with no clear label"
            why = "Nothing in them says what they are about yet"
        raw.append(("|".join(str(k) for k in key), title, why, sorted(paths, key=str.lower)))
    batches = []
    for key, title, why, paths in raw:
        parts = _chunks(paths, max_size)
        for i, part in enumerate(parts):
            suffix = f" (part {i + 1} of {len(parts)})" if len(parts) > 1 else ""
            batches.append(Batch(f"{key}#{i}", title + suffix, part, _labels(part, guesses),
                                 _certainty(part, guesses, sureness), why,
                                 sorted({by_path[p].destination for p in part if by_path[p].destination})))
    batches.sort(key=lambda b: (-b.certainty, -len(b.paths), b.title.lower()))
    return batches


def review_batches(suggestions: list, labels_of, display=lambda p: p, max_size: int = 60) -> list[Batch]:
    """The files the plan moves, by the labels they carry (then by folder when there are many), surest first."""
    by_labels: dict[tuple, list] = defaultdict(list)
    for s in suggestions:
        if s.destination and os.path.normcase(s.destination) != os.path.normcase(s.current_folder):
            by_labels[tuple(labels_of(s.path))].append(s)
    batches = []
    for labels, members in by_labels.items():
        if len(members) > max_size:
            by_folder: dict[str, list] = defaultdict(list)
            for s in members:
                by_folder[s.destination].append(s)
            groups = list(by_folder.values())
        else:
            groups = [members]
        name = " and ".join(labels) if labels else "No labels"
        for group in groups:
            for part in _chunks(sorted(group, key=lambda s: s.path.lower()), max_size):
                folders = sorted({s.destination for s in part})
                n = len(part)
                title = f"{name} · {n} file{'s' if n != 1 else ''} → {len(folders)} folder{'s' if len(folders) != 1 else ''}"
                certainty = round(sum(s.percent for s in part) / n)
                batches.append(Batch(f"{'|'.join(labels)}|{folders[0]}|{part[0].path}", title, [s.path for s in part],
                                     [(label, 100) for label in labels], certainty, "", folders))
    batches.sort(key=lambda b: (-b.certainty, -len(b.paths), b.title.lower()))
    return batches


def label_merge_suggestion(labels: list[str]) -> tuple[str, str] | None:
    """Two labels that are surely the same ("Tax" and "Taxes", "photo" and "Photos"): (merge this, into this)."""
    def base(word: str) -> str:
        if len(word) > 4 and word.endswith(("xes", "ses", "ches", "shes")):
            return word[:-2]
        return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word

    seen = {}
    for label in labels:
        key = " ".join(base(w) for w in label.lower().split())
        if key in seen and seen[key] != label:
            keep, drop = sorted([seen[key], label], key=lambda x: (-len(x), x))
            return drop, keep
        seen[key] = label
    return None
