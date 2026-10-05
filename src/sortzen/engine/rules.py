"""Rules users make: "names with this word (and of this type) go to this folder". Never touches files.

- A rule places every matching file from the folders being sorted, at 100%, with the rule as
  its reason. Files users placed themselves keep their own choice.
- A rule is suggested when users send two or more files to the same folder and their names
  share a word: only when the rule would also place other files in the plan, never moves a
  file SortZen is already sure belongs elsewhere, and was not turned down before.
- For a session, several rules can be suggested for one folder, one for each name users' files share.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter
from dataclasses import dataclass

from ..scanning.file_types import kind_of
from .features import stem_of, words
from .plan import FOLDER_REVIEW, KEEP_TOGETHER, STAYS, Plan, Reason

MIN_EXAMPLES = 2            # files sent to the same folder before a rule is suggested
SURE_ELSEWHERE = 90         # a suggestion this sure is never overruled by a suggested rule


def name_shape(name: str) -> str:
    """A name with its numbers as #: "IMG_2041.jpg" and "IMG_77.jpg" both give "img_#"."""
    stem = os.path.splitext(name)[0].lower()
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", stem)).strip()


KINDS = {"pdf": "PDFs", "word": "Word documents", "spreadsheet": "spreadsheets", "presentation": "presentations",
         "image": "pictures", "video": "videos", "audio": "music files", "archive": "zip files",
         "installer": "programs and installers", "text": "text files", "email": "emails", "web page": "web pages",
         "ebook": "e-books", "form": "forms"}
BY = {"": "", "year": "in a folder for each year", "month": "in a folder for each month"}
YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")


@dataclass(frozen=True)
class Rule:
    """Files that meet every condition set go to ``destination``. Conditions: a label, a word in the name,
    a name shape, a type of file (extension or kind), text the name contains, and the folder the file is in."""
    word: str                   # a name word, as the engine reads it (lower case, singular); "" for none
    destination: str
    ext: str = ""               # ".pdf"; "" for any type
    shape: str = ""             # a name shape ("#", "img_#"); "" for none
    example: str = ""           # a name it was made from, for describing it
    label: str = ""             # files with this label
    contains: str = ""          # text the name contains, as typed
    kind: str = ""              # a kind of file ("pdf", "image" ...)
    inside: str = ""            # files in this folder (or the folders in it)
    by: str = ""                # "year" or "month": a folder for each, inside the destination
    name: str = ""              # what users call the rule
    on: bool = True             # rules switched off place nothing

    @property
    def conditions(self) -> int:
        return sum(bool(x) for x in (self.word, self.shape, self.label, self.contains, self.kind, self.inside,
                                     self.ext))

    def matches(self, name: str, labels=(), path: str = "") -> bool:
        if not self.on or not self.conditions:
            return False
        ext = os.path.splitext(name)[1].lower()
        if self.label and self.label.lower() not in {x.lower() for x in labels}:
            return False
        if self.ext and ext != self.ext:
            return False
        if self.kind and kind_of(ext) != self.kind:
            return False
        if self.shape and name_shape(name) != self.shape:
            return False
        if self.word and self.word not in words(stem_of(name)):
            return False
        if self.contains and self.contains.lower() not in name.lower():
            return False
        if self.inside:
            folder = os.path.normcase(os.path.abspath(self.inside)).rstrip(os.sep)
            here = os.path.normcase(os.path.abspath(os.path.dirname(path))) if path else ""
            if not (here == folder or here.startswith(folder + os.sep)):
                return False
        return True

    def destination_for(self, name: str, modified: float = 0.0) -> str:
        """Where a matching file goes: the destination, or a folder for its year (or month) inside it. The
        year comes from the name ("Tax return 2023.pdf"), otherwise from when the file was last saved."""
        if self.by not in ("year", "month"):
            return self.destination
        found = YEAR.search(name)
        if found and self.by == "year":
            return os.path.join(self.destination, found.group(1))
        if not modified:
            return os.path.join(self.destination, found.group(1)) if found else self.destination
        stamp = time.localtime(modified)
        if self.by == "year":
            return os.path.join(self.destination, str(stamp.tm_year))
        return os.path.join(self.destination, f"{stamp.tm_year}-{stamp.tm_mon:02d}")

    @property
    def key(self) -> str:
        label = f"|label:{self.label.lower()}" if self.label else ""
        more = "".join(f"|{k}:{v}" for k, v in (("contains", self.contains.lower()), ("kind", self.kind),
                                                 ("inside", os.path.normcase(self.inside)), ("by", self.by)) if v)
        return f"{self.word}|{self.ext}|{self.shape}{label}{more}|{os.path.normcase(os.path.abspath(self.destination))}"

    def describe(self, display=lambda p: p) -> str:
        if not self.conditions:
            return f"Needs a condition: change this rule (it sends nothing to {display(self.destination)})"
        parts = []
        if self.shape:
            parts.append("names that are only numbers" if self.shape == "#" else
                         f"names like “{self.example or self.shape}”")
        if self.word:
            parts.append(f"names with “{self.word}”")
        if self.contains:
            parts.append(f"names containing “{self.contains}”")
        if self.label:
            parts.append(f"labelled “{self.label}”")
        if self.kind:
            parts.append(KINDS.get(self.kind, self.kind))
        if self.inside:
            parts.append(f"in {display(self.inside)}")
        if not parts:
            parts.append("files")
        what = "Files " + ", ".join(parts) if parts[0].startswith("labelled") else \
            parts[0][0].upper() + parts[0][1:] + (", " + ", ".join(parts[1:]) if parts[1:] else "")
        if self.ext:
            what += f" ({self.ext.lstrip('.').upper()} files)"
        text = f"{what} go to {display(self.destination)}" + (f", {BY[self.by]}" if self.by in BY and self.by else "")
        text = text if self.on else f"{text} (switched off)"
        return f"{self.name}: {text}" if self.name else text


