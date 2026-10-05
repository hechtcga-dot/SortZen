"""An organizing session from start to end: the wizard's steps (Choose, Duplicates, Catalog) and the
Review tab, over the plan made for the session. Moves nothing: moving is AppService.move, after the
Move window.

Step 3 shows one batch of related files at a time, surest first. Each confirmed batch teaches
SortZen: the labels are guessed again, the remaining batches are formed again, and once SortZen's
guesses match users' choices often enough, the batches it is now sure of are settled by themselves.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ..engine.batches import Batch, catalog_batches, label_merge_suggestion
from ..engine.duplicates import KEEP_RULES, choose_kept
from ..engine.plan import KEEP_TOGETHER, STAYS, FolderSuggestion, Plan, Reason, Suggestion
from ..engine.rules import rename_planned
from ..repositories.file_index import path_key
from ..repositories.sessions import CATALOG, DUPLICATES, MOVED, REVIEW, Session
from . import plan_view

RULES_AT_ONCE = 3       # rules suggested at most in one go (at the start of Step 3, or after a change)
SETTLE = 85             # a batch this sure is settled by itself...
SETTLE_CHECKS = 20      # ...once SortZen's guesses were checked this many times...
SETTLE_AGREE = 0.9      # ...and matched users' choices this often


@dataclass
class Learned:
    """What SortZen learned from a confirmed batch, for the banner."""
    settled_batches: int = 0
    settled_files: int = 0
    merge: tuple[str, str] | None = None        # (label to merge, into this label)
    folder: object | None = None                # a LabelFolderSuggestion
    ideas: list = field(default_factory=list)   # RuleIdeas not offered yet in this session


@dataclass
class RuleIdea:
    rule: object                    # an engine Rule
    why: str
    places: int                     # files and folders of the plan it would place
    source: str = "SortZen"         # or "AI"
    example: str = ""               # the name of a file or folder just placed that it comes from


def _key(path: str) -> str:
    return path_key(path)


class Flow:
    def __init__(self, service, session: Session):
        self.service = service
        self.session = session
        self.plan: Plan | None = None
        self.batches: list[Batch] = []
        self._history: list[tuple[dict, dict]] = []
        self.offered: set[str] = set()          # rules already suggested while the session is open
        self._about: dict | None = None         # what users just did, for the next rule ideas
        self._opened = False                    # the first rule ideas of Step 3 were looked for

    def save(self) -> None:
        self.service.sessions.save(self.session)

    # ---------------------------------------------------------------- Step 1: Choose
    def use_folders(self) -> None:
        """The folders chosen in Step 1 belong to this session."""
        self.session.sources = self.service.source_folders()
        self.session.destinations = self.service.destination_folders()
        self.save()

    def restore_folders(self) -> list[str]:
        """Reopening a session puts its folders back. Returns the ones that can't be found."""
        if not self.session.sources:
            return []
        missing = [f["path"] for f in self.session.sources if not os.path.isdir(f["path"])] + \
                  [d for d in self.session.destinations if not os.path.isdir(d)]
        self.service.settings.data["sources"] = [dict(f) for f in self.session.sources if os.path.isdir(f["path"])]
        self.service.settings.data["destinations"] = [d for d in self.session.destinations if os.path.isdir(d)]
        self.service.settings.save()
        return missing

    def rename(self, name: str) -> None:
        name = " ".join((name or "").split())
        if name:
            self.session.name = name
            self.save()

    def set_plan(self, plan: Plan) -> None:
        self.plan = plan
        self.batches = []
        self._made = False
        self._vector_cache = {}

    # ---------------------------------------------------------------- Step 2: Duplicates
    def copies(self) -> list:
        return list(self.plan.copies) if self.plan is not None else []

    def keep_by(self, rule: str) -> None:
        if rule not in KEEP_RULES:
            raise ValueError(f"Unknown way of choosing the copy to keep: {rule}")
        choose_kept(self.copies(), rule)
        self.session.keep_rule = rule

    def ticked_copies(self) -> int:
        return sum(1 for g in self.copies() for c in g.extras if c.ticked)

    def copies_queued(self, result) -> None:
        """The extra copies are in "To delete": they leave the plan and Step 3."""
        moved = [old for old, _ in result.moves]
        self.session.copies_queued += result.moved
        if self.plan is not None and moved:
            gone = {_key(p) for p in moved}
            self.plan.files = [s for s in self.plan.files if _key(s.path) not in gone]
            self.plan.copies = []
            self.service.forget_files(moved)
        self.session.stage = CATALOG
        self.save()

    def skip_duplicates(self) -> None:
        self.session.stage = CATALOG
        self.save()

    # ---------------------------------------------------------------- Step 3: Catalog
    def _candidates(self) -> list:
        """The files from the folders being sorted that Step 3 hasn't finished with."""
        if self.plan is None:
            return []
        records = self.service._records
        finished = self.session.catalogued
        mine = {path_key(p) for p in self.service.users_labels()}
        found = []
        for s in self.plan.files:
            record = records.get(s.path)
            if record is None or record.role != "source" or s.topic or s.path in self.plan.companions \
                    or self.service.is_left_out(s.path):
                continue
            if _key(s.path) in finished or path_key(s.path) in mine:
                continue
            found.append(s)
        return found

    def make_batches(self) -> list[Batch]:
        """The batches still to label: new files surest first, then the files that come back later."""
        self.batches = self._form(self._batch_inputs())
        self._made = True
        if not self.session.batches_at_start:
            self.session.batches_at_start = len(self.batches)
            self.save()
        return self.batches

    def _vectors_for(self, candidates: list) -> dict:
        """How alike files are, worked out once for the files being sorted (they don't change in a session)."""
        cache = self.__dict__.setdefault("_vector_cache", {})
        missing = [s.path for s in candidates if s.path not in cache]
        if missing:
            cache.update(self.service._vectors(missing))
        return {s.path: cache[s.path] for s in candidates if s.path in cache}

    def _batch_inputs(self, guesses: dict | None = None) -> dict:
        """Everything forming the batches needs, taken at once (so it can be used away from the window)."""
        later = {_key(p) for p in self.session.later}
        candidates = self._candidates()
        mine, ai = self.service._label_index()
        return {"fresh": [s for s in candidates if _key(s.path) not in later],
                "again": [s for s in candidates if _key(s.path) in later],
                "apart": {_key(p) for p in self.session.apart},
                "vectors": self._vectors_for(candidates), "mine": mine, "ai": ai,
                "guesses": guesses if guesses is not None else dict(self.service._guesses),
                "display": self.service.display}

    @staticmethod
    def _labels_by_path(inputs: dict) -> dict[str, list[tuple[str, int]]]:
        found = {}
        for s in [*inputs["fresh"], *inputs["again"]]:
            key = path_key(s.path)
            if key in inputs["mine"]:
                found[s.path] = [(label, 100) for label in inputs["mine"][key]]
            elif inputs["ai"].get(key):
                found[s.path] = sorted(((a, int(b)) for a, b in inputs["ai"][key]), key=lambda x: -x[1])
            else:
                found[s.path] = [(label, percent) for label, percent, _ in inputs["guesses"].get(key, [])]
        return found

    @classmethod
    def _form(cls, inputs: dict) -> list[Batch]:
        guesses = cls._labels_by_path(inputs)
        display, apart, vectors = inputs["display"], inputs["apart"], inputs["vectors"]

        def batches(files):
            together = [s for s in files if _key(s.path) not in apart]
            alone = [catalog_batches([s], guesses, None, display)[0] for s in files if _key(s.path) in apart]
            for b in alone:
                b.title, b.why = os.path.basename(b.paths[0]), "Kept apart from the files it was shown with"
            found = catalog_batches(together, guesses, vectors, display) + alone
            return sorted([b for b in found if b.paths], key=lambda b: (-b.certainty, -len(b.paths), b.title.lower()))

        return batches(inputs["fresh"]) + batches(inputs["again"])

    def current(self) -> Batch | None:
        if not self.batches and not getattr(self, "_made", False):
            self.make_batches()
        return self.batches[0] if self.batches else None

    def files_left(self) -> int:
        return sum(len(b.paths) for b in self.batches)

    def is_later(self, batch: Batch) -> bool:
        later = {_key(p) for p in self.session.later}
        return bool(batch.paths) and all(_key(p) in later for p in batch.paths)

    # ---------------------------------------------------------------- answers (quick: no learning here)
    SNAPSHOT_KEYS = ("labels", "checks", "learned_since_plan")

    def _remember(self) -> None:
        lists = {k: list(getattr(self.session, k)) for k in ("done", "settled", "to_review", "later", "passed", "apart")}
        lists["settled_batches"] = self.session.settled_batches
        lists["answered"] = self.session.answered
        self.session.answered += 1
        settings = {k: json.loads(json.dumps(self.service.settings.data.get(k))) for k in self.SNAPSHOT_KEYS}
        self._history.append((lists, settings, self.service._guesses, list(self.batches)))

    def can_go_back(self) -> bool:
        return bool(self._history)

    def back(self) -> bool:
        """Undo the latest answer and show that batch again (at once: nothing is worked out again)."""
        if not self._history:
            return False
        lists, settings, guesses, batches = self._history.pop()
        for k, v in lists.items():
            setattr(self.session, k, v)
        for k, v in settings.items():
            if v is None:
                self.service.settings.data.pop(k, None)
            else:
                self.service.settings.data[k] = v
        self.service.settings.save()
        self.service._guesses = guesses
        self.batches = batches
        self.epoch += 1                     # learning that was under way belongs to the answer taken back
        self.save()
        return True

    epoch = 0

    def _come_back_later(self, paths: list[str]) -> list[str]:
        """Files skipped or left unticked come back at the end; skipped again, they go to Review as they are.
        Returns the files that come back."""
        later = {_key(p) for p in self.session.later}
        back = []
        for p in paths:
            if _key(p) in later:
                self.session.later = [x for x in self.session.later if _key(x) != _key(p)]
                self.session.passed.append(p)
            else:
                self.session.later.append(p)
                back.append(p)
        return back

    def _finished(self, paths: list[str], into: str) -> None:
        keys = {_key(p) for p in paths}
        self.session.later = [x for x in self.session.later if _key(x) not in keys]
        getattr(self.session, into).extend(paths)

    def _take_out(self, batch: Batch, coming_back: list[str] = (), alone: list[str] = ()) -> None:
        """The answered batch leaves the list; files that come back go to the end (alone ones one by one)."""
        self.batches = [b for b in self.batches if b is not batch]
        by_path = {s.path: s for s in self.plan.files} if self.plan else {}
        guesses = {p: [(label, percent) for label, percent, _ in self.service.label_guesses(p)]
                   for p in [*coming_back, *alone]}
        display = self.service.display
        rest = [by_path[p] for p in coming_back if p in by_path and p not in set(alone)]
        if rest:
            self.batches += catalog_batches(rest, guesses, None, display)
        for p in alone:
            if p in by_path:
                b = catalog_batches([by_path[p]], guesses, None, display)[0]
                b.title, b.why = os.path.basename(p), "Kept apart from the files it was shown with"
                self.batches.append(b)
        self.batches = [b for b in self.batches if b.paths]

    def confirm(self, batch: Batch, ticked: list[str], labels: list[str], learn: bool = True) -> Learned | None:
        """The ticked files get exactly these labels; unticked ones come back later. With ``learn``, SortZen
        learns at once; otherwise the window has it learn in the background (``learning_inputs``)."""
        self._remember()
        for name in labels:
            if name.lower() not in {x.lower() for x in self.service.labels()}:
                self.service.add_label(name)
        ticked_keys = {_key(p) for p in ticked}
        if ticked:
            self.service.set_file_labels(ticked, labels)
            self._finished(ticked, "done")
            self.note_change(ticked, labels)
        self._take_out(batch, self._come_back_later([p for p in batch.paths if _key(p) not in ticked_keys]))
        self.save()
        return self.learn_now() if learn else None

    def send_to_review(self, batch: Batch, ticked: list[str]) -> None:
        """The ticked files go to Review without labels."""
        self._remember()
        ticked_keys = {_key(p) for p in ticked}
        self._finished(ticked, "to_review")
        self._take_out(batch, self._come_back_later([p for p in batch.paths if _key(p) not in ticked_keys]))
        self.save()

    def keep_apart(self, batch: Batch, ticked: list[str]) -> None:
        """The ticked files don't belong with the others: they come back later, one by one."""
        self._remember()
        keys = {_key(p) for p in self.session.apart}
        self.session.apart += [p for p in ticked if _key(p) not in keys]
        ticked_keys = {_key(p) for p in ticked}
        alone = self._come_back_later(ticked)
        rest = self._come_back_later([p for p in batch.paths if _key(p) not in ticked_keys])
        self._take_out(batch, rest + alone, alone)
        self.save()

    def note_change(self, paths: list[str], labels=(), folder: str | None = None) -> None:
        """What users just did (files labelled, or files and folders sent to ``folder``): the next rule ideas
        are about these."""
        about = self._about or {"paths": [], "labels": [], "folder": None}
        about["paths"] = about["paths"] + [p for p in paths if p not in about["paths"]]
        about["labels"] = about["labels"] + [x for x in labels if x not in about["labels"]]
        about["folder"] = folder or about["folder"]
        self._about = about

    def take_change(self) -> dict | None:
        about, self._about = self._about, None
        return about

    def note_deleted(self, paths: list[str]) -> None:
        """Remember the names of files users deleted (for suggesting rules)."""
        self.session.deleted = (self.session.deleted + [os.path.basename(p) for p in paths])[-500:]
        self.save()

    def drop(self, paths: list[str]) -> None:
        """Files moved into "To delete" from Step 3 leave the session."""
        self.note_deleted(paths)
        gone = {_key(p) for p in paths}
        if self.plan is not None:
            self.plan.files = [s for s in self.plan.files if _key(s.path) not in gone]
            self.service.forget_files(paths)
        for b in self.batches:
            b.paths = [p for p in b.paths if _key(p) not in gone]
        self.batches = [b for b in self.batches if b.paths]

    def batch_number(self) -> tuple[int, int]:
        """(this batch's number, how many batches there are now)."""
        return self.session.answered + 1, self.session.answered + len(self.batches)

    def skip(self, batch: Batch) -> None:
        self._remember()
        self._take_out(batch, self._come_back_later(batch.paths))
        self.save()

    def learned_enough(self) -> bool:
        agreed, total = self.service.agreement()
        return total >= SETTLE_CHECKS and agreed >= SETTLE_AGREE * total

    # ---------------------------------------------------------------- learning (can run in the background)
    def learning_inputs(self) -> dict:
        """What learning needs, taken at once in the window, so ``learn`` can run in the background."""
        names = self.service.labels()
        mine, ai = self.service._label_index()
        known = dict(mine)
        for k, v in ai.items():
            known.setdefault(k, [a for a, b in v if b >= 50])
        inputs = self._batch_inputs()
        opening = not self._opened and self.plan is not None
        self._opened = self._opened or opening
        inputs.update(records=list(self.service._records.values()), names=names, known=known,
                      notes=dict(self.service.file_notes()), epoch=self.epoch,
                      answered=self.session.answered, about=self.take_change(), opening=opening)
        return inputs

    def learn(self, inputs: dict) -> dict:
        """Labels guessed again from everything users answered, the batches formed again with them, and a
        folder for a label to suggest. Reads only ``inputs`` and the plan; safe away from the window."""
        from ..engine.labeling import guess_labels

        guesses = {}
        if inputs["names"] and inputs["records"]:
            found = guess_labels(inputs["records"], inputs["names"], inputs["known"], inputs["notes"])
            guesses = {path_key(k): v for k, v in found.items()}
        inputs = dict(inputs, guesses=guesses)
        folder, ideas = None, []
        if self.plan is not None:
            folder = next(iter(self.service.label_folder_suggestions(self.plan, guesses)), None)
            try:                                # ideas about the answers just given, or a few to start with
                if inputs.get("about"):
                    ideas = self.rule_ideas(guesses, inputs["about"])
                elif inputs.get("opening"):
                    ideas = self.rule_ideas(guesses)
            except RuntimeError:                # the window changed a setting meanwhile: next time
                ideas = []
        return {"guesses": guesses, "batches": self._form(inputs), "folder": folder, "ideas": ideas,
                "epoch": inputs["epoch"], "answered": inputs["answered"]}

    def apply_learning(self, result: dict, keep: Batch | None = None) -> Learned | None:
        """Use what was learned; ``keep`` (the batch on screen) stays first, as it is. None when the
        learning belongs to an answer taken back since."""
        if result["epoch"] != self.epoch:
            return None
        self.service._guesses = result["guesses"]
        finished = self.session.catalogued
        shown = {_key(p) for p in keep.paths} if keep is not None else set()
        batches = []
        for b in result["batches"]:             # files answered since learning started leave
            b.paths = [p for p in b.paths if _key(p) not in finished and _key(p) not in shown]
            if b.paths:
                batches.append(b)
        later_now = {_key(p) for p in self.session.later}
        known = {_key(p) for b in batches for p in b.paths} | shown
        missing = [p for b in self.batches for p in b.paths if _key(p) not in known]   # came back since
        self.batches = batches
        if missing:
            self._take_out(Batch("", "", []), [p for p in missing if _key(p) in later_now])
        learned = Learned()
        if self.learned_enough():
            for b in [b for b in self.batches if not self.is_later(b) and b.labels and b.certainty >= SETTLE]:
                self._finished(b.paths, "settled")
                learned.settled_batches += 1
                learned.settled_files += len(b.paths)
            if learned.settled_batches:
                self.session.settled_batches += learned.settled_batches
                settled = {_key(p) for p in self.session.settled}
                self.batches = [b for b in self.batches if not all(_key(p) in settled for p in b.paths)]
        if keep is not None and keep.paths:
            self.batches.insert(0, keep)
        declined = set(self.service.settings.get("declined_merges") or [])
        merge = label_merge_suggestion(self.service.labels())
        if merge and f"{merge[0]}>{merge[1]}" not in declined:
            learned.merge = merge
        learned.folder = result["folder"]
        learned.ideas = self.new_ideas(result.get("ideas", []))[:RULES_AT_ONCE]
        self.save()
        return learned

    def learn_now(self) -> Learned:
        return self.apply_learning(self.learn(self.learning_inputs()))

    def merge_labels(self, drop: str, keep: str) -> None:
        self.service.merge_label(drop, keep)

    def decline_merge(self, drop: str, keep: str) -> None:
        declined = list(self.service.settings.get("declined_merges") or [])
        self.service.settings.set("declined_merges", declined + [f"{drop}>{keep}"])

    def finish_catalog(self) -> None:
        """Step 3 is done: the files still waiting go to Review as they are."""
        self.session.stage = REVIEW
        self.save()

    def agreement_text(self) -> str:
        agreed, total = self.service.agreement()
        return f"SortZen matched your choice in {agreed} of your last {total}" if total else ""

    # ---------------------------------------------------------------- Review
    def start_review(self, plan: Plan) -> None:
        """Review shows the whole plan at once; folders users moved before are moved again."""
        self.plan = plan
        self._placed = set()
        for folder, target in list(self.session.folder_moves.items()):
            if os.path.isdir(folder):
                self._plan_folder_move(folder, target)
            else:
                self.session.folder_moves.pop(folder)
        corrections = {path_key(p): d for p, d in self.service.corrections().items()}
        planned = {_key(s.path) for s in plan.files}
        for path, record in self.service._records.items():     # files in place users sent elsewhere
            target = corrections.get(path_key(path))
            if target and _key(path) not in planned and _key(target) != _key(os.path.dirname(path)):
                self._plan_placed_file(path, target).reasons = [Reason(True, "You chose this folder")]
        if self.session.stage != MOVED:
            self.session.stage = REVIEW
        self.save()

    def level(self) -> int:
        """At or above this, SortZen is sure enough that a file needs no check."""
        return 101 if self.service.ask_everything() else self.service.autonomy()

    def _sources_files(self) -> list:
        """The plan's files from the folders being sorted, and files already in place that users moved."""
        if self.plan is None:
            return []
        records = self.service._records
        return [s for s in self.plan.files
                if (records.get(s.path) is None or records[s.path].role == "source" or _key(s.path) in self._placed)
                and s.path not in self.plan.companions and not self.service.is_left_out(s.path)]

    _placed: set = frozenset()

    def _plan_placed_file(self, path: str, folder: str | None = None):
        """A file already in its folder joins the plan (to go somewhere else users chose)."""
        s = Suggestion(path, os.path.dirname(path), folder or os.path.dirname(path), 100)
        self.plan.files.append(s)
        self._placed = set(self._placed) | {_key(path)}
        return s

    def files_in_place(self) -> dict[str, list[str]]:
        """Files already in the folders files go to (and the folders being tidied), by folder key; files the plan
        moves away are left out."""
        files = self.plan.files if self.plan else []
        leaving = {_key(s.path) for s in files if s.destination and _key(s.destination) != _key(s.current_folder)}
        unplaced = {_key(s.path) for s in files if not s.destination}
        found: dict[str, list[str]] = {}
        for path in self.service._records:
            key = _key(path)
            if key in leaving or key in unplaced or self.service.is_left_out(path):
                continue
            found.setdefault(_key(os.path.dirname(path)), []).append(path)
        return found

    def review_files(self) -> list:
        """The files the plan moves, from the folders being sorted."""
        moving = list(self.moving_folders())
        return [s for s in self._sources_files()
                if s.destination and _key(s.destination) != _key(s.current_folder)
                and not any(_key(s.path).startswith(m + os.sep) for m in moving)]     # those go with their folder

    def unplaced_files(self) -> list:
        """Files SortZen has no folder for: they stay where they are unless users drag them somewhere."""
        return [s for s in self._sources_files() if not s.destination]

    def is_unsure(self, s) -> bool:
        return s.percent < self.level()

    def to_check(self) -> int:
        return sum(1 for s in self.review_files() if self.is_unsure(s)) + \
            sum(1 for f in self.moving_folders().values() if f.percent < self.level())

    def leave_here(self, paths: list[str]) -> dict:
        """These files stay where they are (SortZen remembers it). Returns what Undo needs."""
        by_folder: dict[str, list[str]] = {}
        for s in self.plan.files:
            if s.path in set(paths):
                by_folder.setdefault(s.current_folder, []).append(s.path)
        return {"moves": [self.move_file(group, folder) for folder, group in by_folder.items()]}

    def undo_leave_here(self, undo: dict) -> None:
        for before in reversed(undo["moves"]):
            self.undo_move_file(before)

    def move_file(self, paths: list[str], folder: str) -> dict:
        """Users dragged files to another folder in the plan; SortZen remembers it. Returns the choices before,
        for Undo."""
        paths = self.service.with_companions(self.plan, paths)
        keys = {_key(p) for p in paths}
        planned = {_key(s.path) for s in self.plan.files}
        for p in paths:                         # files already in place join the plan
            if _key(p) not in planned and p in self.service._records:
                self._plan_placed_file(p)
        guessed = {s.path: s.destination for s in self.plan.files if _key(s.path) in keys}
        previous = self.service.correct(paths, folder, guessed)
        before = {}
        for s in self.plan.files:
            if _key(s.path) in keys:
                before[s.path] = (s.destination, s.percent, s.new_folder, list(s.reasons))
                s.destination, s.percent, s.new_folder = folder, 100, not os.path.isdir(folder)
                s.reasons = [Reason(True, "You chose this folder")]
        return {"corrections": previous, "plan": before}

    def undo_move_file(self, before: dict) -> None:
        self.service.restore_corrections(before["corrections"])
        for s in self.plan.files:
            if s.path in before["plan"]:
                s.destination, s.percent, s.new_folder, s.reasons = before["plan"][s.path]

    def new_folder(self, parent: str, name: str) -> str:
        name = (name or "").strip().rstrip(". ")
        if not name:
            raise ValueError("Type a name for the folder.")
        bad = sorted(set(name) & set('\\/:*?"<>|'))
        if bad:
            raise ValueError(f"Folder names can't contain {' '.join(bad)}")
        folder = os.path.join(parent, name)
        if os.path.exists(folder) or _key(folder) in {_key(f) for f in self.planned_folders()}:
            raise ValueError(f"There is already a folder called “{name}” there.")
        self.session.new_folders.append(folder)
        self.save()
        return folder

    def planned_folders(self) -> list[str]:
        """Folders still to be made: users' new folders and the ones the plan makes."""
        found = {_key(f): f for f in self.session.new_folders if not os.path.isdir(f)}
        for s in self.plan.files if self.plan else []:
            if s.destination and not os.path.isdir(s.destination):
                found.setdefault(_key(s.destination), s.destination)
                parent = os.path.dirname(s.destination)
                while parent and not os.path.isdir(parent) and os.path.dirname(parent) != parent:
                    found.setdefault(_key(parent), parent)
                    parent = os.path.dirname(parent)
        for f in self.moving_folders().values() if self.plan else []:
            target = f.destination
            while target and not os.path.isdir(target) and os.path.dirname(target) != target:
                found.setdefault(_key(target), target)
                target = os.path.dirname(target)
        return sorted(found.values(), key=str.lower)

    def delete_folder(self, folder: str) -> dict:
        """Delete a folder still to be made: the files planned for it (and folders in it) go to the folder
        it was in. Returns what is needed for Undo. Folders that exist are deleted in Explorer."""
        if os.path.isdir(folder):
            raise ValueError("Only folders still to be made can be deleted here. This one exists: delete it in "
                             "Explorer once it's empty.")
        parent = os.path.dirname(folder)
        inside = [s.path for s in self.plan.files if s.destination and
                  (_key(s.destination) == _key(folder) or _key(s.destination).startswith(_key(folder) + os.sep))]
        undo = self.move_file(inside, parent) if inside else {"corrections": {}, "plan": {}}
        moving = [f.path for f in self.moving_folders().values()
                  if _key(f.destination) == _key(folder) or _key(f.destination).startswith(_key(folder) + os.sep)]
        undo["folders"] = self.move_folders(moving, parent) if moving else None
        undo["new_folders"] = list(self.session.new_folders)
        self.session.new_folders = [f for f in self.session.new_folders
                                    if _key(f) != _key(folder) and not _key(f).startswith(_key(folder) + os.sep)]
        self.save()
        return undo

    def undo_delete_folder(self, undo: dict) -> None:
        self.undo_move_file(undo)
        if undo.get("folders"):
            self.undo_move_folders(undo["folders"])
        self.session.new_folders = undo["new_folders"]
        self.save()

    def move_planned_folder(self, folder: str, parent: str) -> str:
        """A folder still to be made goes inside another folder; its planned files follow."""
        if os.path.isdir(folder):
            raise ValueError("Only folders still to be made can be moved here.")
        target = os.path.join(parent, os.path.basename(folder))
        if _key(target) == _key(folder) or _key(parent).startswith(_key(folder)):
            raise ValueError("A folder can't go inside itself.")
        if os.path.exists(target):
            raise ValueError(f"There is already a folder called “{os.path.basename(folder)}” there.")
        rename_planned(self.plan, {folder: target})
        self.service._remap_paths(folder, target)
        self.session.new_folders = [target + f[len(folder):] if _key(f).startswith(_key(folder)) else f
                                    for f in self.session.new_folders]
        self.save()
        return target

    # ---------------------------------------------------------------- folders moved in Review
    def _plan_folder_move(self, folder: str, target: str | None):
        """The plan moves a folder as it is into ``target`` (None: it stays where it is)."""
        f = next((x for x in self.plan.folders if _key(x.path) == _key(folder)), None)
        if f is None:
            f = FolderSuggestion(folder, KEEP_TOGETHER, 100, files=sum(
                1 for s in self.plan.files if _key(s.path).startswith(_key(folder) + os.sep)))
            self.plan.folders.append(f)
        before = (f.outcome, f.destination, f.percent, list(f.reasons))
        if target is None or _key(target) == _key(os.path.dirname(folder)):
            f.outcome, f.destination = STAYS, None
        else:
            f.outcome, f.destination = KEEP_TOGETHER, target
        f.percent, f.reasons = 100, [Reason(True, "You chose this folder")]
        return f, before

    def moving_folders(self) -> dict[str, object]:
        """Folders the plan moves as they are, by key: the FolderSuggestion."""
        return {_key(f.path): f for f in (self.plan.folders if self.plan else [])
                if f.outcome == KEEP_TOGETHER and f.destination and _key(f.destination) != _key(os.path.dirname(f.path))}

    def can_move_folder(self, folder: str, target: str) -> str:
        """Why a folder can't go into ``target`` ("" when it can)."""
        roots = {_key(r) for r in self.service.all_roots()}
        if _key(folder) in roots:
            return "The folders you added stay where they are."
        if _key(target) == _key(folder) or _key(target).startswith(_key(folder) + os.sep):
            return "A folder can't go inside itself."
        if not any(_key(target) == r or _key(target).startswith(r + os.sep) for r in roots):
            return "Folders can only go into the folders you added."
        if os.path.exists(os.path.join(target, os.path.basename(folder))) and \
                _key(os.path.dirname(folder)) != _key(target):
            return f"There is already something called “{os.path.basename(folder)}” there."
        return ""

    def move_folders(self, folders: list[str], target: str) -> dict:
        """Folders go, as they are, into another folder when users confirm the move. SortZen remembers the choice
        (for folders being sorted, as their answer). Returns what Undo needs. Raises ValueError when one can't."""
        from ..engine.overview import folder_key

        for folder in folders:
            why = self.can_move_folder(folder, target)
            if why:
                raise ValueError(why)
        undo = {"plan": [], "moves": dict(self.session.folder_moves), "answers": {}}
        sources = [f["path"] for f in self.service.source_folders()]
        for folder in folders:
            f, before = self._plan_folder_move(folder, target)
            undo["plan"].append((f, before))
            self.session.folder_moves[folder] = target
            if any(_key(folder).startswith(_key(s) + os.sep) for s in sources):
                key = folder_key(os.path.abspath(folder))
                undo["answers"][key] = self.service.answers().get(key)
                self.service.save_answers({key: target})
        self.save()
        return undo

    def undo_move_folders(self, undo: dict) -> None:
        for f, (outcome, destination, percent, reasons) in undo["plan"]:
            f.outcome, f.destination, f.percent, f.reasons = outcome, destination, percent, reasons
        self.session.folder_moves = undo["moves"]
        if undo["answers"]:
            self.service.save_answers(undo["answers"])
        self.save()

    def group_folders(self, folders: list[str], parent: str, name: str) -> tuple[str, dict]:
        """Too many folders: these go together into one new folder ``name`` in ``parent``. Returns the new
        folder and what Undo needs."""
        new = self.new_folder(parent, name)
        try:
            undo = self.move_folders(folders, new)
        except ValueError:
            self.session.new_folders.remove(new)
            self.save()
            raise
        undo["new_folder"] = new
        return new, undo

    def undo_group_folders(self, undo: dict) -> None:
        self.undo_move_folders(undo)
        if undo.get("new_folder") in self.session.new_folders:
            self.session.new_folders.remove(undo["new_folder"])
        self.save()

    def look_alike(self, folders: list[str]) -> list[list[str]]:
        """Folders among these that look like versions or copies of one thing ("Report", "Report (2)",
        "Report-1.2"), biggest group first."""
        from ..engine.overview import _family_key

        groups: dict[str, list[str]] = {}
        for f in folders:
            key = _family_key(os.path.basename(f))
            if len(key) >= 3:
                groups.setdefault(key, []).append(f)
        return sorted([g for g in groups.values() if len(g) >= 2], key=lambda g: -len(g))

    # ---------------------------------------------------------------- rules from what users did
    def _users_choices(self) -> dict[str, list[str]]:
        """Folder key -> names of the files and folders users sent there (in this session or before)."""
        found: dict[str, list[str]] = {}
        for path, folder in self.service.corrections().items():
            if folder and _key(folder) != _key(os.path.dirname(path)):
                found.setdefault(_key(folder), []).append(os.path.basename(path))
        for folder, target in self.session.folder_moves.items():
            found.setdefault(_key(target), []).append(os.path.basename(folder))
        return found

    def rule_ideas(self, guesses=None, about: dict | None = None) -> list:
        """Rules SortZen would make from what users did: a folder for a label, and the names (or, for videos,
        music and e-books, the type) in common among the files and folders users sent to one folder. With
        ``about`` (``note_change``), only the rules for what users just did: each names the file it comes from.
        Rules made or turned down before are left out."""
        from ..engine.rules import suggest_rules

        if self.plan is None:
            return []
        known = {r.key for r in self.service.rules()} | set(self.service.settings.get("declined_rules") or [])
        ideas, seen = [], set()
        display = self.service.display

        def add(rule, why, places, always=False):
            if rule.key not in known and rule.key not in seen and (places or always):
                seen.add(rule.key)
                ideas.append(RuleIdea(rule, why, places, "SortZen"))

        for s in self.service.label_folder_suggestions(self.plan, guesses):
            add(s.rule, s.why, s.files)
        corrected = {path_key(p) for p in self.service.corrections()} | {_key(f) for f in self.session.folder_moves}
        just = {_key(p) for p in (about or {}).get("paths", [])}

        def sure(destination, percent):          # a folder SortZen only plans to make never stands in the way
            return percent if destination and os.path.isdir(destination) else min(percent, 89)

        others = [(s.path, s.destination, sure(s.destination, s.percent)) for s in self._sources_files()
                  if path_key(s.path) not in corrected and path_key(s.path) not in just]
        others += [(f.path, f.destination, sure(f.destination, f.percent)) for f in self.plan.folders
                   if _key(f.path) not in corrected and _key(f.path) not in just]
        destinations = {_key(d): d for d in [*self.service.corrections().values(), *self.session.folder_moves.values()]
                        if d}
        choices = self._users_choices()
        rules = self.service.rules()
        for key, names in choices.items():
            elsewhere = [n for k, more in choices.items() if k != key for n in more]
            for found in suggest_rules(names, destinations.get(key, key), others, rules, known | seen, elsewhere):
                add(found.rule, f"You sent {found.examples} like this there", len(found.matches), always=True)
        if about and not about.get("folder"):    # files just labelled: where the plan sends them
            groups: dict[str, list[str]] = {}
            for path in about["paths"]:
                s = self.plan.for_path(path)
                if s is not None and s.destination and _key(s.destination) != _key(os.path.dirname(path)):
                    groups.setdefault(s.destination, []).append(os.path.basename(path))
            for folder, names in groups.items():
                elsewhere = [n for f, more in groups.items() if f != folder for n in more]
                for found in suggest_rules(names, folder, others, rules, known | seen, elsewhere):
                    add(found.rule, "plan", len(found.matches), always=True)
        ideas.sort(key=lambda i: -i.places)
        if about is None:
            return ideas
        return [i for i in (self._about_idea(i, about, display) for i in ideas) if i is not None]

    def _about_idea(self, idea: RuleIdea, about: dict, display) -> RuleIdea | None:
        """The idea told in terms of what users just did, or None when it isn't about that."""
        labels = set(about.get("labels") or [])
        if about.get("folder") and _key(idea.rule.destination) != _key(about["folder"]):
            return None                         # never a rule sending them somewhere else
        for path in about.get("paths") or []:
            name = os.path.basename(path)
            if not idea.rule.matches(name, set(self.service.labels_of(path)) | labels, path):
                continue
            idea.example = name
            if about.get("folder"):
                idea.why = f"You moved “{name}” to {display(about['folder'])}"
            elif idea.rule.label:
                idea.why = f"You labelled “{name}” “{idea.rule.label}”; {idea.why}"
            else:
                idea.why = (f"The plan sends “{name}” to {display(idea.rule.destination)}" if idea.why == "plan"
                            else idea.why)
            return idea
        return None

    def new_ideas(self, ideas: list) -> list:
        """The ideas not suggested yet while the session is open, nor made or turned down since."""
        known = {r.key for r in self.service.rules()} | set(self.service.settings.get("declined_rules") or [])
        return [i for i in ideas if i.rule.key not in self.offered and i.rule.key not in known]

    def session_summary(self) -> dict:
        """What users did, for the AI: names only (long numbers removed), folders as shown."""
        from ..ai import privacy

        display = self.service.display
        choices = [(privacy.scrub_name(os.path.basename(p)), display(d)) for p, d in self.service.corrections().items()
                   if d and _key(d) != _key(os.path.dirname(p))]
        choices += [(privacy.scrub_name(os.path.basename(f)), display(t)) for f, t in self.session.folder_moves.items()]
        labels = []
        if self.plan is not None:
            by_folder: dict[str, list[str]] = {}
            for s in self.plan.files:
                if s.destination:
                    by_folder.setdefault(s.destination, []).extend(self.service.labels_of(s.path))
            for folder, found in by_folder.items():
                common = [x for x in dict.fromkeys(found) if found.count(x) >= max(2, len(found) // 2)]
                if common:
                    labels.append((display(folder), common))
        return {"choices": choices, "new_folders": [display(f) for f in self.planned_folders()],
                "deleted": [privacy.scrub_name(n) for n in self.session.deleted],
                "labels": labels, "folders": [display(f) for f in self.service.destination_choices(self.plan)],
                "rules": [self.service.describe_rule(r) for r in self.service.rules()]}

    def ai_rule_estimate(self) -> dict:
        from ..ai import rule_advisor
        from ..ai.services import SERVICES

        service = SERVICES[self.service.ai_service()]
        return {"service": service.name, "local": service.key == "ollama",
                "cost": rule_advisor.estimate(service.key, self.session_summary()), "files": 0}

    def ai_rule_ideas(self, emit=None, token=None, provider=None) -> tuple[list, list]:
        """The AI's rule suggestions for what users did, and the existing rules it doubts: (ideas, [(rule, why)])."""
        from ..ai import rule_advisor
        from ..ai.costs import cost
        from ..ai.errors import AIProblem, explain
        from ..ai.services import SERVICES
        from ..tasks import Status

        service = SERVICES[self.service.ai_service()]
        summary = self.session_summary()
        if emit:
            emit(Status(f"Asking {service.name} for rules", f"{len(summary['choices']):,} choices"))
        try:
            reply = (provider or self.service.provider()).generate_json(self.service.model(),
                                                                        [rule_advisor.request(summary)])
        except Exception as exc:
            raise AIProblem(explain(exc, service.name, self.service.model())) from exc
        self.service._add_spent(cost(service.key, reply.usage.input_tokens, reply.usage.output_tokens))
        found, doubts = rule_advisor.parse(reply.text)
        known = {r.key for r in self.service.rules()} | set(self.service.settings.get("declined_rules") or [])
        labels = {x.lower(): x for x in self.service.labels()}
        ideas = []
        for item in found:
            folder = self.service.resolve_folder(item["folder"], self.plan)
            try:
                rule = self.service.build_rule(folder or "", label=labels.get(item["label"].lower(), ""),
                                               text=item["contains"], kind=item["kind"], ext=item["ending"],
                                               by=item["by"], name=item["name"])
            except ValueError:
                continue
            if rule.key not in known and (not item["label"] or rule.label):
                ideas.append(RuleIdea(rule, item["why"], len(self.service.rule_matches(rule, self.plan)), "AI"))
        rules = self.service.rules()
        return ideas, [(rules[n - 1], why) for n, why in doubts if 0 < n <= len(rules)]

    def rules_for(self, folder: str) -> list:
        return [r for r in self.service.rules() if _key(r.destination) == _key(folder)]

    def move_rows(self) -> list:
        """What the Move window moves: every file the plan moves from the folders being sorted (with the files
        that go with them) and every folder that moves as it is."""
        if self.plan is None:
            return []
        wanted = {_key(s.path) for s in self.review_files()}
        wanted |= {_key(c) for c, main in self.plan.companions.items() if _key(main) in wanted}
        wanted |= set(self.moving_folders())
        found = []
        for group in plan_view.rows(self.plan, 0).values():
            found += [r for r in group if r.moves and _key(r.path) in wanted]
        return found

    def moved(self, result) -> None:
        self.session.moved += result.moved
        self.session.stage = MOVED
        self.save()

    # ---------------------------------------------------------------- the start screen
    def status(self) -> str:
        return describe(self.session)


def describe(session: Session) -> str:
    """Where a session is, for the start screen: "Step 3 Catalog · 218 files done", "Review: ready to move"."""
    if session.stage == MOVED:
        return f"Moved · {session.moved:,} files · open it to look or change more"
    if session.stage == REVIEW:
        return "Review: ready to move"
    if session.stage == CATALOG:
        done = len(session.done) + len(session.settled) + len(session.to_review)
        return f"Step 3 Catalog · {done:,} files done"
    if session.stage == DUPLICATES:
        return "Step 2 Duplicates"
    return "Step 1 Choose"
