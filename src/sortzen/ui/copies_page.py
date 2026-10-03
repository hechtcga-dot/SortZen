"""The Copies tab: exact copies grouped together, the copy kept and why, and the extras to queue for deletion.

Ticked extras move into the "To delete" folder inside their added folder. Nothing is
deleted: users delete those folders themselves when they are sure, and Undo puts the copies back.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QTreeWidget, QVBoxLayout, QWidget,
)

from .sortable import SortItem, human_size, make_sortable, natural

COPY = Qt.ItemDataRole.UserRole
GROUP = Qt.ItemDataRole.UserRole + 1
NAME, FOLDER, MODIFIED, SIZE, NOTE = range(5)
SHORT_REASONS = {"It's in an organised folder": "organised folder", "Its name has no copy number": "no copy number",
                 "It's the oldest copy": "oldest", "The copy with the shortest path": "shortest path",
                 "You chose this copy": "your choice"}


class CopiesPage(QWidget):
    queue = Signal(list)                    # copy groups, with their ticks
    open_folder = Signal(str)

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.groups = []
        self._filling = False
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)
        top = QHBoxLayout()
        self.summary = QLabel("Copies", objectName="pageTitle")
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.summary, 1)
        self.queue_button = QPushButton("Queue ticked for deletion…", objectName="primary")
        self.queue_button.setToolTip("Moves the ticked copies into “To delete” folders after you "
                                     "confirm. Nothing is deleted, and Undo puts them back.")
        self.queue_button.clicked.connect(lambda: self.queue.emit(self.groups))
        top.addWidget(self.queue_button)
        col.addLayout(top)
        hint = QLabel("Files with exactly the same contents. One copy of each is kept (bold); ticked extras move "
                      "into the “To delete” folder inside the folder you added. Delete those "
                      "folders yourself when you're sure. Right-click a copy to keep it instead.", objectName="hint")
        hint.setWordWrap(True)
        col.addWidget(hint)
        self.search = QLineEdit(placeholderText="Search names and folders")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        col.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Folder", "Modified", "Size", "Notes"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemChanged.connect(self._ticked)
        for column, width in ((NAME, 300), (FOLDER, 280), (MODIFIED, 120), (SIZE, 80), (NOTE, 240)):
            self.tree.setColumnWidth(column, width)
        make_sortable(self.tree, SIZE, Qt.SortOrder.DescendingOrder)
        col.addWidget(self.tree, 1)

    # ---------------------------------------------------------------- filling
    def set_copies(self, groups) -> None:
        self.groups = groups
        self.refresh()

    def refresh(self) -> None:
        self._filling = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for group in self.groups:
            heading = SortItem(self.tree, [f"{group.name}  ·  {len(group.copies)} copies", "", "",
                                           human_size(group.size), ""])
            heading.setData(0, GROUP, group)
            heading.set_key(NAME, natural(group.name))
            heading.set_key(SIZE, group.size * len(group.extras))
            heading.setToolTip(SIZE, "Each copy")
            heading.setFirstColumnSpanned(False)
            for c in group.copies:
                item = SortItem(heading, [c.name, self.service.display(os.path.dirname(c.path)),
                                          time.strftime("%Y-%m-%d", time.localtime(c.modified_ns / 1e9)),
                                          human_size(group.size), self._note(c)])
                item.setData(0, COPY, c)
                item.setData(0, GROUP, group)
                item.set_key(MODIFIED, c.modified_ns)
                item.set_key(SIZE, group.size)
                item.setToolTip(0, c.path)
                item.setToolTip(FOLDER, os.path.dirname(c.path))
                item.setToolTip(NOTE, "\n".join(c.reasons) if c.keep else c.note)
                item.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c.keep:
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                else:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Checked if c.ticked else Qt.CheckState.Unchecked)
            heading.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            heading.setExpanded(True)
        self.tree.setSortingEnabled(True)
        self._filling = False
        self._filter(self.search.text())
        self._update_summary()

    @staticmethod
    def _note(c) -> str:
        if c.keep:
            return "Kept: " + ", ".join(SHORT_REASONS.get(r, r) for r in c.reasons)
        return c.note

    def _update_summary(self) -> None:
        ticked = [(g, c) for g in self.groups for c in g.extras if c.ticked]
        freed = sum(g.size for g, _ in ticked)
        extras = sum(len(g.extras) for g in self.groups)
        self.summary.setText(f"{len(self.groups):,} files have copies · {extras:,} extra copies take "
                             f"{human_size(sum(g.size * len(g.extras) for g in self.groups))}")
        self.queue_button.setText(f"Queue {len(ticked):,} ticked for deletion ({human_size(freed)})…" if ticked
                                  else "Queue ticked for deletion…")
        self.queue_button.setEnabled(bool(ticked))

    def ticked(self) -> list:
        return [c for g in self.groups for c in g.extras if c.ticked]

    # ---------------------------------------------------------------- actions
    def _ticked(self, item, column: int) -> None:
        if self._filling or column != 0 or item.data(0, COPY) is None:
            return
        item.data(0, COPY).ticked = item.checkState(0) == Qt.CheckState.Checked
        self._update_summary()

    def _filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            heading = self.tree.topLevelItem(i)
            group = heading.data(0, GROUP)
            match = not text or any(text in c.path.lower() for c in group.copies)
            heading.setHidden(not match)

    def keep_instead(self, copy) -> None:
        group = next(g for g in self.groups if copy in g.copies)
        group.keep_instead(copy.path)
        self.refresh()

    def _set_ticks(self, copies, on: bool) -> None:
        for c in copies:
            if not c.keep:
                c.ticked = on
        self.refresh()

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        chosen = [i.data(0, COPY) for i in self.tree.selectedItems() if i.data(0, COPY) is not None]
        for heading in (i for i in self.tree.selectedItems() if i.data(0, COPY) is None):
            chosen += heading.data(0, GROUP).extras
        menu = QMenu(self)
        copy = item.data(0, COPY)
        if copy is not None and not copy.keep:
            menu.addAction("Keep this copy instead", lambda: self.keep_instead(copy))
        menu.addAction("Tick", lambda: self._set_ticks(chosen, True))
        menu.addAction("Untick", lambda: self._set_ticks(chosen, False))
        if copy is not None:
            menu.addSeparator()
            menu.addAction("Open folder", lambda: self.open_folder.emit(os.path.dirname(copy.path)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
