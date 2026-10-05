"""Files that go with another file: subtitles with their movie, a cue sheet with its album, a photo's
sidecar file. They never travel alone: wherever the main file goes, they go too.
"""
from __future__ import annotations

import os

from ..scanning.file_types import kind_of
from .plan import Plan, Reason

COMPANION_EXTS = {                  # companion extension -> the kind of file it goes with
    ".srt": "video", ".sub": "video", ".idx": "video", ".ass": "video", ".ssa": "video", ".vtt": "video",
    ".smi": "video", ".nfo": "video", ".thm": "video",
    ".cue": "audio", ".lrc": "audio",
    ".xmp": "image", ".aae": "image",
}
ARTWORK_NAMES = {"poster", "folder", "fanart", "cover", "banner", "thumb", "landscape", "clearlogo", "backdrop",
                 "disc", "albumart", "front"}
EXTRA_WORDS = ("sample", "trailer")          # short clips beside a movie, not the movie itself


def _stem(name: str) -> str:
    return os.path.splitext(name)[0].lower()


def is_companion(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    return ext in COMPANION_EXTS or (kind_of(ext) == "image" and _stem(name).split(".")[0] in ARTWORK_NAMES)


def find_companions(paths: list[str]) -> dict[str, str]:
    """Companion file -> the main file it goes with, for files in the same folder."""
    by_folder: dict[str, list[str]] = {}
    for path in paths:
        by_folder.setdefault(os.path.dirname(path), []).append(path)
    found = {}
    for folder, files in by_folder.items():
        names = {p: os.path.basename(p) for p in files}
        for path, name in names.items():
            if not is_companion(name):
                continue
            ext = os.path.splitext(name)[1].lower()
            wanted = COMPANION_EXTS.get(ext) or "video"
            mains = [p for p, n in names.items() if p != path and not is_companion(n)
                     and kind_of(os.path.splitext(n)[1].lower()) in ({wanted} if ext in COMPANION_EXTS
                                                                     else {"video", "audio"})]
            if not mains:
                continue
            stem = _stem(name)
            named = [m for m in mains if stem.startswith(_stem(names[m]))]
            if named:
                found[path] = max(named, key=lambda m: len(_stem(names[m])))
            elif wanted == "image":
                continue                        # a photo's sidecar belongs to the photo with its name only
            else:
                movies = [m for m in mains if not any(w in _stem(names[m]) for w in EXTRA_WORDS)]
                if len(movies) == 1:
                    found[path] = movies[0]
    return found


def follow_companions(plan: Plan, companions: dict[str, str], keep=lambda path: False) -> int:
    """Companions go wherever their main file goes. ``keep(path)``: users chose this companion's folder
    themselves. Returns how many followed."""
    by_path = {os.path.normcase(s.path): s for s in plan.files}
    moved = 0
    for path, main in companions.items():
        s, m = by_path.get(os.path.normcase(path)), by_path.get(os.path.normcase(main))
        if s is None or m is None or keep(s.path):
            continue
        s.destination, s.percent, s.new_folder, s.runner_up = m.destination, m.percent, m.new_folder, None
        s.reasons = [Reason(True, f"Goes with “{os.path.basename(main)}”")]
        moved += 1
    return moved
