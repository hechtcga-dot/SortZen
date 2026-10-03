"""Windows around moving: confirm before anything moves, what happened afterwards, and past moves to undo."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QTreeWidget, QVBoxLayout,
)

from .opening import open_on_double_click
from .sortable import SortItem, make_sortable

LOG = Qt.ItemDataRole.UserRole


def _label(text: str, name: str = "hint") -> QLabel:
    label = QLabel(text, objectName=name)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _plural(n: int, word: str, many: str = "") -> str:
    return f"{n:,} {word if n == 1 else many or word + 's'}"


def _list(lines: list[str], height: int = 90) -> QPlainTextEdit:
    box = QPlainTextEdit("\n".join(lines))
    box.setReadOnly(True)
    box.setMaximumHeight(height)
    return box


class ConfirmMoveDialog(QDialog):
    """Everything a move will do, before it happens."""

    def __init__(self, parent, preview, display):
        super().__init__(parent)
        self.setWindowTitle("Move these files?")
        self.resize(640, 560)
        col = QVBoxLayout(self)
        what = [_plural(preview.files, "file")] if preview.files else []
        if preview.folders:
            what.append(f"{_plural(preview.folders, 'folder')} kept together "
                        f"({_plural(preview.files_in_folders, 'file')} inside)")
        col.addWidget(_label(f"Move {' and '.join(what)} into {_plural(len(preview.destinations), 'folder')}?",
                             "cardTitle"))
        new = sum(1 for _, _, is_new in preview.destinations if is_new)
        notes = []
        if new:
            notes.append(f"{_plural(new, 'new folder')} will be made (marked “new” below).")
        if preview.renamed:
            notes.append(f"{_plural(len(preview.renamed), 'name')} already taken at the destination: those files "
                         "get a number added, such as “(2)”. Nothing is overwritten.")
        if preview.emptied:
            notes.append(f"{_plural(len(preview.emptied), 'folder')} will be left empty and removed.")
        if preview.problems:
            notes.append(f"{_plural(preview.problems, 'item')} with a problem shown in the plan. Anything that "
                         "can't be moved is skipped and listed afterwards.")
        for note in notes:
            col.addWidget(_label("• " + note))

        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Destination", "Items", ""])
        self.table.setRootIsDecorated(False)
        self.table.setColumnWidth(0, 430)
        self.table.setColumnWidth(1, 60)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        for folder, count, is_new in preview.destinations:
            item = SortItem(self.table, [display(folder), f"{count:,}", "new" if is_new else ""])
            item.set_key(1, count)
            item.setToolTip(0, folder + ("" if is_new else "\nDouble-click to open it"))
            item.setData(0, Qt.ItemDataRole.UserRole, folder)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        open_on_double_click(self.table, lambda item: item.data(0, Qt.ItemDataRole.UserRole))
        make_sortable(self.table, 1, Qt.SortOrder.DescendingOrder)
        col.addWidget(self.table, 1)
        if preview.emptied:
            col.addWidget(_label("Removed once empty:"))
            col.addWidget(_list([display(f) for f in preview.emptied], 70))
        col.addWidget(_label("Every move is written down step by step: Edit › Undo puts everything back where it "
                             "was, even days later. Trying SortZen for the first time? Try it on a copy of a "
                             "folder first."))
        box = QDialogButtonBox()
        self.move_button = box.addButton(f"Move {preview.items:,}", QDialogButtonBox.ButtonRole.AcceptRole)
        self.move_button.setObjectName("primary")
        box.addButton(QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)


class MoveResultDialog(QDialog):
    """What a move (or putting one back) did, with anything skipped and why."""

    def __init__(self, parent, result, display, undoing: bool = False, queued: bool = False):
        super().__init__(parent)
        self.undo_requested = False
        title = "Put back" if undoing else "Moved to “To delete”" if queued else "Moved"
        self.setWindowTitle(title)
        self.resize(600, 420 if result.failed or result.renamed else 220)
        col = QVBoxLayout(self)
        done = f"{title} {_plural(result.moved, 'copy', 'copies') if queued else _plural(result.moved, 'item')}"
        if result.cancelled:
            done += ", then stopped safely: the rest stayed where they were"
        if result.removed_folders:
            done += f"; removed {_plural(result.removed_folders, 'empty folder')}"
        col.addWidget(_label(done + ".", "cardTitle"))
        if result.renamed:
            col.addWidget(_label(f"{_plural(len(result.renamed), 'name')} already taken, so a number was added:"))
            col.addWidget(_list([f"{old}  →  {new}" for old, new in result.renamed]))
        if result.failed:
            col.addWidget(_label(f"{_plural(len(result.failed), 'item')} couldn't be moved and stayed where "
                                 f"{'it was' if len(result.failed) == 1 else 'they were'}:"))
            col.addWidget(_list([f"{display(path)}: {reason}" for path, reason in result.failed], 140))
        col.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        if queued and result.moved:
            col.insertWidget(1, _label("Nothing has been deleted. The copies are in folders named “Queued for "
                                       "deletion” with today's date; delete those folders yourself when you're "
                                       "sure."))
        if not undoing and result.moved:
            undo = QPushButton("Undo this move")
            undo.setToolTip("Put everything from this move back where it was")
            undo.clicked.connect(self._undo)
            box.addButton(undo, QDialogButtonBox.ButtonRole.ActionRole)
        box.rejected.connect(self.accept)
        col.addWidget(box)

    def _undo(self) -> None:
        self.undo_requested = True
        self.accept()


KIND_TEXT = {"move": "Move", "duplicates": "Copies queued for deletion", "rename": "Folder renamed",
             "catalog": "Catalog reorganized", "placed": "Put into a category", "deleted": "Files queued for deletion"}


class RunsDialog(QDialog):
    """Past moves, newest first; any of them can be put back."""

    def __init__(self, parent, runs: list[dict]):
        super().__init__(parent)
        self.chosen: str | None = None
        self.setWindowTitle("Undo a move")
        self.resize(560, 400)
        col = QVBoxLayout(self)
        col.addWidget(_label("Choose a move to put back. Files go back to where they were; any with a name that "
                             "has been taken since get a number added."))
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["When", "What", "Items", ""])
        self.table.setRootIsDecorated(False)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 200)
        for run in runs:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(run["time"])) if run["time"] else ""
            item = SortItem(self.table, [when, KIND_TEXT.get(run["kind"], run["kind"]), f"{run['moved']:,}",
                                         "put back" if run["undone"] else ""])
            item.set_key(0, run["time"])
            item.set_key(2, run["moved"])
            item.setData(0, LOG, "" if run["undone"] or not run["moved"] else run["log"])
            item.setToolTip(0, os.path.basename(run["log"]))
        make_sortable(self.table, 0, Qt.SortOrder.DescendingOrder)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemDoubleClicked.connect(lambda *_: self.accept())
        col.addWidget(self.table, 1)
        box = QDialogButtonBox()
        self.put_back = box.addButton("Put back", QDialogButtonBox.ButtonRole.AcceptRole)
        self.put_back.setEnabled(False)
        box.addButton(QDialogButtonBox.StandardButton.Close)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)
        if not runs:
            col.insertWidget(1, _label("Nothing has been moved yet."))

    def _selected(self) -> None:
        item = self.table.currentItem()
        self.put_back.setEnabled(bool(item and item.data(0, LOG)))

    def accept(self) -> None:
        item = self.table.currentItem()
        if item and item.data(0, LOG):
            self.chosen = item.data(0, LOG)
            super().accept()
