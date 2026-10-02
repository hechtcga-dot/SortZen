"""Profiles: everything SortZen knows about how a user sorts, in one file (.szprofile) to save or load.

A profile holds the added folders, left-out items, answers, chosen destinations, autonomy,
options, AI service and privacy settings and house rules. Speeds and spending stay with the
PC. API keys are included only when users tick it. Folders that don't exist on another PC
can be pointed at their new place when the profile is loaded.
"""
from __future__ import annotations

import json
import os
import time

from .. import __version__

FORMAT = "sortzen-profile"
EXTENSION = ".szprofile"
MACHINE_ONLY = ("speeds", "ai_spent")          # belong to this PC, never saved in a profile


class ProfileError(ValueError):
    """The file isn't a SortZen profile, or can't be read."""


def make(settings: dict, keys: dict[str, str] | None = None) -> dict:
    profile = {"format": FORMAT, "version": __version__, "saved": time.strftime("%Y-%m-%d %H:%M"),
               "settings": {k: v for k, v in settings.items() if k not in MACHINE_ONLY}}
    if keys:
        profile["keys"] = keys
    return profile


def read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
    except (OSError, ValueError) as exc:
        raise ProfileError(f"The profile couldn't be read: {exc}") from exc
    if not isinstance(profile, dict) or profile.get("format") != FORMAT or not isinstance(profile.get("settings"), dict):
        raise ProfileError("This isn't a SortZen profile.")
    return profile


def write(path: str, profile: dict) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    os.replace(temp, path)


def folders(profile: dict) -> list[str]:
    s = profile["settings"]
    return [f["path"] for f in s.get("sources") or [] if isinstance(f, dict) and "path" in f] + \
        [d for d in s.get("destinations") or [] if isinstance(d, str)]


def _swap(text: str, mapping: list[tuple[str, str]]) -> str:
    for old, new in mapping:
        lowered, prefix = os.path.normcase(text), os.path.normcase(old.rstrip("\\/"))
        at = lowered.find(prefix)
        if at >= 0:
            end = at + len(prefix)
            if end == len(text) or text[end] in "\\/":
                return text[:at] + new.rstrip("\\/") + text[end:]
    return text


def remap(value, mapping: dict[str, str]):
    """Every path (in values and in keys) under an old folder moved under its new place."""
    pairs = sorted(mapping.items(), key=lambda kv: -len(kv[0]))
    if isinstance(value, dict):
        return {_swap(k, pairs) if isinstance(k, str) else k: remap(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, mapping) for v in value]
    if isinstance(value, str):
        return _swap(value, pairs)
    return value


def without(settings: dict, dropped: list[str]) -> dict:
    """Settings with some added folders taken out."""
    keys = {os.path.normcase(os.path.abspath(d)) for d in dropped}
    out = dict(settings)
    out["sources"] = [f for f in settings.get("sources") or []
                      if os.path.normcase(os.path.abspath(f.get("path", ""))) not in keys]
    out["destinations"] = [d for d in settings.get("destinations") or [] if os.path.normcase(os.path.abspath(d)) not in keys]
    return out
