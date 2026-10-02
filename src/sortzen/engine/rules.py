"""Rules users make: "names with this word (and of this type) go to this folder". Never touches files.

- A rule places every matching file from the folders being sorted, at 100%, with the rule as
  its reason. Files users placed themselves keep their own choice.
- A rule is suggested when users send two or more files to the same folder and their names
  share a word: only when the rule would also place other files in the plan, never moves a
  file SortZen is already sure belongs elsewhere, and was not turned down before.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass

from .features import stem_of, words
from .plan import Plan, Reason

MIN_EXAMPLES = 2            # files sent to the same folder before a rule is suggested
SURE_ELSEWHERE = 90         # a suggestion this sure is never overruled by a suggested rule


def name_shape(name: str) -> str:
    """A name with its numbers as #: "IMG_2041.jpg" and "IMG_77.jpg" both give "img_#"."""
    stem = os.path.splitext(name)[0].lower()
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", stem)).strip()


@dataclass(frozen=True)
class Rule:
    word: str                   # a name word, as the engine reads it (lower case, singular); "" with a shape
    destination: str
    ext: str = ""               # ".pdf"; "" for any type
    shape: str = ""             # a name shape ("#", "img_#"); "" for a word rule
    example: str = ""           # a name it was made from, for describing it

    def matches(self, name: str) -> bool:
        if self.ext and os.path.splitext(name)[1].lower() != self.ext:
            return False
        if self.shape:
            return name_shape(name) == self.shape
        return self.word in words(stem_of(name))

    @property
    def key(self) -> str:
        return f"{self.word}|{self.ext}|{self.shape}|{os.path.normcase(os.path.abspath(self.destination))}"

    def describe(self, display=lambda p: p) -> str:
        kind = f" ({self.ext.lstrip('.').upper()} files)" if self.ext else ""
        if self.shape:
            what = "Names that are only numbers" if self.shape == "#" else f"Names like “{self.example or self.shape}”"
            return f"{what}{kind} go to {display(self.destination)}"
        return f"Names with “{self.word}”{kind} go to {display(self.destination)}"


@dataclass
class RuleSuggestion:
    rule: Rule
    examples: int               # files users sent there that the rule covers
    matches: list[str]          # other files in the plan the rule would place


def _ordered(rules: list[Rule]) -> list[Rule]:
    """The most specific rules first (a word and a type before a word alone); later rules before earlier."""
    return sorted(reversed(rules), key=lambda r: (not r.shape, not r.ext))


def apply_rules(plan: Plan, rules: list[Rule], is_valid, is_source, display=lambda p: p) -> int:
    """Place matching files by the rules. Returns how many files a rule placed."""
    ordered = _ordered(rules)
    placed = 0
    for s in plan.files:
        if s.percent >= 100 or not is_source(s.path):
            continue
        name = os.path.basename(s.path)
        rule = next((r for r in ordered if r.matches(name) and is_valid(r.destination)), None)
        if rule is None:
            continue
        if s.destination and os.path.normcase(s.destination) != os.path.normcase(rule.destination):
            s.runner_up = (s.destination, s.percent)
        s.destination, s.percent = rule.destination, 100
        s.new_folder = not os.path.isdir(rule.destination)
        s.reasons = [Reason(True, f"Your rule: {rule.describe(display)}")]
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
