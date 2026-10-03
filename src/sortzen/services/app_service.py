"""Program-wide service: folders, settings, AI service choice, API keys, making the plan, background jobs."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

from ..ai import privacy
from ..ai.errors import AIProblem, explain
from ..ai.services import DEFAULT_SERVICE, OLLAMA_URL, SERVICES, make_provider
from ..ai.sorter import AIFile, AIFolder, AIRun, AISorter
from ..config import COST_CAP_PER_1000_FILES, AppPaths, default_paths
from ..engine.ai_evidence import apply_ai
from ..engine.groups import FileGroup, find_groups
from ..engine.rules import Rule, RuleSuggestion, apply_rules, rename_planned, suggest_rule
from ..repositories.ai_answers import AIAnswers, answer_key
from ..repositories.api_keys import ApiKeyStore
from ..repositories.file_index import FileIndex, path_key
from ..repositories.settings import SettingsRepository
from ..engine import Planner, Source
from ..engine.duplicates import CopyGroup, find_copies
from ..engine.plan import STAY as STAY_ACTION, Plan
from ..engine.planner import SORT_OUT, TIDY
from ..mover import Mover, MoveRequest, RunResult
from ..mover.mover import same_contents
from ..scanning.file_types import GOOGLE_LINKS, QUEUE_FOLDER, is_queue_folder
from ..scanning import ocr
from ..scanning.scanner import Scanner
from ..tasks import Estimate, JobRunner, Progress, Status
from ..tasks.gentle import gentle
from . import catalog as catalog_model, moving, plan_view, profile

AUTONOMY_DEFAULT = 90
LABEL_SURE = 70             # a guessed label this sure needs no check
LEARNED_ENOUGH = 10         # changes from users before SortZen offers to catalog again
NOTE_PERCENT = 85           # a note that names a folder makes SortZen this sure
DEFAULTS = {                    # settings with on/off values, and their defaults
    "gentle": False,            # "Be gentle with my computer": lowest priority, short rests
    "read_google_drive": False,  # read file contents on Google Drive (may download them)
    "stop_reading_learned": True,  # Advanced: stop reading left-out folders once learned enough
    "meaning": True,            # match files by meaning (a small model on this PC)
    "read_scans": True,         # read text in scans and pictures of documents (Windows text recognition, on this PC)
}
AI_DEFAULTS = {                 # what the AI step may send, and how much it may spend
    "ai_enabled": True,
    "ai_privacy": privacy.NAME_ONLY,            # or privacy.BEGINNING
    "ai_name_only_folders": [],
    "ai_name_only_words": privacy.DEFAULT_NAME_ONLY_WORDS,
    "ai_previews": False,
    "house_rules": "",
    "ai_cap_per_1000": COST_CAP_PER_1000_FILES,
}
AI_MAX_FOLDERS = 300            # folders listed to the AI service (those holding the most files)
AI_EXAMPLES = 3                 # example file names per folder
RECENT_DESTINATIONS = 20       # folders remembered for quick choosing
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
        self.ai_answers = AIAnswers(self.paths.database_path)
        self._records: dict = {}            # the last plan's files, by path
        self._guesses: dict = {}            # labels SortZen guessed for them, by path key
        self._embedder = None               # the meaning model (loaded when first needed)
        self._ai_catalog: list = []          # the AI's last suggestions for the catalog

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

    def model_choices(self, service: str | None = None) -> list[str]:
        """Models for the drop-down: the usual one, the list last fetched from the service, and the one in use."""
        service = service or self.ai_service()
        fetched = (self.settings.get("ai_model_lists") or {}).get(service) or []
        found = [SERVICES[service].default_model, *fetched, self.model(service)]
        return list(dict.fromkeys(m for m in found if m))

    def fetch_models(self, service: str | None = None, key: str = "") -> list[str]:
        """Ask the service which models it offers (needs the key, except for OpenRouter's list and Ollama).

        Raises AIProblem with a plain explanation when it can't."""
        service = service or self.ai_service()
        name = SERVICES[service].name
        try:
            models = self._make_provider(service, key, listing=True).list_models()
        except Exception as exc:
            raise AIProblem(explain(exc, name, "")) from exc
        if not models:
            raise AIProblem(f"{name} didn't list any models for this key.")
        lists = dict(self.settings.get("ai_model_lists") or {})
        lists[service] = models
        self.settings.set("ai_model_lists", lists)
        return models

    def check_ai(self, service: str | None = None, model: str | None = None, key: str = "") -> None:
        """A tiny request that proves the service, model and key work. Raises AIProblem when they don't."""
        service = service or self.ai_service()
        model = (model or "").strip() or self.model(service)
        try:
            self._make_provider(service, key).generate_json(model, ['Reply with this JSON only: {"ok": true}'])
        except Exception as exc:
            raise AIProblem(explain(exc, SERVICES[service].name, model)) from exc

    def _make_provider(self, service: str, key: str = "", listing: bool = False):
        info = SERVICES[service]
        key = (key or "").strip() or self.api_key(service)
        if info.needs_key and not key and not (listing and service == "openrouter"):    # its list is public
            raise AIProblem(f"Paste your {info.name} API key first.")
        return make_provider(service, key or "list-only", self.ollama_url())

    def ollama_url(self) -> str:
        return str(self.settings.get("ollama_url") or OLLAMA_URL)

    def ai_value(self, name: str):
        value = self.settings.get(name)
        return AI_DEFAULTS[name] if value is None else value

    def set_ai_value(self, name: str, value) -> None:
        if name not in AI_DEFAULTS:
            raise ValueError(f"Unknown AI setting: {name}")
        self.settings.set(name, value)

    def ai_ready(self) -> bool:
        """The AI step can run: it is switched on and the service has its key (Ollama needs none)."""
        return bool(self.ai_value("ai_enabled")) and self.has_api_key()

    def ai_spent(self, month: str | None = None) -> float:
        return float((self.settings.get("ai_spent") or {}).get(month or time.strftime("%Y-%m"), 0.0))

    def _add_spent(self, dollars: float) -> None:
        spent = dict(self.settings.get("ai_spent") or {})
        month = time.strftime("%Y-%m")
        spent[month] = round(spent.get(month, 0.0) + dollars, 6)
        self.settings.set("ai_spent", spent)

    def forget_ai_answers(self) -> None:
        self.ai_answers.forget_all()

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

    def answers(self) -> dict[str, int | str]:
        return dict(self.settings.get("answers") or {})

    def save_answers(self, answers: dict[str, int | str | None]) -> None:
        """Answers by question key: a choice's number, a folder users named, or None to forget it."""
        current = self.answers()
        for key, choice in answers.items():
            if choice is None or choice == "":
                current.pop(key, None)
            elif isinstance(choice, str):
                current[key] = os.path.abspath(choice)
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
        self._learned(len(paths))
        return previous

    def restore_corrections(self, previous: dict[str, str | None]) -> None:
        current = self.corrections()
        for p, destination in previous.items():
            if destination is None:
                current.pop(p, None)
            else:
                current[p] = destination
        self.settings.set("corrections", current)

    # ---------------------------------------------------------------- recent destinations
    def recent_destinations(self, plan: Plan | None = None) -> list[str]:
        """The folders most recently chosen as destinations, newest first (those that exist or are planned)."""
        planned = {path_key(f) for f in plan.new_folders} if plan else set()
        return [f for f in self.settings.get("recent_destinations") or []
                if os.path.isdir(f) or path_key(f) in planned][:RECENT_DESTINATIONS]

    def note_destination(self, folder: str) -> None:
        folder = os.path.abspath(folder)
        recent = [f for f in self.settings.get("recent_destinations") or [] if path_key(f) != path_key(folder)]
        self.settings.set("recent_destinations", [folder, *recent][:RECENT_DESTINATIONS])

    # ---------------------------------------------------------------- the catalog
    def catalog_edits(self) -> dict:
        return dict(self.settings.get("catalog") or {})

    def _set_catalog(self, edits: dict) -> None:
        self.settings.set("catalog", edits)

    def catalog(self, plan: Plan | None = None) -> list:
        """Every category, parents first: from the destination folders and the folders being tidied."""
        roots = self.destination_folders() + [f["path"] for f in self.source_folders() if f["mode"] == TIDY]
        return catalog_model.build(roots, self.catalog_edits(), self.folder_notes(), self.rules(),
                                   chosen=self.corrections())

    def catalog_hidden(self) -> list[str]:
        """Folders of categories files are never sent to."""
        return list(self.catalog_edits().get("hidden") or [])

    def _edit_map(self, part: str, folder: str, value) -> None:
        edits = self.catalog_edits()
        values = {k: v for k, v in (edits.get(part) or {}).items() if path_key(k) != path_key(folder)}
        if value not in (None, "", []):
            values[os.path.abspath(folder)] = value
        edits[part] = values
        self._set_catalog(edits)

    def rename_category(self, folder: str, name: str) -> None:
        """The name shown in the catalog (the folder keeps its name; renaming the folder is rename_folder)."""
        name = (name or "").strip()
        self._edit_map("names", folder, name if name and name != os.path.basename(folder) else None)

    def add_category_folder(self, folder: str, other: str) -> None:
        """Another folder for a category, e.g. its counterpart on another drive."""
        current = next((v for k, v in (self.catalog_edits().get("extra") or {}).items()
                        if path_key(k) == path_key(folder)), [])
        if path_key(other) not in {path_key(f) for f in current} and path_key(other) != path_key(folder):
            self._edit_map("extra", folder, current + [os.path.abspath(other)])

    def remove_category_folder(self, folder: str, other: str) -> None:
        current = next((v for k, v in (self.catalog_edits().get("extra") or {}).items()
                        if path_key(k) == path_key(folder)), [])
        self._edit_map("extra", folder, [f for f in current if path_key(f) != path_key(other)])

    def set_category_hidden(self, folder: str, hidden: bool) -> None:
        """A category files are never sent to (it still teaches SortZen)."""
        edits = self.catalog_edits()
        kept = [p for p in edits.get("hidden") or [] if path_key(p) != path_key(folder)]
        edits["hidden"] = kept + [os.path.abspath(folder)] if hidden else kept
        self._set_catalog(edits)

    def merge_category(self, folder: str, into: str | None) -> None:
        """From now on, files for this category go to ``into`` (None undoes the merge)."""
        if into and path_key(into) == path_key(folder):
            raise FolderError("A category can't be merged into itself.")
        self._edit_map("merged", folder, os.path.abspath(into) if into else None)

    def category_feedback(self, folder: str, kind: str, text: str = "") -> None:
        if kind not in catalog_model.FEEDBACK:
            raise ValueError(f"Unknown feedback: {kind}")
        self._set_catalog(catalog_model.with_feedback(self.catalog_edits(), folder, kind, text))

    def catalog_suggestions(self, categories: list | None = None) -> list:
        """Improvements to the catalog worked out on the PC, with the AI's last ones still waiting."""
        from ..engine.catalog_review import review

        categories = categories if categories is not None else self.catalog()
        declined = set(self.catalog_edits().get("declined") or [])
        waiting = [s for s in self._ai_catalog if s.key not in declined]
        return waiting + review(categories, declined)

    def decline_suggestion(self, suggestion) -> None:
        """Never suggest this again."""
        edits = self.catalog_edits()
        edits["declined"] = list(edits.get("declined") or []) + [suggestion.key]
        self._set_catalog(edits)
        self._ai_catalog = [s for s in self._ai_catalog if s.key != suggestion.key]

    def catalog_ai_estimate(self) -> dict:
        from ..ai import catalog_review as ai_review

        service = SERVICES[self.ai_service()]
        return {"service": service.name, "local": service.key == "ollama",
                "cost": ai_review.estimate(service.key, self.catalog(), self.display),
                "categories": len(self.catalog())}

    def ask_ai_about_catalog(self, emit=None, token=None, provider=None) -> list:
        """The AI service's suggestions for the catalog (names, counts, notes, a few example names and
        feedback are sent; never file contents)."""
        from ..ai import catalog_review as ai_review

        emit = emit or (lambda event: None)
        categories = self.catalog()
        service = SERVICES[self.ai_service()]
        emit(Status(f"Asking {service.name} about the catalog", f"{len(categories):,} categories"))
        try:
            provider = provider or self.provider()
            reply = provider.generate_json(self.model(), [ai_review.request(categories, self.display)])
        except Exception as exc:
            raise AIProblem(explain(exc, service.name, self.model())) from exc
        from ..ai.costs import cost
        self._add_spent(cost(service.key, reply.usage.input_tokens, reply.usage.output_tokens))
        declined = set(self.catalog_edits().get("declined") or [])
        self._ai_catalog = [s for s in ai_review.parse(reply.text, categories, self.display, service.name)
                            if s.key not in declined]
        return self._ai_catalog

    def split_requests(self, suggestion) -> list[MoveRequest]:
        """The moves a split makes: each part's files into a subfolder named after it."""
        requests = []
        for name, members in suggestion.parts:
            folder = os.path.join(suggestion.category, name)
            requests += [MoveRequest(os.path.join(suggestion.category, n), folder) for n in members
                         if os.path.exists(os.path.join(suggestion.category, n))]
        return requests

    def add_subcategory(self, parent: str, name: str, note: str = "") -> str:
        """A new, empty subfolder for a category, with what belongs in it. Returns its folder."""
        name = (name or "").strip().rstrip(". ")
        if not name:
            raise FolderError("Type a name for the subcategory.")
        bad = sorted(set(name) & set('\\/:*?"<>|'))
        if bad:
            raise FolderError(f"Names can't contain {' '.join(bad)}")
        folder = os.path.join(parent, name)
        if os.path.lexists(folder):
            raise FolderError(f"“{name}” is already there.")
        os.mkdir(folder)
        if note.strip():
            self.set_folder_note(folder, note)
        return folder

    def remove_empty_subcategory(self, folder: str) -> None:
        """Undo for add_subcategory: the folder is removed only while nothing is in it."""
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)

    def merge_files(self, folder: str, into: str) -> list[MoveRequest]:
        """What moving a category's files into another category would move (for the preview)."""
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
        return [MoveRequest(e.path, into) for e in entries
                if not e.name.startswith((".", "~$")) and not is_queue_folder(e.name)]

    def reorganize(self, requests: list[MoveRequest], emit=None, token=None, kind: str = "catalog") -> RunResult:
        """Move files and folders to new places in the catalog, logged so Undo puts them back."""
        with gentle(self.option("gentle")):
            result = self.mover.run(requests, (), emit, token, kind=kind)
        self._carry_index(result)
        return result

    # ---------------------------------------------------------------- placing files by hand
    def category_files(self, folder: str) -> list[dict]:
        """The files directly in a category's folder: name, path, size and when each was last changed."""
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
        found = []
        for e in entries:
            if e.name.startswith((".", "~$")):
                continue
            try:
                if not e.is_file(follow_symlinks=False):
                    continue
                info = e.stat(follow_symlinks=False)
            except OSError:
                continue
            found.append({"name": e.name, "path": e.path, "size": info.st_size, "modified": info.st_mtime})
        return sorted(found, key=lambda f: f["name"].lower())

    def drop_requests(self, paths: list[str], folder: str) -> list[MoveRequest]:
        """What putting files and folders into a category moves: everything not already directly in it,
        and never a folder into itself or one of its own subfolders."""
        target = path_key(folder)
        requests = []
        for path in dict.fromkeys(os.path.abspath(p) for p in paths):
            if not os.path.lexists(path) or path_key(os.path.dirname(path)) == target:
                continue
            if os.path.isdir(path) and _inside(target, path_key(path)):
                continue
            requests.append(MoveRequest(path, os.path.abspath(folder)))
        return requests

    def place(self, requests: list[MoveRequest], emit=None, token=None) -> RunResult:
        """Move what users put into categories, logged so Undo puts it back. Each file's new folder is
        remembered as their choice: plans keep it there, learn from it and suggest rules from it."""
        result = self.reorganize(requests, emit, token, kind="placed")
        for old, new in result.moves:
            if os.path.isdir(new):              # a moved category keeps its name, note and settings
                self._remap_paths(old, new)
        chosen = {new: os.path.dirname(new) for _, new in result.moves if os.path.isfile(new)}
        if chosen:
            current = self.corrections()
            current.update(chosen)
            self.settings.set("corrections", current)
        for folder in dict.fromkeys(r.destination for r in requests):
            self.note_destination(folder)
        return result

    def delete_requests(self, paths: list[str]) -> list[MoveRequest]:
        """What deleting files moves: each into a dated "Queued for deletion" folder in its added folder."""
        return [MoveRequest(p, self.queue_folder(p)) for p in dict.fromkeys(os.path.abspath(p) for p in paths)
                if os.path.isfile(p) and not any(is_queue_folder(part) for part in p.split(os.sep))]

    def delete(self, requests: list[MoveRequest], emit=None, token=None) -> RunResult:
        """Move files into "Queued for deletion" folders. Nothing is deleted; Undo puts them back."""
        return self.reorganize(requests, emit, token, kind="deleted")

    # ---------------------------------------------------------------- labels
    def labels(self) -> list[str]:
        """Users' labels, the most important first (the order is their priority)."""
        return [x if isinstance(x, str) else x.get("name", "") for x in self._label_data().get("names") or []]

    def _label_data(self) -> dict:
        return dict(self.settings.get("labels") or {})

    def _save_label_data(self, **parts) -> None:
        data = self._label_data()
        data.update(parts)              # an empty list is kept: users took every label away
        self.settings.set("labels", data)

    def users_labels(self) -> dict[str, list[str]]:
        """The labels users gave files themselves, by file."""
        return {k: list(v) for k, v in (self._label_data().get("files") or {}).items()}

    def ai_labels(self) -> dict[str, list[list]]:
        """Labels the AI gave files: [label, percent], by file."""
        return {k: [list(x) for x in v] for k, v in (self._label_data().get("ai") or {}).items()}

    def add_label(self, name: str) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise FolderError("Type a name for the label.")
        if any(x.lower() == name.lower() for x in self.labels()):
            raise FolderError(f"There is already a label “{name}”.")
        self._save_label_data(names=self.labels() + [name])
        return name

    def set_label_order(self, names: list[str]) -> None:
        """A new priority: the first label counts most when SortZen guesses."""
        known = self.labels()
        self._save_label_data(names=[n for n in names if n in known] + [n for n in known if n not in names])

    def rename_label(self, old: str, new: str) -> None:
        new = " ".join((new or "").split())
        if not new or any(x.lower() == new.lower() and x != old for x in self.labels()):
            raise FolderError(f"There is already a label “{new}”." if new else "Type a name for the label.")
        swap = lambda v: [new if x == old else x for x in v]                       # noqa: E731
        self._save_label_data(names=swap(self.labels()),
                              files={k: swap(v) for k, v in self.users_labels().items()},
                              ai={k: [[new if a == old else a, b] for a, b in v] for k, v in self.ai_labels().items()})
        self._guesses = {}

    def remove_label(self, name: str) -> None:
        """Forget a label, on every file."""
        self._save_label_data(names=[x for x in self.labels() if x != name],
                              files={k: [x for x in v if x != name] for k, v in self.users_labels().items()},
                              ai={k: [x for x in v if x[0] != name] for k, v in self.ai_labels().items()})
        self._guesses = {}

    def label_guesses(self, path: str) -> list[tuple[str, int, str]]:
        """Every label a file has, surest first: (label, percent, who or why). Users' own labels are 100%."""
        key = path_key(path)
        mine = next((v for k, v in self.users_labels().items() if path_key(k) == key), None)
        if mine is not None:
            return [(label, 100, "You") for label in mine]
        ai = next((v for k, v in self.ai_labels().items() if path_key(k) == key), None)
        if ai:
            return [(a, int(b), "AI") for a, b in sorted(ai, key=lambda x: -x[1])]
        return list(getattr(self, "_guesses", {}).get(key, []))

    def labels_of(self, path: str, sure: int = 50) -> list[str]:
        """The labels a file has (users' own, or guessed at least this sure)."""
        return [label for label, percent, _ in self.label_guesses(path) if percent >= sure]

    def set_labels(self, paths: list[str], name: str, on: bool) -> None:
        """Give files a label, or take it away. A file's labels become users' own: what SortZen or the AI
        guessed for it is kept, with this change."""
        files = self.users_labels()
        for path in paths:
            key = next((k for k in files if path_key(k) == path_key(path)), os.path.abspath(path))
            labels = [x for x in (files[key] if key in files else self.labels_of(path)) if x != name]
            files[key] = labels + [name] if on else labels
        self._save_label_data(files=files)
        self._learned(len(paths))

    def guess_labels(self, emit=None) -> int:
        """Label the files SortZen knows on this PC (users' and the AI's labels are kept). Returns how many
        files have a label now."""
        from ..engine.labeling import guess_labels

        names = self.labels()
        if not names or not self._records:
            self._guesses = {}
            return 0
        if emit:
            emit(Status("Labelling", f"{len(self._records):,} files"))
        known = {k: v for k, v in self.users_labels().items()}
        for k, v in self.ai_labels().items():
            known.setdefault(k, [a for a, b in v if b >= 50])
        guesses = guess_labels(list(self._records.values()), names, known, self.file_notes())
        self._guesses = {path_key(k): v for k, v in guesses.items()}
        return sum(1 for r in self._records.values() if self.labels_of(r.path))

    def _effective_labels(self) -> dict[str, list[tuple[str, int]]]:
        found = {}
        for r in self._records.values():
            labels = [(label, percent) for label, percent, _ in self.label_guesses(r.path) if percent >= 50]
            if labels:
                found[r.path] = labels
        return found

    def _apply_labels(self, plan: Plan) -> None:
        """Labels as evidence for folders (from the folders' labelled files and where users put files)."""
        from ..engine.labeling import folder_labels, label_evidence

        names = self.labels()
        if not names:
            return
        labelled = self._effective_labels()
        if not labelled:
            return
        valid = self._ai_valid(plan)
        folders = {}
        for r in self._records.values():
            folder = os.path.dirname(r.path)
            if (r.role == "destination" or valid(folder)) and not self.is_left_out(folder):
                folders[os.path.normcase(folder)] = folder
        corrections = self.corrections()
        corrected = {path_key(p) for p in corrections}
        label_evidence(plan, labelled, folder_labels(labelled, corrections), names, self.display,
                       lambda p: path_key(p) in corrected, folders)

    def unsure_files(self, plan: Plan) -> list:
        """The files from the folders being sorted that need users: no sure label, or no sure folder."""
        level = self.autonomy()
        corrections = {path_key(p) for p in self.corrections()}
        mine = {path_key(p) for p in self.users_labels()}
        found = []
        for s in plan.files:
            record = self._records.get(s.path)
            if record is None or record.role != "source" or s.topic or self.is_left_out(s.path):
                continue
            guesses = self.label_guesses(s.path)
            label_unsure = bool(self.labels()) and path_key(s.path) not in mine and \
                (not guesses or guesses[0][1] < LABEL_SURE)
            folder_unsure = path_key(s.path) not in corrections and (s.destination is None or s.percent < level)
            if label_unsure or folder_unsure:
                found.append(s)
        return found

    # ---------------------------------------------------------------- learning
    def _learned(self, n: int = 1) -> None:
        self.settings.set("learned_since_plan", int(self.settings.get("learned_since_plan") or 0) + n)

    def learned_since_plan(self) -> int:
        """Changes users made since the plan was last made (labels, files placed, rules, notes)."""
        return int(self.settings.get("learned_since_plan") or 0)

    def ready_to_recatalog(self) -> bool:
        return self.learned_since_plan() >= LEARNED_ENOUGH

    # ---------------------------------------------------------------- file notes and kept-together folders
    def file_notes(self) -> dict[str, str]:
        """What users wrote about single files ("this one is for the 2023 audit")."""
        return dict(self.settings.get("file_notes") or {})

    def file_note(self, path: str) -> str:
        key = path_key(path)
        return next((v for k, v in self.file_notes().items() if path_key(k) == key), "")

    def set_file_note(self, path: str, text: str) -> None:
        notes = {k: v for k, v in self.file_notes().items() if path_key(k) != path_key(path)}
        if (text or "").strip():
            notes[os.path.abspath(path)] = text.strip()
        self.settings.set("file_notes", notes)
        self._learned()

    def _apply_file_notes(self, plan: Plan) -> None:
        """A note that names a folder sends the file there (users' words, so quite sure)."""
        from ..engine.features import words as words_of
        from ..engine.plan import Reason

        notes = {path_key(k): v for k, v in self.file_notes().items()}
        if not notes:
            return
        corrected = {path_key(p) for p in self.corrections()}
        valid = self._ai_valid(plan)
        folders = {os.path.dirname(r.path) for r in self._records.values()
                   if r.role == "destination" or valid(os.path.dirname(r.path))}
        named = [(f, set(words_of(os.path.basename(f)))) for f in folders]
        for s in plan.files:
            note = notes.get(path_key(s.path))
            if not note or path_key(s.path) in corrected:
                continue
            said = set(words_of(note))
            fits = [(len(w), f) for f, w in named if w and w <= said]
            if not fits:
                continue
            target = max(fits)[1]
            if not s.destination or os.path.normcase(s.destination) != os.path.normcase(target):
                if s.destination:
                    s.runner_up = (s.destination, s.percent)
                s.destination, s.new_folder = target, False
            s.percent = max(s.percent, NOTE_PERCENT)
            s.reasons.insert(0, Reason(True, f"Your note: “{note[:80]}”"))

    def keep_folder_together(self, folder: str) -> None:
        """A rule for a folder being sorted: everything in it moves together, as it is."""
        from ..engine.overview import _folder_choices, folder_key
        from ..engine.plan import KEEP_TOGETHER

        source = next((f for f in self.source_folders() if _inside(path_key(folder), path_key(f["path"]))), None)
        if source is None or path_key(source["path"]) == path_key(folder):
            raise FolderError("Only folders inside a folder being sorted can be kept together.")
        choices = _folder_choices(source["mode"])
        keep = next((i for i, c in enumerate(choices) if c.outcome == KEEP_TOGETHER), None)
        if keep is None:
            raise FolderError("Folders being tidied stay where they are already.")
        self.save_answers({folder_key(os.path.abspath(folder)): keep})
        self._learned()

    # ---------------------------------------------------------------- similar and different
    def pairs(self) -> dict[str, list[list[str]]]:
        """Files users said are similar to, or different from, another file: {"similar": [[file, other]], ...}."""
        found = self.settings.get("pairs") or {}
        return {"similar": [list(x) for x in found.get("similar") or []],
                "different": [list(x) for x in found.get("different") or []]}

    def pair_files(self, paths: list[str], other: str, kind: str, plan: Plan | None = None) -> None:
        """Remember that files are similar to (kind "similar") or different from ("different") another file,
        replacing anything said before about the same two files. With a plan, it is used there at once."""
        pairs = self.pairs()
        keys = {(path_key(p), path_key(other)) for p in paths}
        for k in ("similar", "different"):
            pairs[k] = [x for x in pairs[k] if (path_key(x[0]), path_key(x[1])) not in keys]
        pairs[kind] += [[os.path.abspath(p), os.path.abspath(other)] for p in paths
                        if path_key(p) != path_key(other)]
        self.settings.set("pairs", pairs)
        if plan is not None:
            fresh = [(os.path.abspath(p), os.path.abspath(other)) for p in paths]
            self._apply_pairs(plan, fresh if kind == "similar" else [], fresh if kind == "different" else [])

    def forget_pairs(self, paths: list[str]) -> None:
        keys = {path_key(p) for p in paths}
        pairs = self.pairs()
        self.settings.set("pairs", {k: [x for x in v if path_key(x[0]) not in keys] for k, v in pairs.items()})

    def pairs_of(self, path: str) -> list[tuple[str, str]]:
        """What was said about one file: (kind, other file)."""
        key = path_key(path)
        return [(k, x[1]) for k, v in self.pairs().items() for x in v if path_key(x[0]) == key]

    def _apply_pairs(self, plan: Plan, similar=None, different=None) -> None:
        from ..engine.pairs import apply_pairs

        if similar is None and different is None:
            pairs = self.pairs()
            similar, different = [tuple(x) for x in pairs["similar"]], [tuple(x) for x in pairs["different"]]
        if not similar and not different:
            return
        by_path = {path_key(s.path): s for s in plan.files}
        corrected = {path_key(p) for p in self.corrections()}

        def home_of(other: str) -> str | None:
            planned = by_path.get(path_key(other))
            if planned is not None:
                return planned.destination if planned.percent >= 50 else None
            return os.path.dirname(other) if os.path.exists(other) else None

        apply_pairs(plan, similar or [], different or [], home_of, self.display, lambda p: path_key(p) in corrected)

    # ---------------------------------------------------------------- to place
    def known_files(self) -> list[str]:
        """Every file SortZen knows from the last plan (to pick one a file is similar to or different from)."""
        return sorted(self._records, key=str.lower)

    # ---------------------------------------------------------------- folder notes
    def folder_notes(self) -> dict[str, str]:
        """What users wrote about folders ("pay stubs, T4s, timesheets"), by folder."""
        return dict(self.settings.get("folder_notes") or {})

    def set_folder_note(self, folder: str, text: str) -> dict[str, str]:
        """Write (or, with empty text, remove) a folder's note. Returns the notes before, for Undo."""
        before = self.folder_notes()
        notes = {k: v for k, v in before.items() if path_key(k) != path_key(folder)}
        if (text or "").strip():
            notes[os.path.abspath(folder)] = text.strip()
        self.settings.set("folder_notes", notes)
        return before

    def restore_folder_notes(self, before: dict[str, str]) -> None:
        self.settings.set("folder_notes", dict(before))

    def folder_note(self, folder: str) -> str:
        key = path_key(folder)
        return next((v for k, v in self.folder_notes().items() if path_key(k) == key), "")

    # ---------------------------------------------------------------- rules
    def rules(self) -> list[Rule]:
        found = []
        for r in self.settings.get("rules") or []:
            try:
                found.append(Rule(str(r.get("word") or ""), str(r["destination"]), str(r.get("ext") or ""),
                                  str(r.get("shape") or ""), str(r.get("example") or ""), str(r.get("label") or "")))
            except (KeyError, TypeError):
                continue
        return found

    def add_rule(self, rule: Rule) -> list[dict]:
        """Save a rule. Returns the rules before, for Undo."""
        before = list(self.settings.get("rules") or [])
        self.settings.set("rules", before + [_rule_dict(rule)])
        self._learned()
        return before

    def remove_rule(self, rule: Rule) -> list[dict]:
        before = list(self.settings.get("rules") or [])
        self.settings.set("rules", [r for r in before if Rule(r.get("word") or "", r["destination"], r.get("ext") or "",
                                                              r.get("shape") or "", label=r.get("label") or "").key
                                    != rule.key])
        return before

    def restore_rules(self, before: list) -> None:
        """Set the rules (dictionaries as saved, or Rule objects)."""
        self.settings.set("rules", [r if isinstance(r, dict) else _rule_dict(r) for r in before])

    # ---------------------------------------------------------------- groups of unsure files
    def file_groups(self, plan: Plan) -> list[FileGroup]:
        """Files SortZen couldn't place, in groups that can be placed in one go."""
        corrected = {path_key(p) for p in self.corrections()}
        unsure = [r for r in self._ai_unsure(plan) if path_key(r.path) not in corrected]
        by_path = {s.path: s for s in plan.files}
        return find_groups([by_path[r.path] for r in unsure if r.path in by_path and not by_path[r.path].topic])

    def place_group(self, group: FileGroup, destination: str, make_rule: bool = False) -> dict:
        """Send every file of a group to one folder (and, when asked, files like them in future plans).

        Returns what to restore for Undo: {"corrections": ..., "rules": ...}."""
        destination = os.path.abspath(destination)
        before = {"corrections": self.correct(group.paths, destination), "rules": None}
        self.note_destination(destination)
        if make_rule:
            before["rules"] = self.add_rule(group.rule(destination))
        return before

    def undo_place_group(self, before: dict) -> None:
        self.restore_corrections(before["corrections"])
        if before["rules"] is not None:
            self.restore_rules(before["rules"])

    def decline_rule(self, rule: Rule) -> None:
        """Never suggest this rule again."""
        self.settings.set("declined_rules", list(self.settings.get("declined_rules") or []) + [rule.key])

    def describe_rule(self, rule: Rule) -> str:
        return rule.describe(self.display)

    def suggest_rule(self, plan: Plan, destination: str) -> RuleSuggestion | None:
        """A rule for the files users have sent to this folder, when one would also place other files."""
        target = path_key(destination)
        corrections = self.corrections()
        examples = [os.path.basename(p) for p, d in corrections.items() if d and path_key(d) == target]
        corrected = {path_key(p) for p in corrections}
        others = [(s.path, s.destination, s.percent) for s in plan.files
                  if path_key(s.path) not in corrected and s.path in self._records
                  and self._records[s.path].role == "source" and not self.is_left_out(s.path)]
        declined = set(self.settings.get("declined_rules") or [])
        if self.labels():
            from ..engine.labeling import suggest_label_rule

            labelled = [self.labels_of(p) for p, d in corrections.items() if d and path_key(d) == target]
            found = suggest_label_rule(labelled, os.path.abspath(destination),
                                       [(*o, self.labels_of(o[0])) for o in others], self.rules(), declined)
            if found:
                return found
        return suggest_rule(examples, os.path.abspath(destination), others, self.rules(), declined)

    def _apply_meaning(self, plan: Plan) -> None:
        """Meaning as evidence for unsure files (skipped when the meaning model isn't installed)."""
        from .. import meaning as meaning_model
        from ..engine.features import stem_of
        from ..engine.meaning import apply_meaning, profiles

        model = meaning_model.load() if self._embedder is None else self._embedder
        if model is None:
            return
        np = model.np
        records = list(self._records.values())
        valid = self._ai_valid(plan)
        texts = [_meaning_text(r, stem_of) for r in records]
        file_vectors = model.embed(texts)
        member_rows: dict[str, list[int]] = {}
        for row, r in enumerate(records):
            folder = os.path.dirname(r.path)
            if (r.role == "destination" or valid(folder)) and not self.is_left_out(folder):
                member_rows.setdefault(folder, []).append(row)
        notes = self.folder_notes()
        folders = sorted(set(member_rows) | {f for f in notes if os.path.isdir(f) and valid(f)})
        if not folders:
            return
        names = model.embed([self.display(f).replace("/", " ") for f in folders])
        note_keys = {path_key(k): v for k, v in notes.items()}
        note_vectors = model.embed([note_keys.get(path_key(f), "") for f in folders])
        matrix = profiles(np, folders, member_rows, file_vectors, names, note_vectors)
        unsure = {r.path: file_vectors[row] for row, r in enumerate(records) if r.role == "source"}
        apply_meaning(np, plan, unsure, folders, matrix, self.display)

    def _apply_rules(self, plan: Plan) -> None:
        rules = self.rules()
        if rules:                   # a rule's folder is made when files first move into it
            apply_rules(plan, rules, lambda f: not self.is_left_out(f)
                        and not any(is_queue_folder(part) for part in f.split(os.sep)),
                        lambda p: p in self._records and self._records[p].role == "source"
                        and not self.is_left_out(p), self.display, self.labels_of)

    # ---------------------------------------------------------------- renaming folders
    def rename_folder(self, plan: Plan | None, folder: str, new_name: str, emit=None) -> RunResult | None:
        """Give a folder a new name.

        A folder SortZen only plans to make is renamed in the plan (returns None). A folder that exists
        is renamed on disk, logged like a move so Undo puts the old name back (returns the run). Every
        choice, rule and recent folder that points into it follows the new name.
        """
        folder = os.path.abspath(folder)
        new_name = (new_name or "").strip().rstrip(". ")
        if not new_name:
            raise FolderError("Type a name for the folder.")
        bad = sorted(set(new_name) & set('\\/:*?"<>|'))
        if bad:
            raise FolderError(f"Folder names can't contain {' '.join(bad)}")
        if new_name == os.path.basename(folder):
            raise FolderError("That is already its name.")
        target = os.path.join(os.path.dirname(folder), new_name)
        if os.path.lexists(target) and path_key(target) != path_key(folder):
            raise FolderError(f"There is already a folder called “{new_name}” there.")
        if path_key(folder) in {path_key(r) for r in self.all_roots()} and not os.path.isdir(folder):
            raise FolderError("That folder can't be found.")
        if not os.path.isdir(folder):
            names = {k: v for k, v in (self.settings.get("folder_names") or {}).items()}
            original = next((k for k, v in names.items() if path_key(v) == path_key(folder)), folder)
            names[original] = target
            self.settings.set("folder_names", names)
            self._remap_paths(folder, target)
            if plan is not None:
                rename_planned(plan, {folder: target})
            return None
        result = self.mover.run([MoveRequest(folder, os.path.dirname(folder), new_name)], (), emit, kind="rename")
        if result.failed:
            raise FolderError(f"The folder couldn't be renamed: {result.failed[0][1]}")
        self._carry_index(result)
        self._remap_paths(folder, target)
        return result

    def _remap_paths(self, old: str, new: str) -> None:
        """Choices, rules, recent folders and added folders that point into a renamed folder follow it."""
        mapping = {old: new}
        data = self.settings.data
        for key in ("corrections", "rules", "recent_destinations", "sources", "destinations", "left_out",
                    "folder_notes", "catalog", "labels", "pairs", "file_notes"):
            if key in data:
                data[key] = profile.remap(data[key], mapping)
        self.settings.save()

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
        self.scanner.ocr = ocr.recognizer() if self.option("read_scans") else None
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
                          not_destinations=self.catalog_hidden(), answers=self.answers(),
                          corrections=self.corrections(), left_out=self.left_out(), notes=self.folder_notes())
        plan = planner.plan()
        plan.copies = find_copies(records, plan, self.is_left_out)
        self._records = {r.path: r for r in records}
        names = self.settings.get("folder_names") or {}
        if names:
            rename_planned(plan, {k: v for k, v in names.items() if not os.path.isdir(k)})
        merged = self.catalog_edits().get("merged") or {}
        if merged:                  # files for a merged category go to the one it was merged into
            rename_planned(plan, merged)
        self.guess_labels(emit)
        self._apply_rules(plan)
        if self.option("meaning"):
            emit(Status("Matching by meaning", f"{len(records):,} files"))
            self._apply_meaning(plan)
        self._apply_ai(plan)
        self._apply_labels(plan)
        self._apply_file_notes(plan)
        self._apply_pairs(plan)
        self.settings.set("learned_since_plan", 0)
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

    def resolve_folder(self, text: str, plan: Plan | None = None) -> str | None:
        """The folder meant by what users typed: a full path, a folder as shown ("Sorted/Work/Payroll"), or a
        new folder's name (made in the first destination folder, or the first folder being tidied)."""
        text = (text or "").strip().strip('"').replace("\\", "/").rstrip("/")
        if not text:
            return None
        if os.path.isabs(text) or re.match(r"^[A-Za-z]:", text):
            return os.path.abspath(text)
        for root in self.all_roots():
            name = os.path.basename(root)
            if text == name or text.startswith(name + "/"):
                return os.path.normpath(os.path.join(os.path.dirname(root), text))
        homes = self.destination_folders() + [f["path"] for f in self.source_folders() if f["mode"] == TIDY]
        if not homes:
            return None
        return os.path.normpath(os.path.join(homes[0], text))

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

    # ---------------------------------------------------------------- AI step
    def _ai_valid(self, plan: Plan):
        roots = [path_key(r) for r in self.destination_folders()] + \
                [path_key(f["path"]) for f in self.source_folders() if f["mode"] == TIDY]
        new = {path_key(f) for f in plan.new_folders}
        seen: dict[str, bool] = {}

        def valid(folder: str) -> bool:
            key = path_key(folder)
            if key not in seen:
                seen[key] = (key in new or os.path.isdir(folder)) and any(_inside(key, r) for r in roots) \
                    and not self.is_left_out(folder) and not any(is_queue_folder(p) for p in folder.split(os.sep))
            return seen[key]

        return valid

    def _apply_ai(self, plan: Plan) -> None:
        """Remembered AI answers count as evidence in every plan, at no cost."""
        keys = {s.path: answer_key(self._records[s.path]) for s in plan.files if s.path in self._records}
        if not keys:
            return
        found = self.ai_answers.get_many(list(set(keys.values())))
        by_path = {path: found[key] for path, key in keys.items() if key in found}
        if by_path:
            apply_ai(plan, by_path, self._ai_valid(plan), {k: v.name for k, v in SERVICES.items()})

    def _ai_unsure(self, plan: Plan) -> list:
        """Files from the folders being sorted that SortZen couldn't settle by itself."""
        level = self.autonomy()
        corrections = {path_key(p) for p in self.corrections()}
        unsure = []
        for s in plan.files:
            record = self._records.get(s.path)
            if record is None or record.role != "source" or record.ext in GOOGLE_LINKS or s.action == STAY_ACTION:
                continue
            if (s.destination is None or s.percent < level) and path_key(s.path) not in corrections \
                    and not self.is_left_out(s.path):
                unsure.append(record)
        return unsure

    def _ai_request(self, plan: Plan) -> tuple[list[AIFolder], list[AIFile], int]:
        """The folders and files to send, as privacy settings allow, and how many already have an answer."""
        valid = self._ai_valid(plan)
        files_in: dict[str, list[str]] = {}
        for r in self._records.values():
            folder = os.path.dirname(r.path)
            if r.role == "destination" or valid(folder):
                files_in.setdefault(folder, []).append(r.name)
        folders = [f for f in self.destination_choices(plan) if valid(f)]
        folders.sort(key=lambda f: -len(files_in.get(f, [])))
        folders = sorted(folders[:AI_MAX_FOLDERS], key=lambda f: self.display(f).lower())
        notes = {path_key(k): v for k, v in self.folder_notes().items()}
        listed = [AIFolder(f, self.display(f), [privacy.scrub_name(n) for n in sorted(files_in.get(f, []))[:AI_EXAMPLES]],
                           notes.get(path_key(f), "")) for f in folders]
        unsure = self._ai_unsure(plan)
        remembered = self.ai_answers.get_many([answer_key(r) for r in unsure])
        sending = self.ai_value("ai_privacy") == privacy.BEGINNING
        name_folders, name_words = self.ai_value("ai_name_only_folders"), self.ai_value("ai_name_only_words")
        files = []
        for r in unsure:
            key = answer_key(r)
            if key in remembered:
                continue
            content = sending and not r.cloud_only and not privacy.name_only(r.path, name_folders, name_words)
            text = privacy.beginning(r.text) if content and r.text else ""
            preview = bool(content and r.kind == "image" and self.ai_value("ai_previews"))
            files.append(AIFile(key, r.path, privacy.scrub_name(r.name), self.display(os.path.dirname(r.path)),
                                text, preview))
        return listed, files, len(unsure) - len(files)

    def _ai_cap(self) -> float:
        return max(0.01, float(self.ai_value("ai_cap_per_1000")) * max(1, len(self._records)) / 1000)

    def _sorter(self, provider=None) -> AISorter:
        return AISorter(provider or self.provider(), self.ai_service(), self.model(), self.ai_value("house_rules"))

    def ai_estimate(self, plan: Plan, **trying) -> dict:
        """What asking the AI service would cost and send, before anything is sent.

        ``trying`` holds settings being chosen on screen (e.g. ai_privacy="beginning"); they are used
        for this estimate only and not saved.
        """
        saved = {k: self.settings.data.get(k) for k in trying}
        self.settings.data.update(trying)
        try:
            return self._ai_estimate(plan)
        finally:
            for k, v in saved.items():
                if v is None:
                    self.settings.data.pop(k, None)
                else:
                    self.settings.data[k] = v

    def _ai_estimate(self, plan: Plan) -> dict:
        folders, files, remembered = self._ai_request(plan)
        service = SERVICES[self.ai_service()]
        estimate = AISorter(None, service.key, self.model(), self.ai_value("house_rules")).estimate(folders, files)
        return {"files": len(files), "remembered": remembered, "folders": len(folders),
                "with_content": sum(1 for f in files if f.has_content), "cost": estimate, "cap": self._ai_cap(),
                "service": service.name, "model": self.model(), "local": service.key == "ollama",
                "privacy": self.ai_value("ai_privacy"), "spent_this_month": self.ai_spent()}

    def ask_ai(self, plan: Plan, emit=None, token=None, provider=None) -> AIRun:
        """Ask the AI service about the unsure files; answers are remembered as they arrive."""
        folders, files, _ = self._ai_request(plan)
        if not files:
            return AIRun()
        try:
            sorter = self._sorter(provider)
        except Exception as exc:
            raise AIProblem(explain(exc, SERVICES[self.ai_service()].name, self.model())) from exc
        _, run = sorter.run(folders, files, self._ai_cap(), emit, token, on_answers=self.ai_answers.save)
        self._add_spent(run.spent)
        return run

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
        if any(r["log"] == log and r["kind"] == "placed" for r in self.move_runs()):
            gone = {path_key(moved_from) for moved_from, _ in result.moves}     # forget the choices it made
            current = self.corrections()
            self.settings.set("corrections", {k: v for k, v in current.items() if path_key(k) not in gone})
            for back_from, back_to in result.moves:
                if os.path.isdir(back_to):
                    self._remap_paths(back_from, back_to)
        if any(r["log"] == log and r["kind"] == "rename" for r in self.move_runs()):
            for back_from, back_to in result.moves:
                self._remap_paths(back_from, back_to)
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

    # ---------------------------------------------------------------- profiles
    def save_profile(self, path: str, include_keys: bool = False) -> None:
        """Save folders, choices, answers and settings to a profile file (API keys only when asked)."""
        keys = {k: self.api_key(k) for k, info in SERVICES.items() if info.needs_key and self.api_key(k)} \
            if include_keys else None
        profile.write(path, profile.make(self.settings.data, keys))

    def read_profile(self, path: str) -> dict:
        return profile.read(path)

    @staticmethod
    def missing_folders(loaded: dict) -> list[str]:
        """The profile's added folders that don't exist on this PC."""
        return [f for f in profile.folders(loaded) if not os.path.isdir(f)]

    def load_profile(self, loaded: dict, moved: dict[str, str] | None = None, dropped: list[str] = ()) -> dict:
        """Use a profile's settings in place of the current ones. Returns the current ones, for Undo.

        ``moved`` maps folders that are somewhere else on this PC to their new place; ``dropped``
        folders are left out of the loaded profile.
        """
        before = self.settings_snapshot()
        settings = profile.without(loaded["settings"], list(dropped))
        if moved:
            settings = profile.remap(settings, moved)
        for key in profile.MACHINE_ONLY:
            if key in self.settings.data:
                settings[key] = self.settings.data[key]
        self.settings.data = settings
        self.settings.save()
        for service_key, key in (loaded.get("keys") or {}).items():
            if service_key in SERVICES and key:
                self.save_api_key(key, service_key)
        return before

    def settings_snapshot(self) -> dict:
        return json.loads(json.dumps(self.settings.data))

    def restore_settings(self, snapshot: dict) -> None:
        self.settings.data = json.loads(json.dumps(snapshot))
        self.settings.save()

    # ---------------------------------------------------------------- help
    def log_path(self):
        return self.paths.logs_dir / "sortzen.log"

    def diagnostics(self) -> str:
        """Details for reporting a problem, with no file or folder names in them."""
        import platform

        try:
            from PySide6 import __version__ as qt_version
        except ImportError:
            qt_version = "not installed"
        from .. import __version__

        sources = self.source_folders()
        modes = ", ".join(sorted({f["mode"] for f in sources})) or "none"
        lines = [f"SortZen {__version__}", f"Windows/system: {platform.platform()}",
                 f"Python {platform.python_version()}, PySide6 {qt_version}",
                 f"Folders: {len(sources)} to sort ({modes}), {len(self.destination_folders())} destinations, "
                 f"{len(self.left_out())} left out",
                 f"Remembered: {len(self.answers())} answers, {len(self.corrections())} chosen destinations, "
                 f"{len(self.move_runs())} moves logged",
                 f"Autonomy {self.autonomy()}%, ask about everything: {self.ask_everything()}",
                 "Options: " + ", ".join(f"{k}={self.option(k)}" for k in DEFAULTS),
                 f"AI: {'on' if self.ai_value('ai_enabled') else 'off'}, {SERVICES[self.ai_service()].name}, "
                 f"model {self.model()}, key saved: {self.has_api_key()}, privacy: {self.ai_value('ai_privacy')}, "
                 f"previews: {self.ai_value('ai_previews')}, spent this month: ${self.ai_spent():.4f}",
                 f"Speeds (files per second): {self.speeds()}"]
        errors = []
        try:
            for line in self.log_path().read_text(encoding="utf-8", errors="replace").splitlines():
                if " ERROR " in line or " WARNING " in line:
                    errors.append(_no_paths(line))
        except OSError:
            pass
        lines.append("Recent problems:" if errors else "Recent problems: none")
        lines += ["  " + e for e in errors[-10:]]
        return "\n".join(lines)

    # ---------------------------------------------------------------- background jobs
    def run_job(self, name: str, work: Callable, on_event: Callable):
        return self.jobs.start(name, work, on_event)

    def stop_job(self) -> None:
        self.jobs.cancel()


_PATHS = re.compile(r"([A-Za-z]:[\\/]|\\\\|/(home|Users|tmp|mnt|media|root)/)[^\"'\n]*?(?=[\"'\n,)]|$|\s{2})")


def _meaning_text(record, stem_of) -> str:
    """What a file is about, for matching by meaning: its name's words, title and the start of its text."""
    name = re.sub(r"[_\-.]+", " ", stem_of(record.name))
    title = str(record.details.get("title") or "")
    return f"{name}. {title}. {record.text[:600]}"


def _rule_dict(rule: Rule) -> dict:
    found = {"word": rule.word, "ext": rule.ext, "destination": rule.destination}
    if rule.shape:
        found.update(shape=rule.shape, example=rule.example)
    if rule.label:
        found["label"] = rule.label
    return found


def _no_paths(text: str) -> str:
    return _PATHS.sub("<path>", text)


def _inside(key: str, root: str) -> bool:
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


def _outermost(folders) -> list:
    keys = {path_key(f): f for f in folders}

    def inside(key, other):
        return key.startswith(other.rstrip(os.sep) + os.sep)

    return [f for k, f in keys.items() if not any(inside(k, other) for other in keys if other != k)]
