"""The Cataloguing tab: the folders files are sorted into, as a tree users can see, edit and comment on,
with the files already in each folder and the files the plan sends there.

The left side lists every category and subcategory with its files and note, and below it the files
in the selected category. Files (several at once) and categories can be dragged onto a category,
from here or from Windows Explorer; SortZen moves them after confirmation and remembers the choice.
Folders dropped on the empty space below the categories are added to the catalog. The right side
shows the selected category (folders, example files, rules, feedback) with buttons to edit it and
to say what is wrong with it, a note box for the selected file, and the suggestions SortZen (or the
AI service) has for the catalog and for labels' folders, each with Accept and Not this. Dragging a
file the plan sends somewhere onto another folder changes the plan, nothing moves, and SortZen learns
from it; files already in a folder move on disk after confirmation.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QGridLayout, QMenu, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QTreeWidget, QVBoxLayout, QWidget,
)

from ..services.catalog import FEEDBACK
from .sortable import SortItem, make_sortable, natural

PATH = Qt.ItemDataRole.UserRole
COMING = Qt.ItemDataRole.UserRole + 1       # a file the plan sends here (not on disk here yet)
MIME = "application/x-sortzen-paths"


def paths_mime(paths: list[str]) -> QMimeData:
    """What a drag inside SortZen carries: the paths, never anything Explorer could act on."""
    mime = QMimeData()
    mime.setData(MIME, json.dumps([p for p in paths if p]).encode("utf-8"))
    return mime


def paths_from(mime: QMimeData) -> list[str]:
    """The paths a drag carries, from SortZen or from Windows Explorer."""
    if mime.hasFormat(MIME):
        return json.loads(bytes(mime.data(MIME)).decode("utf-8"))
    if mime.hasUrls():
        return [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
    return []


class _DropTarget:
    """Drops are confirmed after the drag has finished, and SortZen moves the files itself: the drag
    reports a copy, so neither Qt nor Explorer removes anything."""
    drops_from_itself = False

    def _accept_drag(self, event) -> bool:
        if not paths_from(event.mimeData()) or (event.source() is self and not self.drops_from_itself):
            event.ignore()
            return False
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        return True

    def _finish_drop(self, event, emit) -> None:
        paths = paths_from(event.mimeData())
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if paths:
            QTimer.singleShot(0, lambda: emit(paths))


class CategoryTree(_DropTarget, QTreeWidget):
    """The categories. Files and categories dropped on one go into it; folders dropped on the empty
    space below are added to the catalog."""
    dropped = Signal(list, str)             # paths, the category's folder
    dropped_outside = Signal(list)          # paths dropped below the categories
    drops_from_itself = True                # a category dragged onto another

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._marked = None

    def mimeTypes(self):
        return [MIME, "text/uri-list"]

    def mimeData(self, items):              # a category is dragged as its folder (added folders stay put)
        return paths_mime([i.data(0, PATH) for i in items if i.parent() is not None])

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def dragEnterEvent(self, event):
        self._accept_drag(event)

    def dragMoveEvent(self, event):
        if self._accept_drag(event):
            self._mark(self.itemAt(event.position().toPoint()))

    def dragLeaveEvent(self, event):
        self._mark(None)

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self._mark(None)
        if item is None:
            self._finish_drop(event, self.dropped_outside.emit)
        else:
            folder = item.data(0, PATH)
            self._finish_drop(event, lambda paths: self.dropped.emit(paths, folder))

    def _mark(self, item) -> None:
        """Show which category a drop goes into."""
        if self._marked is item:
            return
        for old in [self._marked] if self._marked is not None else []:
            try:
                for column in range(self.columnCount()):
                    old.setBackground(column, QBrush())
            except RuntimeError:
                pass
        self._marked = item
        if item is not None:
            for column in range(self.columnCount()):
                item.setBackground(column, self.palette().highlight().color().lighter(170))


class FileList(_DropTarget, QTreeWidget):
    """The files in the selected category: Shift- or Ctrl-click to choose several, drag them onto a
    category. Files dropped here from Explorer go into the selected category."""
    dropped = Signal(list, str)

    def __init__(self):
        super().__init__()
        self.folder = ""
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def mimeTypes(self):
        return [MIME, "text/uri-list"]

    def mimeData(self, items):
        return paths_mime([i.data(0, PATH) for i in items])

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def dragEnterEvent(self, event):
        self._accept_drag(event) if self.folder else event.ignore()

    def dragMoveEvent(self, event):
        self._accept_drag(event) if self.folder else event.ignore()

    def dropEvent(self, event):
        folder = self.folder
        self._finish_drop(event, lambda paths: self.dropped.emit(paths, folder))

    def selected_paths(self) -> list[str]:
        return [i.data(0, PATH) for i in self.selectedItems()]


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
    place = Signal(list, str)                # paths put into a category's folder
    move_files = Signal(list)                # paths to put into a category chosen from a list
    delete_files = Signal(list)
    add_to_catalog = Signal(list)            # folders to add (an empty list asks which)
    open_path = Signal(str)
    label = Signal(list, str, bool)          # files, label, on or off
    right_folder = Signal(list)              # files the plan sends to the right folder
    note_file = Signal(str, str)             # file, note

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.plan = None
        self.coming: dict[str, list] = {}       # folder (normcase) -> the plan's suggestions sending files there
        self.categories = []
        self.by_path = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)
        top = QHBoxLayout()
        self.summary = _label("Catalog", "pageTitle")
        top.addWidget(self.summary, 1)
        add = QPushButton("Add a folder…")
        add.setToolTip("Add a folder to the catalog: its subfolders become categories")
        add.clicked.connect(lambda: self.add_to_catalog.emit([]))
        top.addWidget(add)
        self.show_files = QCheckBox("Show files")
        self.show_files.setChecked(True)
        self.show_files.setToolTip("Show or hide the files in the selected category")
        top.addWidget(self.show_files)
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
                             "Coming shows the files the plan sends to each folder. Drag files onto the right folder: "
                             "SortZen remembers it and learns from it. Nothing on disk changes without a preview, and "
                             "everything can be undone.", "hint"))

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QSplitter(Qt.Orientation.Vertical)
        self.tree = CategoryTree()
        self.tree.setHeaderLabels(["Folder", "Files", "Coming", "Note"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 60)
        self.tree.setMinimumWidth(380)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._show)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.dropped.connect(self.place)
        self.tree.dropped_outside.connect(self._dropped_outside)
        make_sortable(self.tree)
        left.addWidget(self.tree)
        self.files_panel = QWidget()
        files_col = QVBoxLayout(self.files_panel)
        files_col.setContentsMargins(0, 6, 0, 0)
        files_col.setSpacing(4)
        self.files_title = _label("", "sectionCaps")
        files_col.addWidget(self.files_title)
        self.files = FileList()
        self.files.setHeaderLabels(["File", "Labels", "From", "Sure"])
        self.files.setColumnWidth(0, 220)
        self.files.setColumnWidth(1, 100)
        self.files.setColumnWidth(2, 120)
        self.files.itemSelectionChanged.connect(self._file_chosen)
        self.files.setRootIsDecorated(False)
        self.files.setAlternatingRowColors(True)
        self.files.setUniformRowHeights(True)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_menu)
        self.files.itemDoubleClicked.connect(lambda item, _: self.open_path.emit(item.data(0, PATH)))
        self.files.dropped.connect(self.place)
        make_sortable(self.files)
        files_col.addWidget(self.files, 1)
        files_col.addWidget(_label("Shift- or Ctrl-click to choose several files, then drag them onto a folder. A "
                                   "file the plan sends here (From shows where it is now) just changes the plan, and "
                                   "SortZen learns from it; a file already here moves after you confirm. Right-click "
                                   "for labels, Move to, Delete and Open.", "hint"))
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.files)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(lambda: self.files.selected_paths() and
                                 self.delete_files.emit(self.files.selected_paths()))
        left.addWidget(self.files_panel)
        left.setSizes([420, 300])
        self.show_files.toggled.connect(self._toggle_files)
        split.addWidget(left)

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
        self.note_box = QWidget()
        note_col = QVBoxLayout(self.note_box)
        note_col.setContentsMargins(0, 6, 0, 0)
        self.note_title = _label("", "sectionCaps")
        note_col.addWidget(self.note_title)
        self.file_why = _label("", "muted")
        note_col.addWidget(self.file_why)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText("Anything special about this file, or why it goes somewhere else. For "
                                          "example: “this one is for the 2023 audit”. Naming a folder sends it there.")
        self.note_edit.setMaximumHeight(70)
        note_col.addWidget(self.note_edit)
        save = QPushButton("Save note")
        save.clicked.connect(lambda: self.files.selected_paths() and
                             self.note_file.emit(self.files.selected_paths()[0], self.note_edit.toPlainText()))
        note_col.addWidget(save, 0, Qt.AlignmentFlag.AlignRight)
        self.note_box.hide()
        self.side.addWidget(self.note_box)
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
    def set_plan(self, plan) -> None:
        self.plan = plan
        self.coming = {}
        for s in plan.files if plan else []:
            if s.destination and os.path.normcase(s.destination) != os.path.normcase(s.current_folder):
                self.coming.setdefault(os.path.normcase(s.destination), []).append(s)
        if self.isVisible():
            self.refresh()

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
            coming = len(self.coming.get(os.path.normcase(c.path), []))
            item = SortItem(parent, [label, f"{c.files:,}", f"+{coming:,}" if coming else "", c.note])
            item.setData(0, PATH, c.path)
            item.set_key(0, natural(c.name))
            item.set_key(1, c.files)
            item.set_key(2, coming)
            item.setToolTip(0, "\n".join(c.folders))
            item.setToolTip(2, f"{coming:,} files the plan sends here" if coming else "")
            item.setToolTip(3, c.note)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if c.hidden or c.merged_into:
                item.setForeground(0, muted)
            items[c.path] = item
            if c.parent is None or len(self.categories) < 60:
                item.setExpanded(True)
        known = {os.path.normcase(c.path) for c in self.categories}
        for key, coming in self.coming.items():           # folders the plan makes
            folder = coming[0].destination
            parent = items.get(os.path.dirname(folder))
            if key in known or parent is None:
                continue
            item = SortItem(parent, [f"{os.path.basename(folder)}  (new)", "0", f"+{len(coming):,}", ""])
            item.setData(0, PATH, folder)
            item.set_key(0, natural(os.path.basename(folder)))
            item.setToolTip(0, "A folder the plan makes when files first move into it")
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            items[folder] = item
        self.tree.setSortingEnabled(True)
        total = sum(c.files for c in self.categories if c.parent is None)
        coming = sum(len(v) for v in self.coming.values())
        self.summary.setText(f"Cataloguing · {len(self.categories):,} folders · {total:,} files"
                             + (f" · {coming:,} coming from the plan" if coming else ""))
        if keep in items:
            self.tree.setCurrentItem(items[keep])
        found = list(self.service.catalog_suggestions(self.categories))
        if self.plan is not None:
            found = list(self.service.label_folder_suggestions(self.plan)) + found
        self.show_suggestions(found)
        self._show()

    def _selected(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, PATH) if item is not None else None

    def _show(self) -> None:
        c = self.by_path.get(self._selected())
        for button in self.edit_buttons + [self.hide_button]:
            button.setEnabled(c is not None)
        self._fill_files(c)
        if c is None and self._selected():
            self.title.setText(os.path.basename(self._selected()))
            self.details.setText("A folder the plan makes when files first move into it.")
            return
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
        if c.chosen:
            lines.append(f"You chose this folder for {c.chosen:,} file{'s' if c.chosen != 1 else ''}; "
                         "SortZen learns from them")
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
            source = getattr(s, "source", "SortZen")
            text = _label(f"{s.title}\n{s.why}" + (f"  ·  from {source}" if source != "SortZen" else ""))
            row.addWidget(text, 1)
            yes = QPushButton("Accept…" if getattr(s, "kind", "") in ("split", "merge", "empty") else "Accept")
            yes.clicked.connect(lambda _=False, x=s: self.accept.emit(x))
            no = QPushButton("Not this")
            no.clicked.connect(lambda _=False, x=s: self.decline.emit(x))
            row.addWidget(yes)
            row.addWidget(no)
            card.suggestion = s
            self.suggestion_box.addWidget(card)

    def _fill_files(self, c) -> None:
        folder = c.path if c else self._selected()
        self.files.folder = folder or ""
        if not self.show_files.isChecked():
            return
        self.files.setSortingEnabled(False)
        self.files.clear()
        found = self.service.category_files(folder) if c else []
        for f in found:
            self._file_row(f["path"], "Already here", "")
        coming = self.coming.get(os.path.normcase(folder), []) if folder else []
        for s in coming:
            item = self._file_row(s.path, self.service.display(s.current_folder), f"{s.percent}%")
            item.setData(0, COMING, True)
            item.set_key(3, s.percent)
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        self.files.setSortingEnabled(True)
        name = c.name if c else os.path.basename(folder or "")
        if not folder:
            self.files_title.setText("Files")
        else:
            more = f" (and {c.files - len(found):,} in its subfolders)" if c and c.files > len(found) else ""
            self.files_title.setText(f"Files in {name} · {len(found):,}{more}"
                                     + (f" · {len(coming):,} coming (in italics)" if coming else ""))
        self._file_chosen()

    def _file_row(self, path: str, origin: str, sure: str) -> SortItem:
        labels = self.service.labels_of(path)
        item = SortItem(self.files, [os.path.basename(path), ", ".join(labels), origin, sure])
        item.setData(0, PATH, path)
        item.setToolTip(0, path)
        item.setToolTip(2, origin)
        item.set_key(0, natural(os.path.basename(path)))
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _file_chosen(self) -> None:
        """One file chosen: why it goes here, and its note."""
        items = self.files.selectedItems()
        if len(items) != 1:
            self.note_box.hide()
            return
        path = items[0].data(0, PATH)
        planned = self.plan.for_path(path) if self.plan is not None else None
        self.note_title.setText(f"About “{os.path.basename(path)}”")
        why = [r.text for r in planned.reasons[:3]] if planned is not None and items[0].data(0, COMING) else []
        self.file_why.setText("\n".join(why))
        self.file_why.setVisible(bool(why))
        self.note_edit.setPlainText(self.service.file_note(path))
        self.note_box.show()

    def _toggle_files(self, on: bool) -> None:
        self.files_panel.setVisible(on)
        if on:
            self._fill_files(self.by_path.get(self._selected()))

    def _dropped_outside(self, paths: list) -> None:
        folders = [p for p in paths if os.path.isdir(p)]
        if folders:
            self.add_to_catalog.emit(folders)

    def _file_menu(self, pos) -> None:
        paths = self.files.selected_paths()
        if not paths:
            return
        n = len(paths)
        some = f"{n:,} files" if n != 1 else "this file"
        menu = QMenu(self)
        if any(i.data(0, COMING) for i in self.files.selectedItems()):
            menu.addAction("Right folder (SortZen learns from it)", lambda: self.right_folder.emit(paths))
        labels = menu.addMenu("Labels")
        for name in self.service.labels():
            action = labels.addAction(name)
            action.setCheckable(True)
            have = all(name in self.service.labels_of(p) for p in paths)
            action.setChecked(have)
            action.triggered.connect(lambda _=False, x=name, h=have: self.label.emit(paths, x, not h))
        labels.setEnabled(bool(self.service.labels()))
        menu.addAction(f"Move {some} to…", lambda: self.move_files.emit(paths))
        menu.addAction(f"Delete {some}…", lambda: self.delete_files.emit(paths))
        if n == 1:
            menu.addAction("Open", lambda: self.open_path.emit(paths[0]))
        menu.addAction("Open the folder", lambda: self.open_path.emit(os.path.dirname(paths[0])))
        menu.exec(self.files.viewport().mapToGlobal(pos))

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("Add a folder to the catalog…", lambda: self.add_to_catalog.emit([]))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
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
        menu.addAction("Open the folder", lambda: self.open_path.emit(path))
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
