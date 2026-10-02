"""Program-wide service: folders, settings, AI service choice, API keys, making the plan, background jobs."""
from __future__ import annotations

import os
import time
from typing import Callable

from ..ai.services import DEFAULT_SERVICE, OLLAMA_URL, SERVICES, make_provider
from ..config import AppPaths, default_paths
from ..repositories.api_keys import ApiKeyStore
from ..repositories.file_index import FileIndex, path_key
from ..repositories.settings import SettingsRepository
from ..engine import Planner, Source
from ..engine.duplicates import CopyGroup, find_copies
from ..engine.plan import Plan
from ..engine.planner import SORT_OUT, TIDY
from ..mover import Mover, MoveRequest, RunResult
from ..mover.mover import same_contents
from ..scanning.file_types import QUEUE_FOLDER, is_queue_folder
from ..scanning.scanner import Scanner
from ..tasks import Estimate, JobRunner, Progress, Status
from ..tasks.gentle import gentle
from . import moving, plan_view

AUTONOMY_DEFAULT = 90
DEFAULTS = {                    # settings with on/off values, and their defaults
    "gentle": False,            # "Be gentle with my computer": lowest priority, short rests
    "read_google_drive": False,  # read file contents on Google Drive (may download them)
    "stop_reading_learned": True,  # Advanced: stop reading left-out folders once learned enough
}
GENTLE_PAUSE = 0.005
PLAN_SHARE = 5                  # planning counts as one fifth of the files on the progress bar
SPEED_DEFAULTS = {"read": 100.0, "remembered": 5000.0, "plan": 1500.0}     # files per second
BIG_FOLDER_FILES = 5000
BIG_FILE_BYTES = 500 * 1024 * 1024
LONG_RUN_SECONDS = 180
LEARNED_FILES = 100             # a left-out folder with this many files read has taught SortZen enough...
LEARNED_NEW_SHARE = 0.25        # ...unless its new files are more than this share of them
MODES = (SORT_OUT, TIDY)
WINDOWS_FOLDERS = {      # name -> Windows known-folder id (found through Windows, so OneDrive moves are followed)
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}


class FolderError(ValueError):
    """A folder can't be added; the message says why."""


