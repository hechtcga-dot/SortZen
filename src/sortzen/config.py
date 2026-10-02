"""Constants and per-user storage locations.

Paths are resolved lazily: importing this module never creates folders. Set
SORTZEN_DATA_DIR to redirect per-user storage (used by tests and the self-test).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__

APP_NAME = "SortZen"
APP_VERSION = ".".join(__version__.split(".")[:2])
APP_TAGLINE = "Sort · Learn · Tidy"

MODEL_DEFAULT = "gemini-3.8-flash"
AI_BATCH_SIZE = 40
COST_CAP_PER_1000_FILES = 0.25          # US dollars
TRANSIENT_BACKOFFS = (5, 15, 30, 60)    # seconds between retries on busy-service errors


@dataclass(frozen=True)
class AppPaths:
    storage: Path

    @property
    def settings_path(self) -> Path:
        return self.storage / "settings.json"

    @property
    def database_path(self) -> Path:
        return self.storage / "sortzen.db"

    @property
    def logs_dir(self) -> Path:
        return self.storage / "logs"


def _default_storage() -> Path:
    override = os.getenv("SORTZEN_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def default_paths() -> AppPaths:
    return AppPaths(_default_storage())
