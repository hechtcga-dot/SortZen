"""File-by-file suggestions: each file goes to the folder whose files it most resembles.

Every folder that may receive files has a profile: the files already in it. For each file
to sort, SortZen finds the most similar files among those (by the clues in features.py),
scores each folder from its closest few files, adds a little when the folder's own name
matches the file, and lowers folders whose year clashes with the file's. The percentage
is how clearly the best folder beats the others, reduced when even the best match is
weak. The reasons shown with each suggestion come from the same numbers.
"""
from __future__ import annotations

import os
from collections import defaultdict
from functools import lru_cache
from dataclasses import dataclass

from ..repositories.file_index import path_key
from ..scanning.file_types import GOOGLE_LINKS
from ..scanning.records import FileRecord
from .features import Clues, clues_for, finish_vectors, rarity, words, years
from .plan import FOLDER_REVIEW, KEEP_TOGETHER, STAYS, Plan, Reason, Suggestion

SORT_OUT = "sort into other folders"
TIDY = "tidy this folder"

NEIGHBOURS = 30             # most similar sorted files considered for each file
TOP_PER_FOLDER = (1.0, 0.6, 0.4)    # weights of a folder's three closest files
SHARPNESS = 3.0             # how strongly the best folder's lead turns into sureness
CLEAR_MATCH = 0.35          # a closest file at least this similar gives full sureness
NAME_BONUS = 0.12           # per matching rare word in the folder's own name
YEAR_CLASH = 0.4            # score kept when the folder's year differs from the file's
MAX_PERCENT = 99            # 100% is kept for rules users approved
TYPE_ONLY_PERCENT = 50      # most sureness when only the file type matches
STAY_BONUS = 0.2            # an organised folder's hold on its own files
LONE_FILE_PERCENT = 80      # a file alone in its organised folder stays
ONE_MATCH_PERCENT = 75      # most sureness when the only similar file in a larger folder looks out of place
MISPLACED_PERCENT = 90      # a sorted file this sure to belong elsewhere counts less as an example
MISPLACED_WEIGHT = 0.25
MOVE_OUT_PERCENT = 50       # below this, a file in an organised folder is shown as staying
KIND_LABELS = {"word": "Word document", "pdf": "PDF", "spreadsheet": "Spreadsheet", "presentation": "Presentation",
               "form": "Form", "text": "Text file", "image": "Picture", "video": "Video", "audio": "Music file",
               "archive": "Zip file", "installer": "Program installer", "shortcut": "Shortcut", "web page": "Web page"}


@dataclass(frozen=True)
class Source:
    root: str
    mode: str = SORT_OUT


@lru_cache(maxsize=500_000)
def _inside(path: str, folder: str) -> bool:
    key, root = path_key(path), path_key(folder)
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


class _Index:
    """Finds the most similar sorted files to a file.

    Files are first found through their distinctive clues (words and details that few files
    share); the full similarity is then worked out for those files only. Clues that most
    files share, such as "it's a PDF", decide nothing on their own and are not searched on,
    unless a file has nothing more distinctive.
    """

    COMMON_SHARE = 0.01         # a clue in more than this share of files is not searched on
    MIN_FOUND = 30
    MOST_FOUND = 200

    def __init__(self, vectors: list[dict[str, float]]):
        self.vectors = vectors
        self.postings: dict[str, list[int]] = defaultdict(list)
        for pos, vector in enumerate(vectors):
            for key in vector:
                self.postings[key].append(pos)
        self.common = max(50, int(self.COMMON_SHARE * len(vectors)))

    def search(self, vector: dict[str, float], exclude: int | None = None) -> list[tuple[int, float]]:
        shared: dict[int, float] = defaultdict(float)
        for key, value in vector.items():
            posting = self.postings.get(key, ())
            if len(posting) <= self.common:
                for pos in posting:
                    shared[pos] += value
        shared.pop(exclude, None)
        if len(shared) < self.MIN_FOUND:     # nothing distinctive: the most specific clues first
            found = set(shared)
            for key in sorted(vector, key=lambda k: len(self.postings.get(k, ()))):
                for pos in self.postings.get(key, ()):
                    if pos != exclude:
                        found.add(pos)
                    if len(found) >= self.MOST_FOUND:
                        break
                if len(found) >= self.MOST_FOUND:
                    break
        else:       # the files sharing the most distinctive weight are worked out in full
            found = sorted(shared, key=shared.__getitem__, reverse=True)[:self.MOST_FOUND]
        scores = []
        for pos in found:
            other = self.vectors[pos]
            sim = sum(value * other[key] for key, value in vector.items() if key in other)
            if sim > 0:
                scores.append((pos, sim))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:NEIGHBOURS]


