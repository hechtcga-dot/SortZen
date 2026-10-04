"""An organizing session from start to end: the wizard's steps (Choose, Duplicates, Catalog) and the
Review tab, over the plan made for the session. Moves nothing: moving is AppService.move, after the
Move window.

Step 3 shows one batch of related files at a time, surest first. Each confirmed batch teaches
SortZen: the labels are guessed again, the remaining batches are formed again, and once SortZen's
guesses match users' choices often enough, the batches it is now sure of are settled by themselves.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..engine.batches import Batch, catalog_batches, label_merge_suggestion, review_batches
from ..engine.duplicates import KEEP_RULES, choose_kept
from ..engine.plan import KEEP_TOGETHER, Plan, Reason
from ..engine.rules import rename_planned
from ..repositories.file_index import path_key
from ..repositories.sessions import CATALOG, DUPLICATES, MOVED, REVIEW, Session
from . import plan_view

SETTLE = 85             # a batch this sure is settled by itself...
SETTLE_CHECKS = 20      # ...once SortZen's guesses were checked this many times...
SETTLE_AGREE = 0.9      # ...and matched users' choices this often
FOLDERS_KEY = "folders kept together"


@dataclass
class Learned:
    """What SortZen learned from a confirmed batch, for the banner."""
    settled_batches: int = 0
    settled_files: int = 0
    merge: tuple[str, str] | None = None        # (label to merge, into this label)
    folder: object | None = None                # a LabelFolderSuggestion


@dataclass
class ReviewBatch:
    batch: Batch
    sure: bool = False              # every file at or above the autonomy level: confirmed without a check
    folders: list[str] = field(default_factory=list)      # kept-together folders in this batch


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class Flow:
    def __init__(self, service, session: Session):
        self.service = service
        self.session = session
        self.plan: Plan | None = None
        self.batches: list[Batch] = []
        self._history: list[tuple[dict, dict]] = []
        self.review: list[ReviewBatch] = []

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
        later = {_key(p) for p in self.session.later}
        candidates = self._candidates()
        fresh = [s for s in candidates if _key(s.path) not in later]
        again = [s for s in candidates if _key(s.path) in later]
        vectors = self.service._vectors([s.path for s in candidates])
        guesses = {s.path: [(label, percent) for label, percent, _ in self.service.label_guesses(s.path)]
                   for s in candidates}
        display = self.service.display
        apart = {_key(p) for p in self.session.apart}

        def batches(files):
            together = [s for s in files if _key(s.path) not in apart]
            alone = [catalog_batches([s], guesses, None, display)[0] for s in files if _key(s.path) in apart]
            for b in alone:
                b.title, b.why = os.path.basename(b.paths[0]), "Kept apart from the files it was shown with"
            found = catalog_batches(together, guesses, vectors, display) + alone
            return sorted([b for b in found if b.paths], key=lambda b: (-b.certainty, -len(b.paths), b.title.lower()))

        self.batches = batches(fresh) + batches(again)
        if not self.session.batches_at_start:
            self.session.batches_at_start = len(self.batches)
            self.save()
        return self.batches

    def current(self) -> Batch | None:
        if not self.batches:
            self.make_batches()
        return self.batches[0] if self.batches else None

    def files_left(self) -> int:
        return sum(len(b.paths) for b in self.batches)

    def is_later(self, batch: Batch) -> bool:
        later = {_key(p) for p in self.session.later}
        return bool(batch.paths) and all(_key(p) in later for p in batch.paths)

    def _remember(self) -> None:
        lists = {k: list(getattr(self.session, k)) for k in ("done", "settled", "to_review", "later", "passed", "apart")}
        lists["settled_batches"] = self.session.settled_batches
        lists["answered"] = self.session.answered
        self.session.answered += 1
        self._history.append((lists, self.service.settings_snapshot()))

    def can_go_back(self) -> bool:
        return bool(self._history)

    def back(self) -> bool:
        """Undo the last batch's answer and show that batch again."""
        if not self._history:
            return False
        lists, settings = self._history.pop()
        for k, v in lists.items():
            setattr(self.session, k, v)
        self.service.restore_settings(settings)
        self.service.guess_labels()
        self.make_batches()
        self.save()
        return True

    def _come_back_later(self, paths: list[str]) -> None:
        """Files skipped or left unticked come back at the end; skipped again, they go to Review as they are."""
        later = {_key(p) for p in self.session.later}
        for p in paths:
            if _key(p) in later:
                self.session.later = [x for x in self.session.later if _key(x) != _key(p)]
                self.session.passed.append(p)
            else:
                self.session.later.append(p)

    def _finished(self, paths: list[str], into: str) -> None:
        keys = {_key(p) for p in paths}
        self.session.later = [x for x in self.session.later if _key(x) not in keys]
        getattr(self.session, into).extend(paths)

    def confirm(self, batch: Batch, ticked: list[str], labels: list[str]) -> Learned:
        """The ticked files get exactly these labels; unticked ones come back later. SortZen learns."""
        self._remember()
        for name in labels:
            if name.lower() not in {x.lower() for x in self.service.labels()}:
                self.service.add_label(name)
        ticked_keys = {_key(p) for p in ticked}
        if ticked:
            self.service.set_file_labels(ticked, labels)
            self._finished(ticked, "done")
        self._come_back_later([p for p in batch.paths if _key(p) not in ticked_keys])
        learned = self._learn()
        self.save()
        return learned

    def send_to_review(self, batch: Batch, ticked: list[str]) -> None:
        """The ticked files go to Review without labels."""
        self._remember()
        ticked_keys = {_key(p) for p in ticked}
        self._finished(ticked, "to_review")
        self._come_back_later([p for p in batch.paths if _key(p) not in ticked_keys])
        self.make_batches()
        self.save()

    def keep_apart(self, batch: Batch, ticked: list[str]) -> None:
        """The ticked files don't belong with the others: they come back later, one by one."""
        self._remember()
        keys = {_key(p) for p in self.session.apart}
        self.session.apart += [p for p in ticked if _key(p) not in keys]
        self._come_back_later(ticked)
        self.make_batches()
        self.save()

    def drop(self, paths: list[str]) -> None:
        """Files moved into "To delete" from Step 3 leave the session."""
        if self.plan is not None:
            gone = {_key(p) for p in paths}
            self.plan.files = [s for s in self.plan.files if _key(s.path) not in gone]
            self.service.forget_files(paths)
        self.make_batches()

    def batch_number(self) -> tuple[int, int]:
        """(this batch's number, how many batches there are now)."""
        return self.session.answered + 1, self.session.answered + len(self.batches)

    def skip(self, batch: Batch) -> None:
        self._remember()
        self._come_back_later(batch.paths)
        self.make_batches()
        self.save()

    def learned_enough(self) -> bool:
        agreed, total = self.service.agreement()
        return total >= SETTLE_CHECKS and agreed >= SETTLE_AGREE * total

    def _learn(self) -> Learned:
        self.service.guess_labels()
        self.make_batches()
        learned = Learned()
        if self.learned_enough():
            for b in [b for b in self.batches if not self.is_later(b) and b.labels and b.certainty >= SETTLE]:
                self._finished(b.paths, "settled")
                learned.settled_batches += 1
                learned.settled_files += len(b.paths)
            if learned.settled_batches:
                self.session.settled_batches += learned.settled_batches
                self.make_batches()
        declined = set(self.service.settings.get("declined_merges") or [])
        merge = label_merge_suggestion(self.service.labels())
        if merge and f"{merge[0]}>{merge[1]}" not in declined:
            learned.merge = merge
        if self.plan is not None:
            learned.folder = next(iter(self.service.label_folder_suggestions(self.plan)), None)
        return learned

    def merge_labels(self, drop: str, keep: str) -> None:
        self.service.merge_label(drop, keep)
        self.service.guess_labels()
        self.make_batches()

    def decline_merge(self, drop: str, keep: str) -> None:
        declined = list(self.service.settings.get("declined_merges") or [])
        self.service.settings.set("declined_merges", declined + [f"{drop}>{keep}"])

    def finish_catalog(self) -> None:
        """Step 3 is done: the files still waiting go to Review as they are."""
        self.session.stage = REVIEW
        self.session.review_batch = 0
        self.save()

    def agreement_text(self) -> str:
        agreed, total = self.service.agreement()
        return f"SortZen matched your choice in {agreed} of your last {total}" if total else ""

    # ---------------------------------------------------------------- Review
    def start_review(self, plan: Plan) -> list[ReviewBatch]:
        """The plan's moves from the folders being sorted, in batches by labels, surest first."""
        self.plan = plan
        records = self.service._records
        level = 101 if self.service.ask_everything() else self.service.autonomy()
        files = [s for s in plan.files if (records.get(s.path) is None or records[s.path].role == "source")
                 and s.path not in plan.companions and not self.service.is_left_out(s.path)]
        found = [ReviewBatch(b, sure=all(s.percent >= level for s in plan.files if s.path in set(b.paths)))
                 for b in review_batches(files, self.service.labels_of, self.service.display)]
        folders = [f for f in plan.folders if f.outcome == KEEP_TOGETHER and f.destination
                   and _key(f.destination) != _key(os.path.dirname(f.path))]
        if folders:
            n = len(folders)
            certainty = round(sum(f.percent for f in folders) / n)
            batch = Batch(FOLDERS_KEY, f"Folders that move as they are · {n} folder{'s' if n != 1 else ''}", [],
                          [], certainty, "", sorted({f.destination for f in folders}))
            found.append(ReviewBatch(batch, sure=all(f.percent >= level for f in folders),
                                     folders=[f.path for f in folders]))
            found.sort(key=lambda r: -r.batch.certainty)
        self.review = found
        reviewed = {_key(p) for p in self.session.reviewed}
        for r in found:                         # sure batches need no check
            if r.sure:
                for p in [*r.batch.paths, *r.folders]:
                    if _key(p) not in reviewed:
                        self.session.reviewed.append(p)
                        reviewed.add(_key(p))
        self.session.stage = REVIEW
        self.session.review_batch = min(self.session.review_batch, max(0, len(found) - 1))
        self.save()
        return found

    def review_index(self) -> int:
        return self.session.review_batch

    def show_review(self, index: int) -> None:
        self.session.review_batch = max(0, min(index, len(self.review) - 1))
        self.save()

    def is_reviewed(self, r: ReviewBatch) -> bool:
        reviewed = {_key(p) for p in self.session.reviewed}
        members = [*r.batch.paths, *r.folders]
        return bool(members) and all(_key(p) in reviewed for p in members)

    def confirm_review(self, r: ReviewBatch) -> bool:
        """Users checked this batch: its plan is kept (SortZen remembers each folder). Returns True when it
        was the last batch."""
        by_folder: dict[str, list[str]] = {}
        for s in self.plan.files if self.plan else []:
            if s.path in r.batch.paths and s.destination:
                by_folder.setdefault(s.destination, []).append(s.path)
        corrected = {path_key(p) for p in self.service.corrections()}
        for folder, paths in by_folder.items():
            paths = [p for p in paths if path_key(p) not in corrected]
            if paths:
                self.service.correct(paths, folder)
        reviewed = {_key(p) for p in self.session.reviewed}
        self.session.reviewed += [p for p in [*r.batch.paths, *r.folders] if _key(p) not in reviewed]
        index = self.review.index(r)
        last = index >= len(self.review) - 1
        if not last:
            self.session.review_batch = index + 1
        self.save()
        return last

    def files_in(self, r: ReviewBatch) -> list:
        wanted = set(r.batch.paths)
        return [s for s in self.plan.files if s.path in wanted] if self.plan else []

    def move_file(self, paths: list[str], folder: str) -> dict:
        """Users dragged files to another folder in the plan; SortZen remembers it. Returns the choices before,
        for Undo."""
        paths = self.service.with_companions(self.plan, paths)
        keys = {_key(p) for p in paths}
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
        undo["new_folders"] = list(self.session.new_folders)
        self.session.new_folders = [f for f in self.session.new_folders
                                    if _key(f) != _key(folder) and not _key(f).startswith(_key(folder) + os.sep)]
        self.save()
        return undo

    def undo_delete_folder(self, undo: dict) -> None:
        self.undo_move_file(undo)
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

    def rules_for(self, folder: str) -> list:
        return [r for r in self.service.rules() if _key(r.destination) == _key(folder)]

    def move_rows(self) -> list:
        """The rows the Move window moves: every reviewed file (and the files that go with it) and folder."""
        if self.plan is None:
            return []
        reviewed = {_key(p) for p in self.session.reviewed}
        companions = {_key(c) for c, main in self.plan.companions.items() if _key(main) in reviewed}
        wanted = reviewed | companions
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
        return describe(self.session, len(self.review) if self.review else 0)


def describe(session: Session, review_batches_total: int = 0) -> str:
    """Where a session is, for the start screen: "Step 3 · 218 files left", "Review · batch 4 of 9"."""
    if session.stage == MOVED:
        return f"Moved · {session.moved:,} files"
    if session.stage == REVIEW:
        total = f" of {review_batches_total}" if review_batches_total else ""
        return f"Review · batch {session.review_batch + 1}{total}"
    if session.stage == CATALOG:
        done = len(session.done) + len(session.settled) + len(session.to_review)
        return f"Step 3 Catalog · {done:,} files done"
    if session.stage == DUPLICATES:
        return "Step 2 Duplicates"
    return "Step 1 Choose"