@dataclass
class RuleSuggestion:
    rule: Rule
    examples: int               # files users sent there that the rule covers
    matches: list[str]          # other files in the plan the rule would place


def _ordered(rules: list[Rule]) -> list[Rule]:
    """The rules with the most conditions first; among equals, a name shape or a type before a word alone and
    a label rule last; then later rules before earlier."""
    return sorted(reversed([r for r in rules if r.on]),
                  key=lambda r: (-r.conditions, not r.shape, not r.ext, bool(r.label)))


def apply_rules(plan: Plan, rules: list[Rule], is_valid, is_source, display=lambda p: p,
                labels_of=lambda path: (), modified_of=lambda path: 0.0, is_source_folder=lambda path: False) -> int:
    """Place matching files by the rules, and folders that move as they are by the rules their names meet.
    ``is_source`` and ``is_source_folder`` say whether a file or folder is in a folder being sorted. Returns how
    many files and folders a rule placed."""
    ordered = _ordered(rules)
    placed = 0
    for s in plan.files:
        if s.percent >= 100 or not is_source(s.path):
            continue
        name = os.path.basename(s.path)
        labels = labels_of(s.path)
        rule = next((r for r in ordered if r.matches(name, labels, s.path) and is_valid(r.destination)), None)
        if rule is None:
            continue
        target = rule.destination_for(name, modified_of(s.path))
        if s.destination and os.path.normcase(s.destination) != os.path.normcase(target):
            s.runner_up = (s.destination, s.percent)
        s.destination, s.percent = target, 100
        s.new_folder = not os.path.isdir(target)
        s.reasons = [Reason(True, f"Your rule: {rule.describe(display)}")]
        placed += 1
    for f in plan.folders:                  # a folder kept whole follows a rule its name meets (not sorted inside)
        if f.percent >= 100 or f.outcome not in (KEEP_TOGETHER, FOLDER_REVIEW, STAYS) or not is_source_folder(f.path):
            continue
        name = os.path.basename(f.path)
        rule = next((r for r in ordered if r.matches(name, (), f.path) and is_valid(r.destination)), None)
        if rule is None or os.path.normcase(rule.destination) == os.path.normcase(os.path.dirname(f.path)):
            continue
        f.outcome, f.destination, f.percent = KEEP_TOGETHER, rule.destination, 100
        f.reasons = [Reason(True, f"Your rule: {rule.describe(display)}")]
        placed += 1
    return placed


