"""What a scan returns."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileRecord:
    path: str
    root: str               # the added folder this file was found under
    role: str               # "source" or "destination"
    name: str
    ext: str
    kind: str
    size: int
    modified_ns: int
    fingerprint: str | None = None      # None for cloud-only files
    cloud_only: bool = False
    details: dict = field(default_factory=dict)
    text: str = ""
    error: str = ""         # why the contents couldn't be read (damaged file), else ""


@dataclass
class ScanSummary:
    root: str
    role: str
    files: list[FileRecord] = field(default_factory=list)
    read: int = 0                       # files read this time
    remembered: int = 0                 # unchanged files taken from the last scan
    skipped: dict[str, int] = field(default_factory=dict)   # reason -> count
    cancelled: bool = False

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1
