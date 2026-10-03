"""The Folders tab: every added folder, drill-down with tick boxes, counts, the time estimate and warnings.

Unticked files and folders are left exactly where they are; SortZen still learns from them.
Subfolders and files are loaded when a folder is expanded, so whole drives open instantly.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QTreeWidget, QVBoxLayout, QWidget

from ..engine.planner import TIDY
from .opening import open_on_double_click
from .sortable import SortItem, human_size, make_sortable, natural

PATH = Qt.ItemDataRole.UserRole
KIND = Qt.ItemDataRole.UserRole + 1          # "root-source", "root-destination", "folder", "file", "more"
MAX_FILES_SHOWN = 500


class FoldersPage(QWidget):
    add_source = Signal()
    add_destination = Signal()
    add_windows = Signal()
    recount = Signal()
    leave_out = Signal(list, bool)          # paths, left out
    remove_folder = Signal(str)
    set_mode = Signal(str, str)
    open_folder = Signal(str)
    note_folder = Signal(str)

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.counts = []
        self._filling = False
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)
        top = QHBoxLayout()
        self.summary = QLabel("Folders", objectName="pageTitle")
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.summary, 1)
        for text, signal in (("Add a folder to sort…", self.add_source),
                             ("Add a destination folder…", self.add_destination)):
            button = QPushButton(text)
            button.clicked.connect(signal)
            top.addWidget(button)
        self.windows_button = QPushButton("Use my Windows folders")
        self.windows_button.clicked.connect(self.add_windows)
        top.addWidget(self.windows_button)
        recount = QPushButton("Count again")
        recount.setToolTip("Count the files again (nothing is opened)")
        recount.clicked.connect(self.recount)
        top.addWidget(recount)
        col.addLayout(top)
        self.estimate = QLabel(objectName="muted")
        self.estimate.setWordWrap(True)
        self.estimate.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.estimate)
        hint = QLabel("Untick anything SortZen should leave exactly where it is: nothing is moved into or out of "
                      "it, and SortZen still learns from what's inside. Right-click a folder to write a note about "
                      "what belongs in it (\"pay stubs, T4s, timesheets\"): SortZen and the AI use it.",
                      objectName="hint")
        hint.setWordWrap(True)
        col.addWidget(hint)

        self.tree = QTreeWidget()
        open_on_double_click(self.tree, lambda item: item.data(0, PATH), self.open_folder.emit)
        self.tree.setHeaderLabels(["Name", "Files", "Size", "How it's sorted", "Note"])
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 90)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemExpanded.connect(self._load_children)
        self.tree.itemChanged.connect(self._ticked)
        make_sortable(self.tree)
        col.addWidget(self.tree, 1)

        self.warnings = QFrame(objectName="banner")
        warn_col = QVBoxLayout(self.warnings)
        warn_col.setContentsMargins(12, 8, 12, 8)
        self.warning_text = QLabel()
        self.warning_text.setWordWrap(True)
        self.warning_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        warn_col.addWidget(self.warning_text)
        self.warnings.hide()
        col.addWidget(self.warnings)

    # ---------------------------------------------------------------- filling
    def set_counts(self, counts) -> None:
        self.counts = counts
        report = self.service.count_report(counts) if counts else None
        n = len(counts)
        if report:
            self.summary.setText(f"{n} folder{'s' if n != 1 else ''} · {report['files']:,} files · "
                                 f"{human_size(report['size'])}")
            self.estimate.setText(f"Making a plan takes {report['estimate']}. Repeat plans are quicker: unchanged "
                                  "files are remembered.")
            self.warning_text.setText("\n".join(f"• {w}" for w in report["warnings"]))
            self.warnings.setVisible(bool(report["warnings"]))
        else:
            self.summary.setText("Folders")
            self.estimate.setText("Add a folder to sort, such as Downloads, and the folders files may go to.")
            self.warnings.hide()
        self.windows_button.setVisible(bool(self.service.suggested_destinations()))
        self._fill()

    def show_counting(self) -> None:
        self.estimate.setText("Counting files… (nothing is opened)")

    def _tree_counts(self, path: str) -> tuple[int, int, int]:
        for c in self.counts:
            if path in c.tree:
                return c.tree[path]
        return (0, 0, 0)

    def _fill(self) -> None:
        self._filling = True
        expanded = {i.data(0, PATH) for i in self._all_items() if i.isExpanded()}
        self.tree.clear()
        modes = {f["path"]: f["mode"] for f in self.service.source_folders()}
        for path in [f["path"] for f in self.service.source_folders()] + self.service.destination_folders():
            kind = "root-source" if path in modes else "root-destination"
            how = ("Tidied in place" if modes.get(path) == TIDY else "Sorted into other folders") \
                if kind == "root-source" else "Destination: files may go here"
            item = self._item(self.tree, path, kind, os.path.basename(path) or path, how)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            if path in expanded:
                item.setExpanded(True)
        self._filling = False
        self.refresh_ticks()

    def _item(self, parent, path: str, kind: str, name: str, how: str = "") -> SortItem:
        if kind == "file":
            try:
                files, size = 1, os.path.getsize(path)
            except OSError:
                files, size = 1, 0
        else:
            files, size, _ = self._tree_counts(path)
        note = self.service.folder_note(path) if kind != "file" else ""
        item = SortItem(parent, [name, "" if kind == "file" else f"{files:,}", human_size(size), how, note])
        if note:
            item.setToolTip(4, note)
        item.setData(0, PATH, path)
        item.setData(0, KIND, kind)
        item.set_key(0, (1 if kind == "file" else 0, natural(name)))        # folders first, as in Explorer
        item.set_key(1, files)
        item.set_key(2, size)
        item.setToolTip(0, path)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        if kind != "file":
            item.setChildIndicatorPolicy(SortItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _load_children(self, item) -> None:
        if item.data(0, KIND) == "file" or item.childCount():
            return
        self._filling = True
        path = item.data(0, PATH)
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except OSError:
            entries = []
        files = 0
        for entry in entries:
            if entry.name.startswith((".", "$")):
                continue
            if entry.is_dir(follow_symlinks=False):
                self._item(item, entry.path, "folder", entry.name)
            elif files < MAX_FILES_SHOWN:
                self._item(item, entry.path, "file", entry.name)
                files += 1
        hidden = sum(1 for e in entries if not e.is_dir(follow_symlinks=False)) - files
        if hidden > 0:
            more = SortItem(item, [f"…and {hidden:,} more files", "", "", "", ""])
            more.setData(0, KIND, "more")
            more.set_key(0, (2, ()))
            more.setForeground(0, self.palette().placeholderText())
        if not item.childCount():
            item.setChildIndicatorPolicy(SortItem.ChildIndicatorPolicy.DontShowIndicator)
        self._filling = False
        self.refresh_ticks()

    def _all_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def refresh_ticks(self) -> None:
        """Ticks follow the left-out list; a folder with something left out inside shows a half tick."""
        self._filling = True
        left = [os.path.normcase(os.path.abspath(p)) for p in self.service.left_out()]

        def inside(path, folder):
            return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)

        for item in self._all_items():
            path = item.data(0, PATH)
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if any(inside(key, f) for f in left):
                state = Qt.CheckState.Unchecked
            elif any(inside(f, key) for f in left):
                state = Qt.CheckState.PartiallyChecked
            else:
                state = Qt.CheckState.Checked
            item.setCheckState(0, state)
            item.setForeground(0, self.palette().placeholderText() if state == Qt.CheckState.Unchecked
                               else self.palette().text())
        self._filling = False

    # ---------------------------------------------------------------- actions
    def _ticked(self, item, column: int) -> None:
        if self._filling or column != 0 or not item.data(0, PATH):
            return
        out = item.checkState(0) == Qt.CheckState.Unchecked
        self.leave_out.emit([item.data(0, PATH)], out)

    def selected_paths(self) -> list[str]:
        return [i.data(0, PATH) for i in self.tree.selectedItems() if i.data(0, PATH)]

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None or not item.data(0, PATH):
            menu = QMenu(self)
            menu.addAction("Add a folder to sort…", self.add_source.emit)
            menu.addAction("Add a destination folder…", self.add_destination.emit)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        paths = self.selected_paths()
        path, kind = item.data(0, PATH), item.data(0, KIND)
        menu = QMenu(self)
        menu.addAction("Leave out (SortZen still learns from it)", lambda: self.leave_out.emit(paths, True))
        menu.addAction("Include again", lambda: self.leave_out.emit(paths, False))
        menu.addSeparator()
        if kind == "root-source":
            current = next((f["mode"] for f in self.service.source_folders() if f["path"] == path), "")
            from .dialogs import MODE_TEXT
            for mode, (title, _) in MODE_TEXT.items():
                action = menu.addAction(title, lambda m=mode: self.set_mode.emit(path, m))
                action.setCheckable(True)
                action.setChecked(mode == current)
            menu.addSeparator()
        if kind != "file":
            has = bool(self.service.folder_note(path))
            menu.addAction("Change the note about this folder…" if has else "Write a note about this folder…",
                           lambda: self.note_folder.emit(path))
        menu.addAction("Open in Explorer", lambda: self.open_folder.emit(path if kind != "file"
                                                                         else os.path.dirname(path)))
        if kind in ("root-source", "root-destination"):
            menu.addAction("Remove from SortZen", lambda: self.remove_folder.emit(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
