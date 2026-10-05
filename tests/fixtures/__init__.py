"""Shared test data."""
from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def shared_test_folders() -> Path:
    """The synthetic test folders, built once per test run. Tests must not change them."""
    from .make_test_folders import build

    folder = Path(tempfile.mkdtemp(prefix="sortzen_test_folders_"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return build(folder)


def answer_key() -> dict:
    return json.loads((shared_test_folders() / "answer_key.json").read_text(encoding="utf-8"))
