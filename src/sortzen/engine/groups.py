"""Files SortZen couldn't place, gathered into groups users can place in one go. Never touches files.

A group is files with the same kind of name ("39 PDFs whose names are only numbers",
"41 pictures named like IMG_1234"), with a word in common ("12 files with “northgate” in
the name") or, given their clues, files that look alike ("9 files like “Lease draft.docx”").
Each file is in one group at most; the biggest groups come first, so one answer settles the
most files.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..scanning.file_types import kind_of
from .features import stem_of, words
from .rules import Rule, name_shape

MIN_GROUP = 3
MAX_GROUPS = 30
WORD_SHARE = 0.5            # a word in more than this share of the unsure files says too little
KIND_PLURAL = {"pdf": "PDFs", "word": "Word documents", "spreadsheet": "spreadsheets", "presentation": "presentations",
               "image": "pictures", "video": "videos", "audio": "music files", "archive": "zip files",
               "installer": "programs", "text": "text files", "email": "emails",
               "web page": "web pages"}


@dataclass
class FileGroup:
    key: str                    # stable across plans: "shape:#|.pdf" or "word:northgate"
    title: str                  # "39 PDFs whose names are only numbers"
    paths: list[str]
    suggestion: str | None = None           # the folder most of them lean towards, if any
    rule_parts: dict = field(default_factory=dict)      # what a rule for files like these looks like

    def rule(self, destination: str) -> Rule | None:
        """A rule for files like these, when their names have something in common."""
        return Rule(destination=destination, **self.rule_parts) if self.rule_parts else None


def _plural(ext: str, n: int) -> str:
    if n == 1:
        return "file"
    return KIND_PLURAL.get(kind_of(ext), f"{ext.lstrip('.').upper()} files" if ext else "files")


LOOKALIKE = 0.3            # files at least this alike (by their clues) form a group of look-alikes


def find_groups(unsure: list, vectors: dict | None = None, max_groups: int | None = MAX_GROUPS) -> list[FileGroup]:
    """Groups among the files SortZen couldn't place (Suggestions with a low percentage or no destination).
    ``vectors``: each file's clue vector, by path, to group the remaining files that look alike."""
    by_shape: dict[tuple[str, str], list] = defaultdict(list)
    for s in unsure:
        name = os.path.basename(s.path)
        shape = name_shape(name)
        if "#" in shape:
            by_shape[(shape, os.path.splitext(name)[1].lower())].append(s)
    groups: list[tuple[FileGroup, list]] = []
    used: set[str] = set()
    for (shape, ext), members in sorted(by_shape.items(), key=lambda kv: -len(kv[1])):
        if len(members) < MIN_GROUP:
            continue
        example = os.path.basename(members[0].path)
        kind = _plural(ext, len(members))
        title = (f"{len(members)} {kind} whose names are only numbers" if shape == "#"
                 else f"{len(members)} {kind} named like “{example}”")
        groups.append((FileGroup(f"shape:{shape}|{ext}", title, [], rule_parts={"word": "", "ext": ext,
                                                                                 "shape": shape, "example": example}),
                       members))
        used.update(s.path for s in members)
    rest = [s for s in unsure if s.path not in used]
    counts = Counter(w for s in rest for w in set(words(stem_of(os.path.basename(s.path)))) if len(w) >= 3)
    for word, n in counts.most_common():
        if n < MIN_GROUP or n > WORD_SHARE * max(len(unsure), 1):
            continue
        members = [s for s in rest if s.path not in used and word in words(stem_of(os.path.basename(s.path)))]
        if len(members) < MIN_GROUP:
            continue
        groups.append((FileGroup(f"word:{word}", f"{len(members)} files with “{word}” in the name", [],
                                 rule_parts={"word": word}), members))
        used.update(s.path for s in members)
    if vectors:
        rest = [s for s in unsure if s.path not in used and vectors.get(s.path)]
        for members in _lookalikes(rest, vectors):
            example = os.path.basename(members[0].path)
            groups.append((FileGroup(f"like:{os.path.normcase(members[0].path)}",
                                     f"{len(members)} files like “{example}”", [], rule_parts={}), members))
    found = []
    for group, members in sorted(groups, key=lambda g: -len(g[1]))[:max_groups]:
        members = sorted(members, key=lambda s: s.path.lower())
        group.paths = sorted(s.path for s in members)
        leaning = Counter(s.destination for s in members if s.destination and s.destination != s.current_folder)
        if leaning:
            folder, votes = leaning.most_common(1)[0]
            group.suggestion = folder if votes >= len(members) / 2 else None
        found.append(group)
    return found


def _lookalikes(files: list, vectors: dict) -> list[list]:
    """Files that look alike, by their clues: each group is a file and the files close enough to it."""
    from .planner import _Index

    index = _Index([vectors[s.path] for s in files])
    near = {pos: [other for other, sim in index.search(vectors[s.path], exclude=pos) if sim >= LOOKALIKE]
            for pos, s in enumerate(files)}
    taken: set[int] = set()
    found = []
    for pos in sorted(near, key=lambda k: -len(near[k])):
        if pos in taken:
            continue
        members = [pos] + [o for o in near[pos] if o not in taken]
        if len(members) >= MIN_GROUP:
            taken.update(members)
            found.append([files[m] for m in members])
    return found
