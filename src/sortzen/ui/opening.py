"""Opening files and folders with Windows, from any list: double-click a file or folder to open it."""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_path(path: str | None) -> bool:
    """Open a file with its program, or a folder in Explorer. False when it isn't there (yet)."""
    if not path or not os.path.exists(path):
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_on_double_click(view, path_of, opener=None) -> None:
    """Double-clicking a row opens the file or folder ``path_of(item)`` gives (rows without one do nothing).
    In trees, double-click opens instead of expanding; the arrow still expands and collapses."""
    if hasattr(view, "setExpandsOnDoubleClick"):
        view.setExpandsOnDoubleClick(False)
    opener = opener or open_path

    def opened(item, *_):
        path = path_of(item)
        if path:
            opener(path)

    view.itemDoubleClicked.connect(opened)
