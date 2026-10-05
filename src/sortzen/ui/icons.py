"""The program icon."""
from __future__ import annotations

from PySide6.QtGui import QIcon

from .theme import ASSET_DIR


def app_icon() -> QIcon:
    ico = ASSET_DIR / "sortzen.ico"
    return QIcon(str(ico if ico.is_file() else ASSET_DIR / "sortzen-icon.svg"))
