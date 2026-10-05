"""What helps users recognise a file at a glance: when it arrived on this PC (downloaded, copied or saved
there), the site it was downloaded from, its size and type, its title, pages, camera, and the start of
its text. Everything comes from this PC; nothing is sent anywhere.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..scanning.file_types import kind_of
from .plan_view import KIND_NAMES

SNIPPET = 160               # characters of the file's text shown


@dataclass
class FileFacts:
    path: str
    added: float = 0.0              # when it arrived on this PC (created here), seconds
    modified: float = 0.0           # last saved
    size: int = 0
    kind: str = ""                  # "PDF", "Picture" ...
    site: str = ""                  # the site it was downloaded from ("example.org"), when Windows noted it
    title: str = ""                 # a document's own title, when it differs from the name
    extra: list[str] = field(default_factory=list)      # "2 pages", "Camera: Pixel 7", "Taken Jun 2 2024"
    snippet: str = ""               # the start of its text

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


def day(seconds: float) -> str:
    return time.strftime("%b %d %Y", time.localtime(seconds)) if seconds else ""


def _added(stat) -> float:
    """When a file was made in its folder: on Windows, when it was downloaded, copied or saved there."""
    born = getattr(stat, "st_birthtime", None)
    if born:
        return float(born)
    if sys.platform.startswith("win"):
        return float(stat.st_ctime)                 # creation time on Windows
    return float(stat.st_mtime)


def download_site(path: str) -> str:
    """The site a downloaded file came from, as Windows noted it beside the file (its "Zone.Identifier")."""
    if not sys.platform.startswith("win"):
        return ""
    try:
        with open(path + ":Zone.Identifier", encoding="utf-8", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return ""
    for key in ("ReferrerUrl", "HostUrl"):
        found = re.search(rf"^{key}=(.+)$", text, re.MULTILINE)
        if found:
            host = urlparse(found.group(1).strip()).hostname or ""
            if host and host not in ("localhost",):
                return host.removeprefix("www.")
    return ""


def _photo_day(text: str) -> str:
    """A photo's date as cameras write it ("2024:06:02 14:31:07") as "Jun 02 2024"."""
    try:
        return time.strftime("%b %d %Y", time.strptime(text[:10], "%Y:%m:%d"))
    except ValueError:
        return text[:10]


def facts_for(path: str, record=None) -> FileFacts:
    found = FileFacts(path)
    try:
        stat = os.stat(path)
    except OSError:
        return found
    found.added, found.modified, found.size = _added(stat), float(stat.st_mtime), stat.st_size
    ext = os.path.splitext(path)[1].lower()
    found.kind = KIND_NAMES.get(kind_of(ext), ext.lstrip(".").upper() or "File")
    found.site = download_site(path)
    details = (record.details if record is not None else None) or {}
    title = str(details.get("title") or "").strip()
    stem = os.path.splitext(os.path.basename(path))[0]
    if title and title.lower() != stem.lower():
        found.title = title[:120]
    for key, word in (("pages", "page"), ("slides", "slide"), ("sheets", "sheet")):
        n = details.get(key)
        if isinstance(n, int) and n > 0:
            found.extra.append(f"{n} {word}{'s' if n != 1 else ''}")
    if details.get("author"):
        found.extra.append(f"by {str(details['author'])[:60]}")
    if details.get("camera"):
        found.extra.append(f"camera: {str(details['camera'])[:40]}")
    if details.get("taken"):
        found.extra.append(f"taken {_photo_day(str(details['taken']))}")
    text = " ".join((getattr(record, "text", "") or "").split())
    if text:
        found.snippet = text[:SNIPPET] + ("…" if len(text) > SNIPPET else "")
    return found
