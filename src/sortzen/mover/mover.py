"""Moves confirmed files and folders, never overwriting, and logs every step so a run can be undone.

- A name already taken at the destination gets " (2)", " (3)" … added.
- On the same drive a move is a rename. To another drive the file (or folder) is copied
  under a temporary name, every copied file is checked against the original byte for byte
  (by hash), the copy gets its real name, and only then is the original removed.
- Google link files never leave their drive (moving one out disconnects it).
- Each step is appended to the run log as it happens (one JSON line per step), so even an
  interrupted run can be undone.
- Folders emptied by "sort the inside" are removed when nothing is left in them; Undo
  recreates them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..scanning.file_types import GOOGLE_LINKS
from ..tasks import Progress, Status

PART = ".sortzen-part"
NUMBERED = re.compile(r"^(.*?) \((\d+)\)$")          # "name (2)"


@dataclass(frozen=True)
class MoveRequest:
    path: str                   # the file or folder to move
    destination: str            # the folder it goes into (created if missing)
    name: str = ""              # the name it gets there; its own name when empty


@dataclass
class RunResult:
    log: str                                            # the run log's path
    moved: int = 0
    renamed: list[tuple[str, str]] = field(default_factory=list)    # (original name, new name)
    failed: list[tuple[str, str]] = field(default_factory=list)     # (path, reason)
    removed_folders: int = 0
    cancelled: bool = False
    moves: list[tuple[str, str]] = field(default_factory=list)      # (from, to) full paths


def _hash(path: str) -> str:
    digest = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def same_contents(a: str, b: str) -> bool:
    """True when two files are the same byte for byte."""
    return os.path.getsize(a) == os.path.getsize(b) and _hash(a) == _hash(b)


def free_name(folder: str, name: str, is_folder: bool = False) -> str:
    """The name itself if nothing has it, otherwise "name (2).ext", "name (3).ext" …

    A name that already ends in a number counts on from it: "name (2).ext" becomes "name (3).ext".
    """
    stem, ext = (name, "") if is_folder else os.path.splitext(name)
    numbered = NUMBERED.match(stem)
    stem, n = (numbered.group(1), int(numbered.group(2)) + 1) if numbered else (stem, 2)
    candidate = name
    while os.path.lexists(os.path.join(folder, candidate)) or os.path.lexists(os.path.join(folder, candidate + PART)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


def _drive(path: str) -> int:
    probe = path
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return os.stat(probe).st_dev


class _Log:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8")

    def write(self, **step) -> None:
        step["time"] = time.time()
        self.file.write(json.dumps(step, ensure_ascii=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self) -> None:
        self.file.close()


class Mover:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)

    # ---------------------------------------------------------------- moving
    def run(self, requests: list[MoveRequest], remove_if_empty: list[str] = (), emit=None, token=None,
            kind: str = "move") -> RunResult:
        emit = emit or (lambda event: None)
        name = time.strftime("%Y-%m-%d %H-%M-%S")
        log_path, n = self.runs_dir / f"{name} {kind}.jsonl", 2
        while log_path.exists():
            log_path, n = self.runs_dir / f"{name} {kind} {n}.jsonl", n + 1
        log = _Log(log_path)
        log.write(step="start", kind=kind, items=len(requests))
        result = RunResult(str(log_path))
        try:
            for done, request in enumerate(requests, start=1):
                if token is not None and token.cancelled:
                    result.cancelled = True
                    break
                emit(Status("Moving", os.path.basename(request.path)))
                try:
                    target = self._move_one(request, log)
                    result.moved += 1
                    result.moves.append((os.path.abspath(request.path), target))
                    if os.path.basename(target) != os.path.basename(request.path):
                        result.renamed.append((os.path.basename(request.path), os.path.basename(target)))
                except (OSError, ValueError) as exc:
                    result.failed.append((request.path, _plain(exc)))
                    log.write(step="failed", path=request.path, reason=_plain(exc))
                emit(Progress(done, len(requests)))
            if not result.cancelled:
                for folder in sorted(remove_if_empty, key=len, reverse=True):
                    result.removed_folders += self._remove_empty(folder, log)
        finally:
            log.write(step="end", moved=result.moved, failed=len(result.failed))
            log.close()
        return result

    def _move_one(self, request: MoveRequest, log: _Log) -> str:
        source = os.path.abspath(request.path)
        if not os.path.lexists(source):
            raise FileNotFoundError(f"“{os.path.basename(source)}” is no longer there")
        destination = os.path.abspath(request.destination)
        if os.path.normcase(destination).startswith(os.path.normcase(source.rstrip(os.sep) + os.sep)):
            raise ValueError("A folder can't be moved inside itself")
        same_drive = _drive(source) == _drive(destination)
        if os.path.splitext(source)[1].lower() in GOOGLE_LINKS and not same_drive:
            raise ValueError("Google link files only move within their own drive")
        self._make_folders(destination, log)
        target = os.path.join(destination, free_name(destination, request.name or os.path.basename(source),
                                                         os.path.isdir(source)))
        if same_drive:
            os.rename(source, target)
        else:
            self._copy_checked(source, target)
        log.write(step="move", source=source, target=target)
        return target

    def _make_folders(self, folder: str, log: _Log) -> None:
        missing = []
        while not os.path.isdir(folder):
            missing.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        for path in reversed(missing):
            os.mkdir(path)
            log.write(step="mkdir", path=path)

    @staticmethod
    def _copy_checked(source: str, target: str) -> None:
        """Copy to another drive, check every byte, then remove the original."""
        part = target + PART
        try:
            if os.path.isdir(source):
                shutil.copytree(source, part)
                for folder, _, files in os.walk(source):
                    for name in files:
                        original = os.path.join(folder, name)
                        copy = os.path.join(part, os.path.relpath(original, source))
                        if _hash(original) != _hash(copy):
                            raise OSError(f"The copy of “{name}” didn't match; the original was kept")
            else:
                shutil.copy2(source, part)
                if _hash(source) != _hash(part):
                    raise OSError("The copy didn't match; the original was kept")
            os.rename(part, target)
        except BaseException:
            if os.path.isdir(part):
                shutil.rmtree(part, ignore_errors=True)
            elif os.path.exists(part):
                os.remove(part)
            raise
        if os.path.isdir(source):
            shutil.rmtree(source)
        else:
            os.remove(source)

    @staticmethod
    def _remove_empty(folder: str, log: _Log) -> int:
        """Remove a folder (and empty folders inside it) when no files are left in it."""
        if not os.path.isdir(folder):
            return 0
        for _, _, files in os.walk(folder):
            if files:
                return 0
        removed = 0
        for path, dirs, _ in sorted(os.walk(folder), key=lambda w: len(w[0]), reverse=True):
            os.rmdir(path)
            log.write(step="rmdir", path=path)
            removed += 1
        return removed

    # ---------------------------------------------------------------- undo
    def runs(self) -> list[dict]:
        """Past runs, newest first: their log, kind, when, how many moved, and whether undone."""
        found = []
        for path in self.runs_dir.glob("*.jsonl"):
            steps = _read_log(path)
            start = next((s for s in steps if s.get("step") == "start"), {})
            moved = sum(1 for s in steps if s.get("step") == "move")
            found.append({"log": str(path), "kind": start.get("kind", "move"), "time": start.get("time", 0),
                          "moved": moved, "undone": any(s.get("step") == "undone" for s in steps)})
        found.sort(key=lambda r: (r["time"], r["log"]), reverse=True)
        return found

    def undo(self, log_path: str, emit=None) -> RunResult:
        """Put a run back: moves are reversed newest first, removed folders recreated, new folders removed."""
        emit = emit or (lambda event: None)
        steps = _read_log(Path(log_path))
        if any(s.get("step") == "undone" for s in steps):
            raise ValueError("This run has already been undone")
        log = _Log(Path(log_path))
        result = RunResult(log_path)
        todo = [s for s in steps if s.get("step") in ("move", "mkdir", "rmdir")]
        try:
            for done, step in enumerate(reversed(todo), start=1):
                try:
                    if step["step"] == "rmdir":
                        os.makedirs(step["path"], exist_ok=True)
                    elif step["step"] == "mkdir":
                        if os.path.isdir(step["path"]) and not os.listdir(step["path"]):
                            os.rmdir(step["path"])
                    else:
                        emit(Status("Putting back", os.path.basename(step["source"])))
                        back = Mover._move_one(self, MoveRequest(step["target"], os.path.dirname(step["source"]),
                                                                       os.path.basename(step["source"])),
                                               _NoLog())
                        result.moved += 1
                        result.moves.append((step["target"], back))
                        if os.path.basename(back) != os.path.basename(step["source"]):
                            result.renamed.append((os.path.basename(step["source"]), os.path.basename(back)))
                except (OSError, ValueError) as exc:
                    result.failed.append((step.get("target", step.get("path", "")), _plain(exc)))
                emit(Progress(done, len(todo)))
        finally:
            log.write(step="undone", moved=result.moved, failed=len(result.failed))
            log.close()
        return result


class _NoLog:
    def write(self, **step) -> None:
        pass


def _read_log(path: Path) -> list[dict]:
    steps = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                steps.append(json.loads(line))
            except ValueError:
                continue                    # a half-written last line after a crash
    except OSError:
        pass
    return steps


def _plain(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "It's open in another program, or SortZen isn't allowed to move it"
    if isinstance(exc, FileNotFoundError):
        return str(exc) if "no longer there" in str(exc) else "It's no longer there"
    return str(exc) or type(exc).__name__