def windows_folder(name: str) -> str:
    """Where Windows keeps a standard folder for this user (follows OneDrive and other moves)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("data", ctypes.c_byte * 16)]

            guid = GUID()
            ctypes.memmove(guid.data, uuid.UUID(WINDOWS_FOLDERS[name]).bytes_le, 16)
            result = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result)) == 0:
                path = result.value
                ctypes.windll.ole32.CoTaskMemFree(result)
                return path
        except (OSError, AttributeError, ValueError):
            pass
    return os.path.join(os.path.expanduser("~"), name)


class AppService:
    def __init__(self, paths: AppPaths | None = None, keys: ApiKeyStore | None = None):
        self.paths = paths or default_paths()
        self.settings = SettingsRepository(self.paths.settings_path)
        self.keys = keys or ApiKeyStore()
        self.jobs = JobRunner()
        self.index = FileIndex(self.paths.database_path)
        self.scanner = Scanner(self.index)
        self.mover = Mover(self.paths.runs_dir)

    # ---------------------------------------------------------------- AI service
    def ai_service(self) -> str:
        service = self.settings.get("ai_service", DEFAULT_SERVICE)
        return service if service in SERVICES else DEFAULT_SERVICE

    def set_ai_service(self, service: str) -> None:
        if service not in SERVICES:
            raise ValueError(f"Unknown AI service: {service}")
        self.settings.set("ai_service", service)

    def model(self, service: str | None = None) -> str:
        service = service or self.ai_service()
        models = self.settings.get("ai_models") or {}
        return str(models.get(service) or SERVICES[service].default_model)

    def set_model(self, model: str, service: str | None = None) -> None:
        service = service or self.ai_service()
        models = dict(self.settings.get("ai_models") or {})
        model = (model or "").strip()
        if model and model != SERVICES[service].default_model:
            models[service] = model
        else:
            models.pop(service, None)
        self.settings.set("ai_models", models)

    def ollama_url(self) -> str:
        return str(self.settings.get("ollama_url") or OLLAMA_URL)

    # ---------------------------------------------------------------- API keys
    def api_key(self, service: str | None = None) -> str:
        service = service or self.ai_service()
        info = SERVICES[service]
        return self.keys.load(service, info.key_env) if info.needs_key else ""

    def has_api_key(self, service: str | None = None) -> bool:
        service = service or self.ai_service()
        return not SERVICES[service].needs_key or bool(self.api_key(service))

    def save_api_key(self, key: str, service: str | None = None) -> None:
        self.keys.save(service or self.ai_service(), key)

    def clear_api_key(self, service: str | None = None) -> None:
        self.keys.clear(service or self.ai_service())

    def provider(self):
        service = self.ai_service()
        return make_provider(service, self.api_key(service), self.ollama_url())

    # ---------------------------------------------------------------- folders
    def source_folders(self) -> list[dict]:
        return [dict(f) for f in self.settings.get("sources") or [] if f.get("mode") in MODES]

    def destination_folders(self) -> list[str]:
        return list(self.settings.get("destinations") or [])

    def all_roots(self) -> list[str]:
        return [f["path"] for f in self.source_folders()] + self.destination_folders()

    def _check_new(self, path: str) -> str:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise FolderError(f"The folder {path} can't be found.")
        key = path_key(path)
        if any(_inside(key, p) for p in self.scanner.protected):
            raise FolderError("SortZen doesn't sort Windows or program folders.")
        if any(path_key(p) == key for p in self.all_roots()):
            raise FolderError(f"{os.path.basename(path)} is already added.")
        return path

    def add_source(self, path: str, mode: str = SORT_OUT) -> str:
        if mode not in MODES:
            raise ValueError(f"Unknown way of sorting: {mode}")
        path = self._check_new(path)
        self.settings.set("sources", self.source_folders() + [{"path": path, "mode": mode}])
        return path

    def set_source_mode(self, path: str, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown way of sorting: {mode}")
        self.settings.set("sources", [dict(f, mode=mode) if path_key(f["path"]) == path_key(path) else f
                                      for f in self.source_folders()])

    def add_destination(self, path: str) -> str:
        path = self._check_new(path)
        self.settings.set("destinations", self.destination_folders() + [path])
        return path

    def remove_folder(self, path: str) -> None:
        key = path_key(path)
        self.settings.data["sources"] = [f for f in self.source_folders() if path_key(f["path"]) != key]
        self.settings.data["destinations"] = [d for d in self.destination_folders() if path_key(d) != key]
        self.settings.save()

    def suggested_destinations(self) -> list[str]:
        """The standard Windows folders that exist and aren't added yet."""
        added = {path_key(p) for p in self.all_roots()}
        found = [windows_folder(n) for n in ("Documents", "Pictures", "Music", "Videos")]
        return [p for p in found if os.path.isdir(p) and path_key(p) not in added]

    # ---------------------------------------------------------------- on/off settings
    def option(self, name: str) -> bool:
        return bool(self.settings.get(name, DEFAULTS[name]))

    def set_option(self, name: str, on: bool) -> None:
        if name not in DEFAULTS:
            raise KeyError(name)
        self.settings.set(name, bool(on))

    # ---------------------------------------------------------------- autonomy, answers, corrections
    def autonomy(self) -> int:
        try:
            return max(50, min(100, int(self.settings.get("autonomy", AUTONOMY_DEFAULT))))
        except (TypeError, ValueError):
            return AUTONOMY_DEFAULT

    def set_autonomy(self, level: int) -> None:
        self.settings.set("autonomy", max(50, min(100, int(level))))

    def ask_everything(self) -> bool:
        return bool(self.settings.get("ask_everything", False))

    def set_ask_everything(self, on: bool) -> None:
        self.settings.set("ask_everything", bool(on))

    def answers(self) -> dict[str, int]:
        return dict(self.settings.get("answers") or {})

    def save_answers(self, answers: dict[str, int | None]) -> None:
        current = self.answers()
        for key, choice in answers.items():
            if choice is None:
                current.pop(key, None)
            else:
                current[key] = int(choice)
        self.settings.set("answers", current)

    def corrections(self) -> dict[str, str]:
        return dict(self.settings.get("corrections") or {})

    def correct(self, paths: list[str], destination: str | None) -> dict[str, str | None]:
        """Remember chosen destinations (None forgets them). Returns the previous ones, for Undo."""
        current = self.corrections()
        previous = {p: current.get(p) for p in paths}
        for p in paths:
            if destination is None:
                current.pop(p, None)
            else:
                current[p] = os.path.abspath(destination)
        self.settings.set("corrections", current)
        return previous

    def restore_corrections(self, previous: dict[str, str | None]) -> None:
        current = self.corrections()
        for p, destination in previous.items():
            if destination is None:
                current.pop(p, None)
            else:
                current[p] = destination
        self.settings.set("corrections", current)

    # ---------------------------------------------------------------- left out
    def left_out(self) -> list[str]:
        """Files and folders left exactly where they are; SortZen still learns from them."""
        return list(self.settings.get("left_out") or [])

    def set_left_out(self, paths: list[str], out: bool) -> list[str]:
        """Leave paths out (or include them again). Returns the previous list, for Undo."""
        previous = self.left_out()
        keys = {path_key(p) for p in paths}
        kept = [p for p in previous if path_key(p) not in keys]
        self.settings.set("left_out", kept + [os.path.abspath(p) for p in paths] if out else kept)
        return previous

    def restore_left_out(self, previous: list[str]) -> None:
        self.settings.set("left_out", list(previous))

    def is_left_out(self, path: str) -> bool:
        key = path_key(path)
        return any(_inside(key, path_key(p)) for p in self.left_out())

    def learned_folders(self, counts) -> list[str]:
        """Left-out folders that have taught SortZen enough: their new files are read by name only."""
        if not self.option("stop_reading_learned"):
            return []
        learned = []
        for path in self.left_out():
            for c in counts:
                files, _, new = c.tree.get(path, (0, 0, 0))
                if files and files - new >= LEARNED_FILES and new <= LEARNED_NEW_SHARE * (files - new):
                    learned.append(path)
        return learned

    # ---------------------------------------------------------------- the plan
    def make_plan(self, emit=None, token=None) -> Plan | None:
        """Scan every added folder (remembered results make repeat scans quick) and plan. Moves nothing."""
        with gentle(self.option("gentle")):
            return self._make_plan(emit, token)

    def _make_plan(self, emit=None, token=None) -> Plan | None:
        emit = emit or (lambda event: None)
        self.scanner.read_google_drive = self.option("read_google_drive")
        self.scanner.pause = GENTLE_PAUSE if self.option("gentle") else 0.0
        sources = self.source_folders()
        if not sources:
            raise FolderError("Add a folder to sort first.")
        emit(Status("Counting files", "nothing is opened yet"))
        counts = self.count_folders()
        emit(Estimate(self.estimate_seconds(counts)))
        learned = self.learned_folders(counts)
        total_files = sum(c.files for c in counts)
        plan_units = max(1, total_files // PLAN_SHARE)
        grand = total_files + plan_units
        done_before = 0
        records = []
        started = time.perf_counter()
        read = remembered = 0
        for number, count in enumerate(counts):
            role = "source" if number < len(sources) else "destination"
            emit(Status("Reading", os.path.basename(count.root)))

            def overall(event, offset=done_before):
                if isinstance(event, Progress):
                    event = Progress(offset + event.done, grand)
                emit(event)

            summary = self.scanner.scan(count.root, role, recursive=True,
                                        exclude=[f["path"] for f in sources] if role == "destination" else (),
                                        emit=overall, token=token, listing=count.listing, names_only=learned)
            records += summary.files
            read, remembered = read + summary.read, remembered + summary.remembered
            if summary.cancelled:
                return None
            done_before += count.files
        reading_time = time.perf_counter() - started
        emit(Status("Making the plan", f"{len(records):,} files"))
        emit(Progress(total_files, grand))
        started = time.perf_counter()
        planner = Planner(records, [Source(f["path"], f["mode"]) for f in sources],
                          [c.root for c in counts[len(sources):]],
                          answers=self.answers(), corrections=self.corrections(), left_out=self.left_out())
        plan = planner.plan()
        plan.copies = find_copies(records, plan, self.is_left_out)
        emit(Progress(grand, grand))
        self._learn_speed(read, remembered, reading_time, len(records), time.perf_counter() - started)
        return plan

    # ---------------------------------------------------------------- counting and estimates
    def count_folders(self) -> list:
        """Every added folder's file count, new files and biggest files, without opening any file.

        Sources come first, in the order they were added, then the destination folders.
        """
        sources = self.source_folders()
        source_paths = [f["path"] for f in sources]
        counts = [self.scanner.count(f["path"], recursive=True) for f in sources]
        counts += [self.scanner.count(d, recursive=True, exclude=source_paths)
                   for d in _outermost(self.destination_folders())]
        return counts

    def count_report(self, counts) -> dict:
        """The Folders tab's summary line, time estimate and warnings about what will take longest."""
        files = sum(c.files for c in counts)
        size = sum(c.size for c in counts)
        new = sum(c.new_files for c in counts)
        seconds = self.estimate_seconds(counts)
        minutes = max(1, round(seconds / 60))
        when = "the first time" if new == files else ("" if new else "(everything already read)")
        estimate = "under a minute" if seconds < 60 else f"about {minutes} minute{'s' if minutes != 1 else ''}"
        warnings = []
        for c in counts:
            name = os.path.basename(c.root) or c.root
            for sub, n in c.busiest[:3]:
                if n >= BIG_FOLDER_FILES:
                    warnings.append(f"“{sub}” in {name} holds {n:,} files; this part takes longest.")
            big = [p for p, b in c.biggest if b >= BIG_FILE_BYTES]
            if big:
                warnings.append(f"{len(big)} file{'s' if len(big) != 1 else ''} over 500 MB in {name} (such as "
                                f"“{os.path.basename(big[0])}”): only their names and details are read.")
            if c.google_drive:
                warnings.append(f"{name} is on Google Drive: its files are sorted by name and not downloaded. "
                                "Settings › Read file contents on Google Drive changes this.")
        if seconds > LONG_RUN_SECONDS:
            warnings.append("For the quickest run, close programs you don't need. Or tick “Be gentle with my "
                            "computer” in Settings to keep it quiet (slower).")
        return {"files": files, "size": size, "new": new, "seconds": seconds,
                "estimate": f"{estimate} {when}".strip(), "warnings": warnings}

    def speeds(self) -> dict[str, float]:
        stored = self.settings.get("speeds") or {}
        return {k: float(stored.get(k, v)) for k, v in SPEED_DEFAULTS.items()}

    def estimate_seconds(self, counts) -> float:
        """How long a plan will take: new files are read, unchanged ones come from what's remembered."""
        speed = self.speeds()
        new = sum(c.new_files for c in counts)
        unchanged = sum(c.files - c.new_files for c in counts)
        total = sum(c.files for c in counts)
        slow = 2.0 if self.option("gentle") else 1.0
        return slow * (new / speed["read"] + unchanged / speed["remembered"]) + total / speed["plan"]

    def _learn_speed(self, read: int, remembered: int, reading_time: float, planned: int, plan_time: float) -> None:
        speed = self.speeds()
        if read >= 50 and reading_time > 0:
            measured = read / max(0.001, reading_time - remembered / speed["remembered"])
            speed["read"] = round(0.5 * speed["read"] + 0.5 * max(1.0, measured), 1)
        if planned >= 100 and plan_time > 0:
            speed["plan"] = round(0.5 * speed["plan"] + 0.5 * planned / plan_time, 1)
        self.settings.set("speeds", speed)

    def plan_rows(self, plan: Plan) -> dict[str, list[plan_view.PlanRow]]:
        return plan_view.rows(plan, self.autonomy(), self.ask_everything())

    def display(self, path: str | None) -> str:
        return plan_view.display(path, self.all_roots())

    def export_plan(self, plan: Plan, target: str) -> None:
        plan_view.export_xlsx(plan, target, self.all_roots(), self.autonomy(), self.ask_everything())

    def destination_choices(self, plan: Plan | None = None) -> list[str]:
        """Folders a file can be sent to: every folder under the destination folders and tidied folders."""
        roots = self.destination_folders() + [f["path"] for f in self.source_folders() if f["mode"] == TIDY]
        found = set()
        for root in roots:
            for folder, dirs, _ in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and not is_queue_folder(d)]
                found.add(folder)
        if plan:
            found.update(plan.new_folders)
        return sorted(found, key=lambda f: self.display(f).lower())

    # ---------------------------------------------------------------- moving
    def move_preview(self, plan: Plan, rows: list[plan_view.PlanRow]) -> moving.MovePreview:
        """What a move of these rows would do, for the confirmation window. Touches nothing."""
        return moving.preview(plan, rows, self.all_roots())

    def move(self, plan: Plan, rows: list[plan_view.PlanRow], emit=None, token=None) -> RunResult:
        """Move the ticked rows after users confirmed them; emptied "sort inside" folders are removed."""
        requests = moving.requests(rows)
        emptied = moving.emptied_folders(plan, requests, self.all_roots())
        with gentle(self.option("gentle")):
            result = self.mover.run(requests, emptied, emit, token)
        self._carry_index(result)
        return result

    def queue_folder(self, path: str) -> str:
        """Where a copy goes: a dated "Queued for deletion" folder inside its added folder, keeping its
        subfolders, so it is easy to find and put back by hand."""
        place = self._root_of(path)
        root = place[0] if place else os.path.dirname(path)
        relative = os.path.relpath(os.path.dirname(os.path.abspath(path)), root)
        queue = os.path.join(root, f"{QUEUE_FOLDER} {time.strftime('%Y-%m-%d')}")
        return os.path.normpath(os.path.join(queue, relative)) if relative != "." else queue

    def queue_copies(self, groups: list[CopyGroup], emit=None, token=None) -> RunResult:
        """Move the ticked extra copies into "Queued for deletion" folders. Nothing is deleted.

        Right before each one moves, it is checked byte for byte against the copy kept; anything that
        is no longer an exact copy stays where it is.
        """
        emit = emit or (lambda event: None)
        requests, skipped = [], []
        ticked = [(g, c) for g in groups for c in g.extras if c.ticked]
        with gentle(self.option("gentle")):
            for done, (group, copy) in enumerate(ticked, start=1):
                if token is not None and token.cancelled:
                    break
                emit(Status("Checking copies", copy.name))
                kept = group.kept.path
                if not os.path.isfile(kept):
                    skipped.append((copy.path, f"The copy to keep (“{group.kept.name}”) is no longer there"))
                elif not os.path.isfile(copy.path):
                    skipped.append((copy.path, "It's no longer there"))
                elif not same_contents(kept, copy.path):
                    skipped.append((copy.path, f"It's no longer an exact copy of “{group.kept.name}”"))
                else:
                    requests.append(MoveRequest(copy.path, self.queue_folder(copy.path)))
                emit(Progress(done, len(ticked) * 2))
            stages = len(ticked)

            def moving(event):
                emit(Progress(stages + event.done, stages * 2) if isinstance(event, Progress) else event)

            result = self.mover.run(requests, (), moving, token, kind="duplicates")
        result.failed = skipped + result.failed
        result.cancelled = result.cancelled or bool(token is not None and token.cancelled)
        return result

    def move_runs(self) -> list[dict]:
        """Past moves, newest first, for Undo."""
        return self.mover.runs()

    def undo_move(self, log: str, emit=None, token=None) -> RunResult:
        """Put everything from one move back where it was."""
        result = self.mover.undo(log, emit)
        self._carry_index(result)
        return result

    def _carry_index(self, result: RunResult) -> None:
        if result.moves:
            self.index.moved(result.moves, self._root_of)

    def _root_of(self, path: str) -> tuple[str, str] | None:
        """The added folder holding a path, and its role ("source" or "destination")."""
        key = path_key(path)
        roots = [(f["path"], "source") for f in self.source_folders()] + \
                [(d, "destination") for d in self.destination_folders()]
        inside = [(r, role) for r, role in roots if _inside(key, path_key(r))]
        return max(inside, key=lambda x: len(x[0])) if inside else None

    # ---------------------------------------------------------------- background jobs
    def run_job(self, name: str, work: Callable, on_event: Callable):
        return self.jobs.start(name, work, on_event)

    def stop_job(self) -> None:
        self.jobs.cancel()


def _inside(key: str, root: str) -> bool:
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


def _outermost(folders) -> list:
    keys = {path_key(f): f for f in folders}

    def inside(key, other):
        return key.startswith(other.rstrip(os.sep) + os.sep)

    return [f for k, f in keys.items() if not any(inside(k, other) for other in keys if other != k)]