def suggest_rule(examples: list[str], destination: str, others: list[tuple[str, str | None, int]],
                 rules: list[Rule], declined: set[str]) -> RuleSuggestion | None:
    """A rule covering the files users sent to ``destination`` (their names in ``examples``).

    ``others`` are the plan's other files from the folders being sorted: (path, destination, percent).
    """
    if len(examples) < MIN_EXAMPLES:
        return None
    known = {r.key for r in rules} | set(declined)
    word_counts = Counter(w for name in examples for w in set(words(stem_of(name))))
    exts = {os.path.splitext(n)[1].lower() for n in examples}
    candidates = []
    for word, count in word_counts.items():
        if count < MIN_EXAMPLES or count < 0.8 * len(examples) or len(word) < 3:
            continue
        options = [Rule(word, destination)]
        if len(exts) == 1 and next(iter(exts)):
            options.append(Rule(word, destination, next(iter(exts))))
        for rule in options:
            if rule.key in known:
                continue
            gain, harm = [], 0
            for path, current, percent in others:
                if not rule.matches(os.path.basename(path)):
                    continue
                if current and os.path.normcase(current) == os.path.normcase(destination):
                    continue
                if current and percent >= SURE_ELSEWHERE:
                    harm += 1
                else:
                    gain.append(path)
            if gain and not harm:
                covered = sum(1 for n in examples if rule.matches(n))
                candidates.append((covered, len(gain), not rule.ext, rule, gain))
    if not candidates:
        return None
    covered, _, _, rule, gain = max(candidates, key=lambda c: (c[0], c[1], c[2]))
    return RuleSuggestion(rule, covered, gain)


GENERIC = {"setup", "install", "installer", "window", "windows", "win", "portable", "release", "version", "final",
           "copy", "download", "update", "new", "old", "latest", "beta", "alpha", "main", "master", "file",
           "document", "draft", "scan", "image", "photo", "img", "dsc", "screenshot", "untitled", "readme", "note"}


def _name_parts(name: str) -> list[tuple[str, str]]:
    """Ways a rule can pick out a name, in the order they come in it: ("contains", text) for two words side by
    side ("tide log") or a run-together name ("harbormap", whole, so "harbor" alone isn't taken for it), and
    ("word", w) for a word. Common words such as "setup" or "windows" are left out."""
    found = []
    raws = re.findall(r"[A-Za-z]{2,}|\S", stem_of(name))
    for i, raw in enumerate(raws):
        parts = [p for p in words(raw) if len(p) >= 3] if len(raw) >= 3 else []
        if len(parts) > 1:
            found.append(("contains", raw))
        elif parts and parts[0] not in GENERIC:
            found.append(("word", parts[0]))
            after = raws[i + 1] if i + 1 < len(raws) else ""
            if after.isalpha() and len(after) >= 3 and words(after) and words(after)[0] not in GENERIC:
                found.append(("contains", f"{raw} {after}"))
    return list(dict.fromkeys(found))


TYPE_KINDS = ("video", "audio", "ebook")      # kinds a rule by type alone may be suggested for


def _type_parts(name: str) -> list[tuple[str, str]]:
    """("ext", ".avi") for a video, music or e-book file: rules by type are suggested only for those kinds."""
    ext = os.path.splitext(name)[1].lower()
    return [("ext", ext)] if ext and kind_of(ext) in TYPE_KINDS else []


def _candidate(how: str, text: str, destination: str) -> Rule:
    if how == "word":
        return Rule(text, destination)
    if how == "ext":
        return Rule("", destination, ext=text)
    if how == "kind":
        return Rule("", destination, kind=text)
    return Rule("", destination, contains=text)


