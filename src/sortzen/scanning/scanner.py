"""Scan an added folder: list its files, read them on the PC, remember the results.

Never sorted: hidden and system files, Windows housekeeping files, Office lock files,
downloads still in progress, links to other folders, and Windows or program folders.
OneDrive cloud-only files are listed by name and details only, because reading them
would download them.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..repositories.file_index import FileIndex, path_key
from ..tasks import Progress, Status
from .file_types import SKIPPED_FOLDER_NAMES, is_queue_folder, kind_of, skip_reason
from .fingerprint import fingerprint
from .readers import read_contents
from .records import FileRecord, ScanSummary

HIDDEN, SYSTEM, REPARSE_POINT = 0x2, 0x4, 0x400
CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000      # offline, recall on open, recall on data access
COMMIT_EVERY = 200
PROGRESS_EVERY = 25
LISTING_EVERY = 500


@dataclass
class FolderCount:
    root: str
    files: int
    new_files: int                          # not read before, or changed since
    size: int                               # bytes
    biggest: list[tuple[str, int]]          # the largest files, (path, bytes)
    busiest: list[tuple[str, int]]          # subfolders holding the most files, (name, files)
    google_drive: bool                      # on Google Drive for desktop, contents not read
    listing: tuple = field(default=(), repr=False)
    tree: dict = field(default_factory=dict, repr=False)   # folder -> (files, bytes, new files), all levels


class ProtectedFolderError(ValueError):
    pass


def protected_roots() -> list[str]:
    names = ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
    return [path_key(os.environ[n]) for n in names if os.environ.get(n)]


def _inside(key: str, roots) -> bool:
    return any(key == r or key.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def on_google_drive(path: str) -> bool:
    """Whether a folder is on the drive Google Drive for desktop creates (labelled "Google Drive").

    Reading a file there can make Google Drive download it, so its files are treated like
    cloud-only files unless reading them is allowed.
    """
    if os.name != "nt":
        return False
    import ctypes

    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return False
    label = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(drive + "\\", label, 261, None, None, None, None, 0)
    return bool(ok) and label.value.lower().startswith("google drive")


class Scanner:
    def __init__(self, index: FileIndex, protected: list[str] | None = None, read_google_drive: bool = False):
        self.index = index
        self.protected = protected_roots() if protected is None else [path_key(p) for p in protected]
        self.read_google_drive = read_google_drive
        self.pause = 0.0            # seconds to rest after each file read ("Be gentle with my computer")

    def scan(self, root, role: str, recursive: bool, exclude=(), emit=None, token=None,
             listing=None, names_only=()) -> ScanSummary:
        """Read the folder's files (unchanged ones come from the index). ``listing`` reuses one from listing()."""
        root = Path(os.path.abspath(str(root)))
        if not root.is_dir():
            raise FileNotFoundError(f"The folder {root} can't be found.")
        root_key = path_key(root)
        if _inside(root_key, self.protected):
            raise ProtectedFolderError(f"SortZen doesn't sort Windows or program folders ({root}).")
        emit = emit or (lambda event: None)
        summary = ScanSummary(str(root), role)
        excluded = [path_key(p) for p in exclude]
        names_keys = [path_key(n) for n in names_only]

        streamed = not self.read_google_drive and on_google_drive(str(root))
        if listing is None:
            emit(Status("Listing files", root.name))
            listing = self.listing(root, recursive, exclude, emit)
        entries, skipped = listing
        summary.skipped = dict(skipped)

        total = len(entries)
        seen: set[str] = set()
        with self.index.session() as conn:
            known = self.index.known(conn, root_key)
            for done, (path, st) in enumerate(entries, start=1):
                if token is not None and token.cancelled:
                    summary.cancelled = True
                    break
                key = path_key(path)
                cloud = streamed or bool(getattr(st, "st_file_attributes", 0) & CLOUD_ONLY)
                previous = known.get(key)
                names = bool(names_keys) and any(_inside(key, n) for n in names_keys)
                if (previous and previous.size == st.st_size and previous.modified_ns == st.st_mtime_ns
                        and previous.cloud_only == cloud and previous.role == role
                        and (names or not previous.details.get("names_only"))):
                    record = previous
                    summary.remembered += 1
                else:
                    record = self._read(path, str(root), role, st, cloud, contents=not names)
                    if record is None:
                        summary.skip("in use")
                        continue
                    self.index.save(conn, record)
                    summary.read += 1
                    if self.pause and not cloud:
                        time.sleep(self.pause)
                    if summary.read % COMMIT_EVERY == 0:
                        conn.commit()
                seen.add(key)
                summary.files.append(record)
                if done % PROGRESS_EVERY == 0 or done == total:
                    emit(Progress(done, total))
            if not summary.cancelled:
                self.index.forget_missing(conn, root_key, seen)
        summary.files.sort(key=lambda r: r.path.lower())
        return summary

    def listing(self, root, recursive: bool, exclude=(), emit=None):
        """The folder's sortable files and why others were skipped, without opening any file."""
        summary = ScanSummary(str(root), "")
        entries: list[tuple[str, os.stat_result]] = []
        self._walk(str(root), recursive, [path_key(p) for p in exclude], entries, summary, emit, Path(root).name)
        return entries, summary.skipped

    def count(self, root, recursive: bool, exclude=()) -> FolderCount:
        """How many files a folder holds, how many are new since the last scan, and the biggest ones."""
        root = Path(os.path.abspath(str(root)))
        entries, skipped = self.listing(root, recursive, exclude)
        with self.index.session() as conn:
            known = self.index.known(conn, path_key(root))
        new = 0
        per_subfolder: dict[str, int] = {}
        tree: dict[str, list[int]] = {}
        root_text = str(root)
        for path, st in entries:
            previous = known.get(path_key(path))
            fresh = not previous or previous.size != st.st_size or previous.modified_ns != st.st_mtime_ns
            new += fresh
            rel = os.path.relpath(path, root).split(os.sep)
            if len(rel) > 1:
                per_subfolder[rel[0]] = per_subfolder.get(rel[0], 0) + 1
            folder = os.path.dirname(path)
            while True:
                counts = tree.setdefault(folder, [0, 0, 0])
                counts[0] += 1
                counts[1] += st.st_size
                counts[2] += fresh
                if folder == root_text or len(folder) <= len(root_text):
                    break
                folder = os.path.dirname(folder)
        biggest = sorted(((p, st.st_size) for p, st in entries), key=lambda x: -x[1])[:20]
        return FolderCount(str(root), len(entries), new, sum(st.st_size for _, st in entries),
                           biggest, sorted(per_subfolder.items(), key=lambda x: -x[1])[:10],
                           not self.read_google_drive and on_google_drive(str(root)), (entries, skipped),
                           {k: tuple(v) for k, v in tree.items()})

    def _walk(self, folder: str, recursive: bool, excluded, entries, summary, emit=None, name="") -> None:
        try:
            listing = os.scandir(folder)
        except OSError:
            summary.skip("unreadable folder")
            return
        with listing:
            for entry in listing:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    summary.skip("unreadable")
                    continue
                attrs = getattr(st, "st_file_attributes", 0)
                if attrs & (HIDDEN | SYSTEM) or entry.name.startswith("."):
                    summary.skip("hidden")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    key = path_key(entry.path)
                    if (entry.name.lower() in SKIPPED_FOLDER_NAMES or is_queue_folder(entry.name) or attrs & REPARSE_POINT
                            or _inside(key, self.protected) or _inside(key, excluded)):
                        summary.skip("excluded folder")
                    elif recursive:
                        self._walk(entry.path, recursive, excluded, entries, summary, emit, name)
                    else:
                        summary.skip("subfolder")
                    continue
                if entry.is_symlink():
                    summary.skip("link")
                    continue
                name = entry.name
                reason = skip_reason(name, os.path.splitext(name)[1])
                if reason:
                    summary.skip(reason)
                    continue
                entries.append((entry.path, st))
                if emit and len(entries) % LISTING_EVERY == 0:
                    emit(Status("Listing files", f"{name}: {len(entries):,} found"))

    @staticmethod
    def _read(path: str, root: str, role: str, st, cloud: bool, contents: bool = True) -> FileRecord | None:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        record = FileRecord(path=path, root=path_key(root), role=role, name=name, ext=ext, kind=kind_of(ext),
                            size=st.st_size, modified_ns=st.st_mtime_ns, cloud_only=cloud)
        if cloud:
            return record
        if not contents:
            record.details = {"names_only": True}
            return record
        try:
            record.fingerprint = fingerprint(Path(path), st.st_size)
        except PermissionError:
            return None
        except OSError as exc:
            record.error = f"Couldn't read the file: {exc}"[:300]
            return record
        try:
            record.details, record.text = read_contents(Path(path), record.kind, ext, st.st_size)
        except Exception as exc:  # damaged or unusual file: sorted by name and details
            record.error = f"Couldn't read the contents ({type(exc).__name__}: {exc})"[:300]
        return record
