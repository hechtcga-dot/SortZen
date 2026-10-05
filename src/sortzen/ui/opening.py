"""Opening files and folders with Windows, from any list.

- Double-click a file or folder to open it (a file with its program, a folder in Explorer).
- Right-click: Open, Open containing folder (Explorer with the file selected) and, where it
  makes sense, Delete (into the "To delete" folder, after confirmation, with Undo).

Windows is asked to open things in the background, so a click never waits for the program
that opens the file to start.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractItemView, QMenu


class _Hub(QObject):
    """Carries messages from the background back to the window."""
    message = Signal(str)


_hub: _Hub | None = None
_handlers = {"report": None, "delete": None}    # the window's: report(text), delete(paths)


def _show(text: str) -> None:
    report = _handlers["report"]
    if report is not None:
        try:
            report(text)
        except RuntimeError:            # the window has closed
            _handlers["report"] = None


def set_handlers(report=None, delete=None) -> None:
    """``report(text)`` shows a short message (the status bar); ``delete(paths)`` deletes after confirmation."""
    global _hub
    if _hub is None:
        _hub = _Hub()
        _hub.message.connect(_show)
    _handlers.update(report=report, delete=delete)


def _report(text: str) -> None:
    if _hub is not None:
        _hub.message.emit(text)


def _name(path: str) -> str:
    return os.path.basename(os.path.normpath(path)) or path


def _in_background(work, path: str) -> None:
    def run():
        try:
            work()
        except OSError as exc:
            _report(f"“{_name(path)}” couldn't be opened: {exc.strerror or exc}")

    threading.Thread(target=run, daemon=True).start()


def open_path(path: str | None) -> bool:
    """Open a file with its program, or a folder in Explorer, without waiting for it. False when it isn't
    there (yet)."""
    if not path or not os.path.exists(path):
        return False
    path = os.path.normpath(path)
    _report(f"Opening “{_name(path)}”…")
    if sys.platform.startswith("win"):
        _in_background(lambda: os.startfile(path), path)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    return True


def show_in_folder(path: str | None) -> bool:
    """Open the folder a file or folder is in, with it selected (in Explorer). False when it isn't there."""
    if not path or not os.path.exists(path):
        return False
    path = os.path.normpath(path)
    _report(f"Opening the folder “{_name(os.path.dirname(path))}”…")
    if sys.platform.startswith("win"):
        _in_background(lambda: subprocess.Popen(["explorer", f"/select,{path}"]), path)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
    return True


def add_file_actions(menu: QMenu, paths: list[str], opener=None, delete: bool = True) -> None:
    """Open, Open containing folder and (when ``delete``) Delete for the chosen files or folders."""
    paths = [p for p in paths if p]
    if not paths:
        return
    opener = opener or open_path
    if menu.actions():
        menu.addSeparator()
    first = paths[0]
    there = os.path.exists(first)
    a = menu.addAction("Open" if len(paths) == 1 else f"Open “{_name(first)}”", lambda: opener(first))
    a.setEnabled(there)
    b = menu.addAction("Open containing folder", lambda: show_in_folder(first))
    b.setEnabled(there)
    if delete and _handlers["delete"] is not None:
        existing = [p for p in paths if os.path.exists(p)]
        n = len(existing)
        c = menu.addAction(f"Delete{'' if n == 1 else f' {n:,} items'}… (to the “To delete” folder)",
                           lambda: _handlers["delete"](existing))
        c.setEnabled(bool(existing))


def selected_paths(view, path_of) -> list[str]:
    items = view.selectedItems() if hasattr(view, "selectedItems") else []
    return [p for p in (path_of(i) for i in items) if p]


def open_on_double_click(view, path_of, opener=None, menu: bool = True, delete: bool = True) -> None:
    """Double-clicking a row opens the file or folder ``path_of(item)`` gives (rows without one do nothing).
    In trees, double-click opens instead of expanding; the arrow still expands and collapses. A list with no
    right-click menu of its own gets one with Open, Open containing folder and Delete."""
    if hasattr(view, "setExpandsOnDoubleClick"):
        view.setExpandsOnDoubleClick(False)
    opener = opener or open_path

    def opened(item, *_):
        path = path_of(item)
        if path:
            opener(path)

    view.itemDoubleClicked.connect(opened)
    if menu and view.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu:
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def show_menu(pos):
            item = view.itemAt(pos)
            if item is None or not path_of(item):
                return
            if not item.isSelected():
                if view.selectionMode() != QAbstractItemView.SelectionMode.NoSelection:
                    view.clearSelection()
                item.setSelected(True)
            paths = selected_paths(view, path_of) or [path_of(item)]
            context = QMenu(view)
            add_file_actions(context, paths, opener, delete)
            context.exec(view.viewport().mapToGlobal(pos))

        view.customContextMenuRequested.connect(show_menu)