def suggest_rules(examples: list[str], destination: str, others: list[tuple[str, str | None, int]],
                  rules: list[Rule], declined: set[str], elsewhere: list[str] = (), limit: int = 4
                  ) -> list[RuleSuggestion]:
    """Several rules for the files and folders users sent to ``destination`` (their names in ``examples``): one
    for each name part shared by two or more of them ("Tide Log" files, "Harbor Map" files), the part covering
    the most first; then, for videos, music and e-books, one for their type (".avi files", or "videos" when
    there are several endings), even from one file when it places others too. A rule never takes a name users
    sent to another folder (``elsewhere``) or a file SortZen is sure belongs elsewhere; one that places nothing
    more today is kept when three or more names share it. Names a rule already sends there are left out."""
    if not examples:
        return []
    known = {r.key for r in rules} | set(declined)
    here = [r for r in rules if os.path.normcase(r.destination) == os.path.normcase(destination)]
    left = [n for n in dict.fromkeys(examples) if not any(r.matches(n) for r in here)]   # a rule has them
    found: list[RuleSuggestion] = []
    tried: set[tuple[str, str]] = set()
    while left and len(found) < limit:
        best = None
        order, spelled = {}, {}                 # the first spelling met is kept ("HarborMap")
        for name in left:
            for at, (how, text) in enumerate(_name_parts(name) + _type_parts(name)):
                part = (how, text.lower())
                spelled.setdefault(part, text)
                order[part] = min(order.get(part, at), at)
        exts = {low for how, low in order if how == "ext"}
        kinds = {kind_of(e) for e in exts}
        for kind in kinds:                      # several endings of one kind: the kind as a whole
            if sum(1 for e in exts if kind_of(e) == kind) > 1:
                order[("kind", kind)], spelled[("kind", kind)] = len(order), kind
        for how, low in order:
            text = spelled[(how, low)]
            if (how, low) in tried:
                continue
            rule = _candidate(how, text, destination)
            by_type = how in ("ext", "kind")
            count = sum(1 for n in left if rule.matches(n))
            if count < (1 if by_type else MIN_EXAMPLES):
                continue
            if rule.key in known or any(rule.matches(n) for n in elsewhere):
                tried.add((how, low))
                continue
            gain, harm = [], 0
            for path, current, percent in others:
                if not rule.matches(os.path.basename(path)):
                    continue
                if current and os.path.normcase(current) == os.path.normcase(destination):
                    continue
                if current and percent >= SURE_ELSEWHERE:
                    harm += 1
                    break
                gain.append(path)
            if harm or (not gain and count < MIN_EXAMPLES + 1):
                tried.add((how, low))
                continue
            score = (not by_type, count, len(gain), how == "contains", how == "kind", -order[(how, low)],
                     len(text))
            if best is None or score > best[0]:
                best = (score, rule, gain)
        if best is None:
            break
        _, rule, gain = best
        covered = [n for n in left if rule.matches(n)]
        found.append(RuleSuggestion(rule, len(covered), gain))
        left = [n for n in left if n not in covered]
    return found


def _swap(path: str | None, old: str, new: str) -> str | None:
    if not path:
        return path
    p, o = os.path.normcase(path), os.path.normcase(old).rstrip(os.sep)
    if p == o:
        return new
    if p.startswith(o + os.sep):
        return new + path[len(o):]
    return path


def rename_planned(plan: Plan, names: dict[str, str]) -> None:
    """Folders SortZen plans to make, under the names users gave them."""
    for old, new in names.items():
        for s in plan.files:
            s.destination = _swap(s.destination, old, new)
            if s.runner_up:
                s.runner_up = (_swap(s.runner_up[0], old, new), s.runner_up[1])
        for f in plan.folders:
            f.destination = _swap(f.destination, old, new)
        for t in plan.topics:
            t.home = _swap(t.home, old, new)
        plan.new_folders = list(dict.fromkeys(_swap(f, old, new) for f in plan.new_folders))
