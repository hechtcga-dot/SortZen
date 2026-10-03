"""Files SortZen couldn't place, gathered into groups users can place in one go. Never touches files.

A group is files with the same kind of name ("39 PDFs whose names are only numbers",
"41 pictures named like IMG_1234") or with a word in common ("12 files with “northgate” in
the name"). Each file is in one group at most; the biggest groups come first.
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

    def rule(self, destination: str) -> Rule:
        return Rule(destination=destination, **self.rule_parts)


def _plural(ext: str, n: int) -> str:
    if n == 1:
        return "file"
    return KIND_PLURAL.get(kind_of(ext), f"{ext.lstrip('.').upper()} files" if ext else "files")


def find_groups(unsure: list) -> list[FileGroup]:
    """Groups among the files SortZen couldn't place (Suggestions with a low percentage or no destination)."""
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
    found = []
    for group, members in sorted(groups, key=lambda g: -len(g[1]))[:MAX_GROUPS]:
        group.paths = sorted(s.path for s in members)
        leaning = Counter(s.destination for s in members if s.destination and s.destination != s.current_folder)
        if leaning:
            folder, votes = leaning.most_common(1)[0]
            group.suggestion = folder if votes >= len(members) / 2 else None
        found.append(group)
    return found
