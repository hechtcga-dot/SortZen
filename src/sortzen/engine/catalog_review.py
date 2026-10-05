"""Suggestions for a better catalog, worked out on the PC. Never touches files.

- Split: a big category whose files fall into groups by a word they share
  ("Split “Payroll” into Timesheets (14) and Stubs (12)"). Users' "Too broad" lowers the size.
- Merge: sibling categories with nearly the same name ("Invoice" and "Invoices"); after users'
  "Too narrow", the closest category by the words its files share, or the category above it.
- Empty: a category with no files, no note and no subcategories.
Categories users marked "Looks right", hidden or merged ones, and suggestions turned down
are left alone.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

from ..repositories.file_index import path_key
from .features import DEFAULT_NAME_WORDS, stem_of, words

SPLIT_FILES = 30            # files directly in a category before a split is suggested
SPLIT_FILES_ASKED = 8       # ...when users said it is too broad
MAX_PARTS = 4
MAX_SUGGESTIONS = 20


@dataclass
class CatalogSuggestion:
    kind: str                   # "split", "merge", "empty", "rename", "new"
    category: str               # the category's folder
    title: str
    why: str = ""
    into: str | None = None     # merge: the category it goes into
    name: str = ""              # rename: the new name; new: the subcategory's name
    note: str = ""              # new: what belongs in it
    parts: list[tuple[str, list[str]]] = field(default_factory=list)   # split: (name, file names)
    source: str = "SortZen"

    @property
    def key(self) -> str:
        return f"{self.kind}|{path_key(self.category)}|{path_key(self.into) if self.into else self.name.lower()}"


def _name_words(name: str) -> set[str]:
    return set(words(name))


def _similar_names(a: str, b: str) -> bool:
    wa, wb = _name_words(a), _name_words(b)
    if wa and wa == wb:
        return True
    la, lb = a.lower().strip(), b.lower().strip()
    if min(len(la), len(lb)) >= 5 and _distance(la, lb) <= 2:
        return True
    return bool(wa and wb and (wa < wb or wb < wa) and len(wa | wb) <= 3)


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def split_parts(category, limit: int) -> list[tuple[str, list[str]]]:
    """Groups of the category's own files that share a word not in its name."""
    names = list(category.direct)
    if len(names) < limit:
        return []
    own = _name_words(category.name) | _name_words(os.path.basename(category.path))
    file_words = {n: set(words(stem_of(n))) - own - DEFAULT_NAME_WORDS for n in names}
    left, parts = set(names), []
    for _ in range(MAX_PARTS):
        counts = Counter(w for n in left for w in file_words[n] if len(w) >= 3)
        ranked = sorted(counts.items(), key=lambda wc: (-wc[1], -len(wc[0]), wc[0]))   # ties: the longer word
        best = next(((w, c) for w, c in ranked if max(3, 0.1 * len(names)) <= c <= 0.7 * len(names)), None)
        if best is None:
            break
        members = sorted(n for n in left if best[0] in file_words[n])
        tokens = (re.sub(r"\d+", "", t) for n in members for t in re.split(r"[\s_\-.]+", stem_of(n)))
        spelled = next((t for t in tokens if t and t.lower().rstrip("s") == best[0].rstrip("s")), best[0])
        parts.append((spelled[:1].upper() + spelled[1:], members))
        left -= set(members)
    covered = sum(len(m) for _, m in parts)
    return parts if parts and (covered >= 0.3 * len(names) or limit == SPLIT_FILES_ASKED) else []


def review(categories: list, declined: set[str] = frozenset()) -> list[CatalogSuggestion]:
    by_path = {path_key(c.path): c for c in categories}
    found: list[CatalogSuggestion] = []
    live = [c for c in categories if not c.hidden and not c.merged_into]
    for c in live:
        feedback = c.last_feedback
        if feedback == "right":
            continue
        siblings = [o for o in live if o.parent and c.parent and path_key(o.parent) == path_key(c.parent)
                    and o is not c]
        limit = SPLIT_FILES_ASKED if feedback == "too_broad" else SPLIT_FILES
        parts = split_parts(c, limit)
        if parts:
            listed = ", ".join(f"{name} ({len(m)})" for name, m in parts)
            found.append(CatalogSuggestion(
                "split", c.path, f"Split “{c.name}” ({len(c.direct)} files) into {listed}",
                "You said it is too broad" if feedback == "too_broad" else "Its files fall into groups by name",
                parts=parts))
        if c.parent:
            twin = next((o for o in siblings if _similar_names(c.name, o.name) and o.files >= c.files), None)
            if twin is None and feedback == "too_narrow":
                mine = {w for n in c.direct for w in words(stem_of(n))}
                scored = [(len(mine & {w for n in o.direct for w in words(stem_of(n))}), o) for o in siblings]
                scored = [x for x in scored if x[0]]
                twin = max(scored, key=lambda x: x[0])[1] if scored else by_path.get(path_key(c.parent))
            if twin is not None:
                found.append(CatalogSuggestion(
                    "merge", c.path, f"Merge “{c.name}” ({c.files} files) into “{twin.name}” ({twin.files} files)",
                    "You said it is too narrow" if feedback == "too_narrow" else "The names are nearly the same",
                    into=twin.path))
        if c.parent and c.files == 0 and not c.note and not c.children and not c.feedback:
            found.append(CatalogSuggestion("empty", c.path, f"“{c.name}” is empty",
                                           "Write what belongs in it, or don't put files there"))
    asked = [s for s in found if any(path_key(s.category) == path_key(c.path) and c.last_feedback
                                     for c in categories)]
    rest = [s for s in found if s not in asked]
    ordered = asked + sorted(rest, key=lambda s: ("merge", "split", "empty").index(s.kind))
    return [s for s in ordered if s.key not in declined][:MAX_SUGGESTIONS]