class Planner:
    def __init__(self, records: list[FileRecord], sources: list[Source], destinations: list[str],
                 not_destinations: list[str] = (), answers: dict[str, int] | None = None,
                 corrections: dict[str, str] | None = None, left_out: list[str] = ()):
        self.records = list(records)
        self.sources = [Source(os.path.abspath(s.root), s.mode) for s in sources]
        self.destinations = [os.path.abspath(d) for d in destinations]
        self.not_destinations = [os.path.abspath(d) for d in not_destinations]   # never used as destinations
        self.answers = dict(answers or {})                       # question key -> chosen choice
        self.corrections = {path_key(k): os.path.abspath(v) for k, v in (corrections or {}).items()}
        self.excluded: list[str] = []                            # messy, undecided or moving folders
        self.left_out = [os.path.abspath(p) for p in left_out]  # left in place, still learned from
        self._sources: dict[str, Source | None] = {}
        self._labels: dict[str, str] = {}

    # ---------------------------------------------------------------- set-up
    def _source_of(self, path: str) -> Source | None:
        folder = os.path.dirname(path)
        if folder not in self._sources:
            self._sources[folder] = next((s for s in self.sources if _inside(folder, s.root)), None)
        source = self._sources[folder]
        if source is None and path_key(path) in {path_key(s.root) for s in self.sources}:
            return next(s for s in self.sources if path_key(s.root) == path_key(path))
        return source

    def _root_of(self, folder: str) -> str:
        for root in [s.root for s in self.sources] + self.destinations:
            if _inside(folder, root):
                return root
        return folder

    def is_left_out(self, path: str) -> bool:
        return any(_inside(path, p) for p in self.left_out)

    def _is_candidate(self, folder: str) -> bool:
        if any(_inside(folder, d) for d in self.not_destinations + self.excluded):
            return False
        if self.is_left_out(folder):
            return True             # a profile to learn from; files are never sent there
        if any(_inside(folder, d) for d in self.destinations):
            return True
        source = self._source_of(folder)
        return bool(source and source.mode == TIDY and path_key(folder) != path_key(source.root))

    def label(self, folder: str) -> str:
        if folder not in self._labels:
            self._labels[folder] = os.path.relpath(folder, os.path.dirname(self._root_of(folder))).replace(os.sep, "/")
        return self._labels[folder]

    # ---------------------------------------------------------------- the plan
    def plan(self) -> Plan:
        from . import overview

        self.clues: list[Clues] = [clues_for(r) for r in self.records]
        self.idf = rarity(self.clues)
        finish_vectors(self.clues, self.idf)
        self.folder = [os.path.dirname(r.path) for r in self.records]
        self.home = [self.corrections.get(path_key(r.path), f) for r, f in zip(self.records, self.folder)]
        self._prepare()
        plan = Plan(folders=overview.decide_folders(self))
        joining = overview.gather_families(self, plan)
        self.excluded = [f.path for f in plan.folders if f.outcome != STAYS]
        self.held = [f.path for f in plan.folders if f.outcome in (KEEP_TOGETHER, FOLDER_REVIEW)] + sorted(self.units)
        self._prepare()
        overview.place_kept_folders(self, plan)
        for i, record in enumerate(self.records):
            if (self._source_of(record.path) and not any(_inside(record.path, h) for h in self.held)
                    and not self.is_left_out(record.path)):
                if record.path in joining and path_key(record.path) not in self.corrections:
                    home, reasons = joining[record.path]
                    plan.files.append(Suggestion(record.path, self.folder[i], home, overview.FAMILY_PERCENT,
                                                 reasons, new_folder=not os.path.isdir(home)))
                else:
                    plan.files.append(self._suggest(i))
        overview.find_topics(self, plan)
        overview.ask_about_folders(self, plan)
        overview.apply_answers(self, plan)
        plan.files.sort(key=lambda s: s.path.lower())
        plan.folders.sort(key=lambda f: f.path.lower())
        plan.new_folders = sorted({s.destination for s in plan.files if s.new_folder}
                                  | {t.home for t in plan.topics if t.new_folder}
                                  | {f for f in plan.new_folders if not os.path.isdir(f)})
        return plan

    def _prepare(self) -> None:
        """Folder profiles: the files in each folder that may receive files."""
        candidate = {f: self._is_candidate(f) for f in set(self.home)}
        self.examples = [i for i, f in enumerate(self.home) if candidate[f]]
        self.example_pos = {i: pos for pos, i in enumerate(self.examples)}
        self.by_folder: dict[str, list[int]] = defaultdict(list)
        for i in self.examples:
            self.by_folder[self.home[i]].append(i)
        self.index = _Index([self.clues[i].vector for i in self.examples])
        self.folders_named: dict[str, list[str]] = defaultdict(list)
        for folder in self.by_folder:
            for w in set(words(os.path.basename(folder))):
                self.folders_named[w].append(folder)
        # First pass: sorted files that look misplaced count less as examples for their folder.
        self.weight = {i: 1.0 for i in self.examples}
        self.out_of_place: set[int] = set()
        first = {i: self._suggest(i) for i in self.examples
                 if path_key(self.records[i].path) not in self.corrections}
        for i, suggestion in first.items():
            if suggestion.destination not in (None, self.home[i]) and suggestion.percent >= 50:
                self.out_of_place.add(i)
                if suggestion.percent >= MISPLACED_PERCENT:
                    self.weight[i] = MISPLACED_WEIGHT

    def _suggest(self, i: int, outside: str | None = None) -> Suggestion:
        """Where file i belongs. With ``outside``, that folder and its files are left out of the comparison."""
        record, clues = self.records[i], self.clues[i]
        current = self.folder[i]
        corrected = self.corrections.get(path_key(record.path))
        if corrected and outside is None:
            return Suggestion(record.path, current, corrected, 100, [Reason(True, "You chose this folder")],
                              new_folder=not os.path.isdir(corrected))
        if clues.default_name and clues.no_contents:
            return Suggestion(record.path, current, None, 0, [Reason(False, "Default name and no readable contents")],
                              note="looks empty")
        source = self._source_of(record.path)
        tidy_home = bool(outside is None and source and source.mode == TIDY and current in self.by_folder)
        if tidy_home and self.by_folder[current] == [i]:
            return Suggestion(record.path, current, current, LONE_FILE_PERCENT,
                              [Reason(True, "The only file in its folder")])
        neighbours = self.index.search(clues.vector, exclude=self.example_pos.get(i))
        sims: dict[str, list[tuple[float, int]]] = defaultdict(list)
        for pos, sim in neighbours:
            j = self.examples[pos]
            if outside is None or not _inside(self.home[j], outside):
                sims[self.home[j]].append((sim * self.weight.get(j, 1.0), j))
        scores = {f: sum(w * s for w, (s, _) in zip(TOP_PER_FOLDER, sorted(v, reverse=True))) for f, v in sims.items()}
        name_matches = {f: m for f, m in self._name_matches(clues).items()
                        if outside is None or not _inside(f, outside)}
        for folder, matched in name_matches.items():
            scores[folder] = scores.get(folder, 0.0) + NAME_BONUS * min(2.0, sum(min(1.0, self.idf[f"w:{w}"] / 4)
                                                                              for w in matched))
        if tidy_home:
            scores[current] = scores.get(current, 0.0) + STAY_BONUS
        clashes = {}
        for folder in list(scores):
            folder_years = years(os.path.basename(folder))
            if folder_years and clues.name_years and not folder_years & clues.name_years:
                scores[folder] *= YEAR_CLASH
                clashes[folder] = (sorted(folder_years)[0], sorted(clues.name_years)[0])
        if record.ext in GOOGLE_LINKS:
            scores = {f: s for f, s in scores.items() if source and _inside(f, source.root)}
        ranked = sorted(((f, s) for f, s in scores.items() if s > 0), key=lambda kv: -kv[1])[:5]
        if not ranked:
            reason = "Google link files only move within their own drive" if record.ext in GOOGLE_LINKS \
                else "No sorted files are like this one"
            return Suggestion(record.path, current, None, 0, [Reason(False, reason)])

        if self.is_left_out(ranked[0][0]) and not self.is_left_out(current):
            others = [(f, sc) for f, sc in ranked if not self.is_left_out(f)]
            return Suggestion(record.path, current, None, 0,
                              [Reason(False, f"Most like the files in {self.label(ranked[0][0])}, which is left out")],
                              runner_up=(others[0][0], 0) if others else None)
        total = sum(s ** SHARPNESS for _, s in ranked)
        best, best_score = ranked[0]
        closest = max((s for s, _ in sims.get(best, [])), default=0.0)
        coverage = min(1.0, closest / CLEAR_MATCH)
        percent = min(MAX_PERCENT, round(100 * best_score ** SHARPNESS / total * coverage))
        type_only = not self._shared_clues(clues, [j for _, j in sims.get(best, [])[:3]]) and best not in name_matches
        if type_only:
            percent = min(percent, TYPE_ONLY_PERCENT)
        close = sorted(((sim, j) for sim, j in sims.get(best, []) if j != i), reverse=True)
        others_there = len([j for j in self.by_folder.get(best, []) if j != i])
        one_match = (others_there >= 3 and close and (len(close) < 2 or close[1][0] < 0.5 * close[0][0])
                     and close[0][1] in getattr(self, "out_of_place", ()))
        if one_match:
            percent = min(percent, ONE_MATCH_PERCENT)
        runner_up = None
        if len(ranked) > 1:
            second, second_score = ranked[1]
            runner_up = (second, round(100 * second_score ** SHARPNESS / total * coverage))
        reasons = self._reasons(i, best, sims.get(best, []), name_matches.get(best), clashes.get(best), coverage,
                                runner_up)
        if type_only:
            reasons.append(Reason(False, "Only the file type matches"))
        elif one_match:
            reasons.append(Reason(False, f"Only one similar file there, among {others_there}"))
        if tidy_home and best != current and percent < MOVE_OUT_PERCENT:
            stay = round(100 * scores.get(current, 0.0) ** SHARPNESS / total * coverage)
            return Suggestion(record.path, current, current, stay,
                              [Reason(True, "Fits the folder it is already in"),
                               Reason(False, f"Might belong in {self.label(best)} ({percent}%)")])
        suggestion = Suggestion(record.path, current, best, percent, reasons, runner_up)
        if best in clashes and outside is None:
            new = os.path.join(os.path.dirname(best),
                               os.path.basename(best).replace(clashes[best][0], clashes[best][1]))
            if not os.path.isdir(new) and new not in self.by_folder:
                suggestion.destination, suggestion.new_folder = new, True
                suggestion.reasons.insert(0, Reason(True, f"New folder “{os.path.basename(new)}” next to "
                                                          f"“{os.path.basename(best)}”"))
        return suggestion

    def _name_matches(self, clues: Clues) -> dict[str, list[str]]:
        """Folders whose own name shares a rare word with the file's name or contents."""
        matches: dict[str, list[str]] = defaultdict(list)
        for w in set(clues.name_words) | set(clues.content_words):
            if self.idf.get(f"w:{w}", 0) > 2:
                for folder in self.folders_named.get(w, ()):
                    matches[folder].append(w)
        return {f: sorted(m) for f, m in matches.items()}

    # ---------------------------------------------------------------- reasons
    def _reasons(self, i, best, close, name_match, clash, coverage, runner_up) -> list[Reason]:
        clues, record = self.clues[i], self.records[i]
        reasons: list[Reason] = []
        if best == self.folder[i]:
            reasons.append(Reason(True, "Fits the folder it is already in"))
        close = sorted(close, reverse=True)
        if best == self.folder[i]:
            close = [(sim, j) for sim, j in close if j not in getattr(self, "out_of_place", ())]
        if close:
            j = close[0][1]
            more = len(close) - 1
            extra = f" and {more} more" if more else ""
            reasons.append(Reason(True, f"Like “{self.records[j].name}”{extra} in {self.label(best)}"))
            shared = self._shared_words(clues, [j for _, j in close[:3]])
            in_name = [w for w in shared if w in clues.name_words][:3]
            in_text = [w for w in shared if w not in clues.name_words][:3]
            if in_name:
                reasons.append(Reason(True, "Name shares " + ", ".join(f"“{w}”" for w in in_name)))
            if in_text:
                reasons.append(Reason(True, "Mentions " + ", ".join(f"“{w}”" for w in in_text)))
        if name_match:
            reasons.append(Reason(True, f"Folder name “{os.path.basename(best)}” matches "
                                        + ", ".join(f"“{w}”" for w in name_match)))
        there = self.by_folder.get(best, [])
        same_kind = sum(1 for j in there if self.records[j].kind == record.kind and j != i)
        others = len([j for j in there if j != i])
        if others and same_kind:
            label = KIND_LABELS.get(record.kind, record.kind.capitalize())
            reasons.append(Reason(True, f"{label}, like {same_kind} of {others} files there"))
        if clash:
            reasons.append(Reason(False, f"Folder is for {clash[0]}; this file is from {clash[1]}"))
        if coverage < 1.0:
            reasons.append(Reason(False, "No close match among sorted files"))
        if runner_up:
            reasons.append(Reason(False, f"Runner-up: {self.label(runner_up[0])} ({runner_up[1]}%)"))
        return reasons

    def _shared_clues(self, clues: Clues, others: list[int]) -> bool:
        """Whether the file shares a word, prefix or detail (not just its type) with any of these files."""
        mine = {k for k in clues.vector if k[0] in "wpx"}
        return any(mine & self.clues[j].vector.keys() for j in others)

    def _shared_words(self, clues: Clues, others: list[int]) -> list[str]:
        totals: dict[str, float] = defaultdict(float)
        for j in others:
            vector = self.clues[j].vector
            for key, value in clues.vector.items():
                if key.startswith("w:") and key in vector:
                    totals[key[2:]] += value * vector[key]
        return [w for w, _ in sorted(totals.items(), key=lambda kv: -kv[1])]
