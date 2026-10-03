"""The Catalog tab: the categories files are sorted into, as a tree users can see, edit and comment on.

The left side lists every category and subcategory with its files and note. The right side shows
the selected category (folders, example files, rules, feedback) with buttons to edit it and to say
what is wrong with it, and below them the suggestions SortZen (or the AI service) has for the
catalog, each with Accept and Not this.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QMenu, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSplitter, QTreeWidget, QVBoxLayout, QWidget,
)

from ..services.catalog import FEEDBACK
from .sortable import SortItem, make_sortable, natural

PATH = Qt.ItemDataRole.UserRole


def _label(text: str = "", name: str = "") -> QLabel:
    label = QLabel(text, objectName=name) if name else QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class CatalogPage(QWidget):
    rename = Signal(str)
    add_subcategory = Signal(str)
    note = Signal(str)
    add_folder = Signal(str)
    merge = Signal(str)
    hide = Signal(str, bool)
    feedback = Signal(str, str)              # category, kind
    accept = Signal(object)                  # a suggestion
    decline = Signal(object)
    ask_ai = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.categories = []
        self.by_path = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)
        top = QHBoxLayout()
        self.summary = _label("Catalog", "pageTitle")
        top.addWidget(self.summary, 1)
        refresh = QPushButton("Find suggestions")
        refresh.setToolTip("Read the folders again and look for ways to improve the catalog (on this PC)")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        self.ai_button = QPushButton("Ask AI to review…")
        self.ai_button.setToolTip("Sends category names, file counts, notes, a few example names and your feedback; "
                                  "never file contents. Shows the cost first.")
        self.ai_button.clicked.connect(self.ask_ai)
        top.addWidget(self.ai_button)
        col.addLayout(top)
        col.addWidget(_label("Your categories, built from your folders. Select one to edit it or tell SortZen "
                             "what is wrong with it; SortZen uses your feedback to suggest a better structure. "
                             "Nothing on disk changes without a preview, and everything can be undone.", "hint"))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Category", "Files", "Note"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 60)
        self.tree.setMinimumWidth(380)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._show)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        make_sortable(self.tree)
        split.addWidget(self.tree)

        side = QScrollArea()
        side.setWidgetResizable(True)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        self.side = QVBoxLayout(panel)
        self.side.setContentsMargins(4, 0, 4, 0)
        self.title = _label("", "pageTitle")
        self.side.addWidget(self.title)
        self.details = _label("", "muted")
        self.side.addWidget(self.details)
        edits = QGridLayout()
        self.edit_buttons = []
        for i, (text, handler) in enumerate((
                ("Rename…", lambda p: self.rename.emit(p)), ("Add a subcategory…", lambda p: self.add_subcategory.emit(p)),
                ("Write a note…", lambda p: self.note.emit(p)), ("Add another folder…", lambda p: self.add_folder.emit(p)),
                ("Merge into…", lambda p: self.merge.emit(p)))):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, h=handler: self._selected() and h(self._selected()))
            edits.addWidget(button, i // 2, i % 2)
            self.edit_buttons.append(button)
        self.hide_button = QPushButton("Don't put files here")
        self.hide_button.setCheckable(True)
        self.hide_button.setToolTip("SortZen still learns from what is in it, but never sends files to it")
        self.hide_button.clicked.connect(lambda on: self._selected() and self.hide.emit(self._selected(), on))
        edits.addWidget(self.hide_button, 2, 1)
        self.side.addLayout(edits)
        self.side.addWidget(_label("How is this category?", "sectionCaps"))
        grid = QGridLayout()
        for i, kind in enumerate(("right", "too_broad", "too_narrow", "wrong_name", "comment")):
            button = QPushButton(FEEDBACK[kind] + ("…" if kind == "comment" else ""))
            button.clicked.connect(lambda _=False, k=kind: self._selected() and self.feedback.emit(self._selected(), k))
            grid.addWidget(button, i // 3, i % 3)
            self.edit_buttons.append(button)
        self.side.addLayout(grid)
        self.side.addWidget(_label("Suggestions", "sectionCaps"))
        self.suggestion_box = QVBoxLayout()
        self.side.addLayout(self.suggestion_box)
        self.side.addStretch(1)
        side.setWidget(panel)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([460, 620])
        col.addWidget(split, 1)
        self._show()

    # ---------------------------------------------------------------- filling
    def refresh(self) -> None:
        keep = self._selected()
        self.categories = self.service.catalog()
        self.by_path = {c.path: c for c in self.categories}
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        items = {}
        muted = self.palette().placeholderText()
        for c in self.categories:
            parent = items.get(c.parent, self.tree) if c.parent else self.tree
            label = c.name
            if c.hidden:
                label += "  (files aren't put here)"
            if c.merged_into:
                into = self.by_path.get(c.merged_into)
                label += f"  → {into.name if into else os.path.basename(c.merged_into)}"
            item = SortItem(parent, [label, f"{c.files:,}", c.note])
            item.setData(0, PATH, c.path)
            item.set_key(0, natural(c.name))
            item.set_key(1, c.files)
            item.setToolTip(0, "\n".join(c.folders))
            item.setToolTip(2, c.note)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if c.hidden or c.merged_into:
                item.setForeground(0, muted)
            items[c.path] = item
            if c.parent is None or len(self.categories) < 60:
                item.setExpanded(True)
        self.tree.setSortingEnabled(True)
        total = sum(c.files for c in self.categories if c.parent is None)
        self.summary.setText(f"Catalog · {len(self.categories):,} categories · {total:,} files")
        if keep in items:
            self.tree.setCurrentItem(items[keep])
        self.show_suggestions(self.service.catalog_suggestions(self.categories))
        self._show()

    def _selected(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, PATH) if item is not None else None

    def _show(self) -> None:
        c = self.by_path.get(self._selected())
        for button in self.edit_buttons + [self.hide_button]:
            button.setEnabled(c is not None)
        if c is None:
            self.title.setText("Select a category")
            self.details.setText("")
            return
        self.title.setText(c.name)
        lines = [f"{c.files:,} files" + (f", {len(c.direct):,} directly in it" if c.children else "")]
        lines.append("Folder" + ("s" if len(c.folders) > 1 else "") + ": " +
                     "; ".join(self.service.display(f) for f in c.folders))
        if c.note:
            lines.append(f"Note: {c.note}")
        if c.rules:
            lines.append(f"{c.rules} rule{'s' if c.rules != 1 else ''} send files here")
        if c.examples:
            lines.append("For example: " + ", ".join(c.examples))
        for f in c.feedback[-3:]:
            lines.append(f"Your feedback: {FEEDBACK.get(f['kind'], f['kind'])}" + (f" ({f['text']})" if f.get("text") else ""))
        self.details.setText("\n".join(lines))
        self.hide_button.blockSignals(True)
        self.hide_button.setChecked(c.hidden)
        self.hide_button.blockSignals(False)

    def show_suggestions(self, suggestions) -> None:
        while self.suggestion_box.count():
            widget = self.suggestion_box.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if not suggestions:
            self.suggestion_box.addWidget(_label("No suggestions right now. Give feedback on a category, or ask "
                                                 "the AI to review the catalog.", "hint"))
        for s in suggestions:
            card = QFrame(objectName="card")
            row = QHBoxLayout(card)
            row.setContentsMargins(10, 8, 10, 8)
            text = _label(f"{s.title}\n{s.why}" + (f"  ·  from {s.source}" if s.source != "SortZen" else ""))
            row.addWidget(text, 1)
            yes = QPushButton("Accept…" if s.kind in ("split", "merge", "empty") else "Accept")
            yes.clicked.connect(lambda _=False, x=s: self.accept.emit(x))
            no = QPushButton("Not this")
            no.clicked.connect(lambda _=False, x=s: self.decline.emit(x))
            row.addWidget(yes)
            row.addWidget(no)
            card.suggestion = s
            self.suggestion_box.addWidget(card)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        path = item.data(0, PATH)
        c = self.by_path.get(path)
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self.rename.emit(path))
        menu.addAction("Add a subcategory…", lambda: self.add_subcategory.emit(path))
        menu.addAction("Write a note…", lambda: self.note.emit(path))
        menu.addAction("Add another folder…", lambda: self.add_folder.emit(path))
        menu.addAction("Merge into…", lambda: self.merge.emit(path))
        hidden = bool(c and c.hidden)
        menu.addAction("Put files here again" if hidden else "Don't put files here",
                       lambda: self.hide.emit(path, not hidden))
        feedback = menu.addMenu("How is this category?")
        for kind in ("right", "too_broad", "too_narrow", "wrong_name", "comment"):
            feedback.addAction(FEEDBACK[kind] + ("…" if kind == "comment" else ""),
                               lambda k=kind: self.feedback.emit(path, k))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def select(self, path: str) -> None:
        for item in self._items():
            if item.data(0, PATH) == path:
                self.tree.setCurrentItem(item)
                return

    def _items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))
