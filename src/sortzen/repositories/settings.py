"""Program settings (``settings.json`` in per-user storage).

Saved with a write-then-rename so a crash never leaves a half-written file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class SettingsRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._read()

    def _read(self) -> dict:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            pass
        return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()
