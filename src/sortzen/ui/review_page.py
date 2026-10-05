"""The Review tab: the whole plan on one screen, before anything moves and again after.

One tree of the folders files go to (folders still to be made are marked NEW): the files and
folders coming, the files already there (grey), and the ones SortZen is less sure of marked
"check" ("Show only what to check" leaves only those). Dragging files or folders onto another
folder changes the plan and SortZen learns from it. The box on the right shows the selected
file's labels, why it goes there and a note, or the selected folder's rules; Rules… lists them
all. Move shows everything that will move; after a move the screen comes back with everything
where it is now, to change more and move again.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engine.planner import TIDY
from . import theme
from .catalog_page import CategoryTree, paths_mime
from .opening import open_on_double_click
from ..services.file_facts import day
from .session_wizard import _clear, _label, _link, describe_facts, label_menu_on
from .to_place_page import FlowLayout

PATH = Qt.ItemDataRole.UserRole
KIND = Qt.ItemDataRole.UserRole + 1         # "folder", "file" or "kept" (a folder that moves as it is)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class ReviewTree(CategoryTree):
    """Folders and the batch's files. Files and new folders dragged onto a folder go there in the plan."""

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHeaderLabels(["Folders and files", "Details"])
        self.header().setSectionsMovable(False)
        self.header().setToolTip("Drag the line between the headings to make a column wider")

    def mimeData(self, items):                  # files and folders (the folders added themselves stay put)
        return paths_mime([i.data(0, PATH) for i in items if i.parent() is not None])

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self._mark(None)
        if item is not None and item.data(0, KIND) != "folder":
            item = item.parent()
        if item is None:
            event.ignore()
            return
        folder = item.data(0, PATH)
        self._finish_drop(event, lambda paths: self.dropped.emit(paths, folder))


class ReviewPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.service = window.service
        self.flow = None
        self.items: dict[str, QTreeWidgetItem] = {}
        self._choices: list[str] = []
        self._widened = False
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 14, 20, 0)
        col.setSpacing(10)
        head = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = _label("", "bigTitle")
        words.addWidget(self.title)
        self.subtitle = _label("", "muted")
        words.addWidget(self.subtitle)
        head.addLayout(words, 1)
        self.new_button = QPushButton("New folder")
        self.new_button.setToolTip("Make a folder in the plan, inside the selected folder; it is made on disk when "
                                   "files move into it")
        self.new_button.clicked.connect(lambda: self.new_folder())
        head.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignTop)
        self.rules_button = QPushButton("Rules…")
        self.rules_button.setToolTip("Every rule: what it matches and where its files go. Change, switch off or "
                                     "remove them; the plan is made again with them")
        self.rules_button.clicked.connect(lambda: self.show_rules())
        head.addWidget(self.rules_button, 0, Qt.AlignmentFlag.AlignTop)
        self.group_button = QPushButton("Too many folders?")
        self.group_button.setToolTip("Put the selected folders (or the look-alike folders in the selected folder) "
                                     "together into one new folder, such as “Old versions”")
        self.group_button.clicked.connect(lambda: self.too_many_folders())
        head.addWidget(self.group_button, 0, Qt.AlignmentFlag.AlignTop)
        self.delete_files_button = QPushButton("Delete…")
        self.delete_files_button.setToolTip("Move the selected files into the “To delete” folder (Undo puts them back)")
        self.delete_files_button.clicked.connect(lambda: self.selected_files() and
                                                 self.window.delete_files(self.selected_files()))
        head.addWidget(self.delete_files_button, 0, Qt.AlignmentFlag.AlignTop)
        self.delete_button = QPushButton("Delete folder")
        self.delete_button.setToolTip("Delete a folder still to be made; its files go to the folder it was in")
        self.delete_button.clicked.connect(self.delete_folder)
        head.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QFrame(objectName="section")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(4, 6, 4, 8)
        self.tree = ReviewTree()
        self.tree.setStyleSheet("QTreeWidget { background: white; }")
        self.tree.setColumnWidth(0, 330)
        self.tree.dropped.connect(self.dropped)
        self.tree.itemSelectionChanged.connect(self._show_details)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        open_on_double_click(self.tree, lambda item: item.data(0, PATH), window.open_folder)
        lcol.addWidget(self.tree, 1)
        lcol.addWidget(_label("Drag files or folders onto another folder to change the plan; SortZen learns from "
                              "it. Shift- or Ctrl-click to choose several. Double-click to open; right-click for more.",
                              "hint"))
        body.addWidget(left, 125)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.details = QFrame(objectName="card")
        dcol = QVBoxLayout(self.details)
        dcol.setContentsMargins(16, 14, 16, 14)
        dcol.setSpacing(8)
        self.details_caption = QLabel(objectName="sectionCaps")
        dcol.addWidget(self.details_caption)
        self.details_name = _label("", "cardTitle")
        dcol.addWidget(self.details_name)
        self.details_facts = _label("", "hint")
        dcol.addWidget(self.details_facts)
        self.chips = FlowLayout(spacing=6)
        holder = QWidget()
        holder.setLayout(self.chips)
        dcol.addWidget(holder)
        self.details_why = _label("", "muted")
        dcol.addWidget(self.details_why)
        self.note_label = QLabel("Note", objectName="fieldLabel")
        dcol.addWidget(self.note_label)
        self.note = QPlainTextEdit(placeholderText="Anything special about this file, or why it goes somewhere else")
        self.note.setAccessibleName("Note")
        self.note.setMaximumHeight(70)
        self._note_timer = QTimer(self, singleShot=True, interval=600)
        self._note_timer.timeout.connect(self._save_note)
        self.note.textChanged.connect(lambda: self._note_timer.start())
        dcol.addWidget(self.note)
        right.addWidget(self.details)
        self.rules_box = QFrame(objectName="card")
        rcol = QVBoxLayout(self.rules_box)
        rcol.setContentsMargins(16, 14, 16, 14)
        rcol.setSpacing(6)
        self.rules_caption = QLabel(objectName="sectionCaps")
        rcol.addWidget(self.rules_caption)
        self.rules = QVBoxLayout()
        self.rules.setSpacing(4)
        rcol.addLayout(self.rules)
        rcol.addWidget(_link("Add a rule…", lambda: self.add_rule()))
        right.addWidget(self.rules_box)
        right.addStretch(1)
        body.addLayout(right, 100)
        col.addLayout(body, 1)

        footer = QFrame(objectName="footer")
        row = QHBoxLayout(footer)
        row.setContentsMargins(0, 12, 0, 12)
        self.only_check = QCheckBox("Show only what to check")
        self.only_check.setToolTip("Only the files and folders SortZen is less sure of, and the folders they go to")
        self.only_check.toggled.connect(lambda _: self.refresh_plan())
        row.addWidget(self.only_check)
        self.show_there = QCheckBox("Show files already there", checked=True)
        self.show_there.setToolTip("List the files already in each folder too (grey), not only the ones coming")
        self.show_there.toggled.connect(lambda _: self.refresh_plan())
        row.addWidget(self.show_there)
        self.footer_text = QLabel(objectName="hint")
        self.footer_text.setWordWrap(True)
        row.addWidget(self.footer_text, 1)
        self.move_button = QPushButton("Move…", objectName="primary")
        self.move_button.clicked.connect(self.move)
        row.addWidget(self.move_button)
        col.addWidget(footer)
        self._path = None
        self._files_by_folder: dict[str, list] = {}
        self._filled: set[str] = set()
        self.tree.itemExpanded.connect(self._fill_folder)

    # ---------------------------------------------------------------- the whole plan, at once
    def set_flow(self, flow) -> None:
        self.flow = flow
        flow.start_review(flow.plan)
        self._choices = self.service.destination_choices(flow.plan)
        self.only_check.setChecked(False)
        self.refresh_plan()

    def refresh_plan(self) -> None:
        """The plan as one tree: where everything goes, the files and folders to check marked."""
        if self.flow is None:
            return
        files, folders = self.flow.review_files(), self.flow.moving_folders()
        unplaced, to_check = self.flow.unplaced_files(), self.flow.to_check()
        places = {_key(s.destination) for s in files} | {_key(f.destination) for f in folders.values()}
        what = [f"{len(files):,} file{'s' if len(files) != 1 else ''}"] if files else []
        if folders:
            what.append(f"{len(folders):,} folder{'s' if len(folders) != 1 else ''}")
        moved = self.flow.session.moved
        if what:
            self.title.setText(f"{' and '.join(what)} go into {len(places):,} folder{'s' if len(places) != 1 else ''}")
        else:
            self.title.setText("Everything is in place" if moved else "Nothing to move")
        if not what:
            self.subtitle.setText((f"{moved:,} files moved in this session. " if moved else "") +
                                  "Drag files or folders onto another folder to change anything, then Move again. "
                                  "Edit › Undo a move puts a move back.")
        elif to_check:
            self.subtitle.setText(f"SortZen is sure of the rest; {to_check:,} {'is' if to_check == 1 else 'are'} "
                                  "marked “check”: it is less sure where they go. Drag anything to change it. Nothing "
                                  "moves until you click Move.")
        else:
            self.subtitle.setText("SortZen is sure of all of it. Drag anything to change it. Nothing moves until you "
                                  "click Move.")
        extra = f" · {len(unplaced):,} with no folder yet stay where they are" if unplaced else ""
        self.footer_text.setText(f"{to_check:,} to check{extra}. Every move can be undone.")
        self.only_check.setText(f"Show only what to check ({to_check:,})")
        self.only_check.setEnabled(bool(to_check) or self.only_check.isChecked())
        self.rules_button.setText(f"Rules ({len(self.service.rules()):,})…")
        n = len(files) + len(folders)
        self.move_button.setText(f"Move {n:,}…" if n else "Move…")
        self.move_button.setEnabled(bool(n))
        self._fill(files, folders, unplaced)

    def _fill(self, files: list, moving: dict, unplaced: list) -> None:
        expanded = {_key(i.data(0, PATH)) for i in self.items.values() if i.isExpanded()}
        selected = [i.data(0, PATH) for i in self.tree.selectedItems()]
        scroll = self.tree.verticalScrollBar().value()
        first_time = not self.items
        self.tree.clear()
        self.items, self._filled = {}, set()
        only = self.only_check.isChecked()
        unsure = self.flow.is_unsure
        planned = {_key(f) for f in self.flow.planned_folders()}
        self._files_by_folder = {}
        for s in files:
            if not only or unsure(s):
                self._files_by_folder.setdefault(_key(s.destination), []).append(s)
        roots = [*self.service.destination_folders(),
                 *[f["path"] for f in self.service.source_folders() if f["mode"] == TIDY]]

        def moves(key: str) -> bool:
            return any(key == m or key.startswith(m + os.sep) for m in moving)

        shown_moving = {k: f for k, f in moving.items() if not only or f.percent < self.flow.level()}
        wanted = set(self._files_by_folder) | {_key(f.destination) for f in shown_moving.values()}
        folders = {_key(f): f for f in [*self._choices, *self.flow.planned_folders(),
                                        *[s.destination for s in files], *[f.destination for f in moving.values()]]
                   if not moves(_key(f))}
        for key in sorted(folders, key=lambda k: (k.count(os.sep), k)):
            if only and not any(w == key or w.startswith(key + os.sep) for w in wanted):
                continue
            self._folder_item(folders[key], planned, roots)
        totals: dict[str, list[int]] = {}
        for s in files:
            counts = totals.setdefault(_key(s.destination), [0, 0])
            counts[0] += 1
            counts[1] += unsure(s)
        self._in_place = self.flow.files_in_place() if self.show_there.isChecked() and not only else {}
        for key, item in self.items.items():
            count, check = totals.get(key, (0, 0))
            there = len(self._in_place.get(key, []))
            parts = [f"{count:,} coming" + (f" ({check:,} to check)" if check else "")] if count else []
            if there:
                parts.append(f"{there:,} there")
            text = "· " + " · ".join(parts) if parts else ""
            if text or key in planned:
                self._detail(item, text, key in planned)
            if self._files_by_folder.get(key) or there:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        for key, f in sorted(shown_moving.items(), key=lambda kv: os.path.basename(kv[1].path).lower()):
            parent = self.items.get(_key(f.destination))
            if parent is None:
                continue
            item = QTreeWidgetItem(parent, [os.path.basename(f.path)])
            item.setData(0, PATH, f.path)
            item.setData(0, KIND, "kept")
            item.setToolTip(0, f"{f.path}\nMoves here as it is, with everything in it")
            check = "check · " if f.percent < self.flow.level() else ""
            item.setText(1, f"{check}moves here as it is · from {self.service.display(os.path.dirname(f.path))} · "
                            f"{f.files:,} file{'s' if f.files != 1 else ''}")
            item.setForeground(1, QColor(theme.WARN_TEXT) if check else self.palette().placeholderText())
        if unplaced and not only:
            group = QTreeWidgetItem(self.tree, [f"No folder yet · {len(unplaced):,}"])
            group.setData(0, KIND, "unplaced")
            group.setText(1, "they stay where they are unless you drag them onto a folder")
            group.setForeground(1, self.palette().placeholderText())
            for s in sorted(unplaced, key=lambda s: os.path.basename(s.path).lower()):
                self._file_item(group, s, unplaced=True)
        for key, item in self.items.items():               # open what was open, and where there is something to check
            count, check = totals.get(key, (0, 0))
            if key in expanded or item.parent() is None or (check and (only or first_time)):
                item.setExpanded(True)
                above = item.parent()
                while above is not None and (check or key in expanded):
                    above.setExpanded(True)
                    above = above.parent()
        if not self._widened:                       # once; after that the width users chose stays
            self.tree.resizeColumnToContents(0)
            self.tree.setColumnWidth(0, min(max(self.tree.columnWidth(0) + 24, 280), 520))
            self._widened = True
        self.tree.verticalScrollBar().setValue(scroll)
        chosen = [self._find(p) for p in selected]
        chosen = [i for i in chosen if i is not None]
        for item in chosen:
            item.setSelected(True)
        if not chosen:
            moving = {_key(s.path) for s in files}
            first = next((i for i in self._all_items() if i.data(0, KIND) == "file"
                          and _key(i.data(0, PATH)) in moving), None)
            if first is not None:
                first.setSelected(True)
                self.tree.setCurrentItem(first)
        self._show_details()

    def _fill_folder(self, item) -> None:
        """A folder's files are listed when it is first opened, so a big plan shows at once."""
        key = _key(item.data(0, PATH) or "")
        if item.data(0, KIND) != "folder" or key in self._filled:
            return
        self._filled.add(key)
        files = sorted(self._files_by_folder.get(key, []), key=lambda s: os.path.basename(s.path).lower())
        there = sorted(getattr(self, "_in_place", {}).get(key, []), key=lambda p: os.path.basename(p).lower())
        facts = self.service.file_facts([s.path for s in files] + there)
        for s in files:
            self._file_item(item, s, facts=facts)
        for path in there:                      # already in this folder: grey
            child = QTreeWidgetItem(item, [os.path.basename(path)])
            child.setData(0, PATH, path)
            child.setData(0, KIND, "file")
            child.setToolTip(0, path)
            added = day(facts[path].added)
            child.setText(1, "already here" + (f" · {added}" if added else ""))
            for column in (0, 1):
                child.setForeground(column, self.palette().placeholderText())

    def _file_item(self, parent, s, unplaced: bool = False, facts=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [os.path.basename(s.path)])
        item.setData(0, PATH, s.path)
        item.setData(0, KIND, "file")
        item.setToolTip(0, s.path)
        facts = facts or self.service.file_facts([s.path])
        added = day(facts[s.path].added)
        where = f"from {self.service.display(s.current_folder)}" + (f" · {added}" if added else "")
        check = not unplaced and self.flow.is_unsure(s)
        item.setText(1, f"check · {s.percent}% sure · {where}" if check else where)
        item.setForeground(1, QColor(theme.WARN_TEXT) if check else self.palette().placeholderText())
        return item

    def _all_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _find(self, path: str):
        if _key(path) in self.items:
            return self.items[_key(path)]
        return next((i for i in self._all_items() if i.data(0, PATH) and _key(i.data(0, PATH)) == _key(path)), None)

    def _folder_item(self, folder: str, planned: set, roots: list[str]) -> QTreeWidgetItem | None:
        key = _key(folder)
        if key in self.items:
            return self.items[key]
        parent_path = os.path.dirname(folder)
        is_root = any(_key(r) == key for r in roots)
        parent = None
        if not is_root:
            if parent_path == folder or not any(key.startswith(_key(r) + os.sep) for r in roots):
                return None
            parent = self._folder_item(parent_path, planned, roots)
            if parent is None:
                return None
        item = QTreeWidgetItem(parent or self.tree, [os.path.basename(folder) or folder])
        if is_root:
            item.setText(1, folder)
            item.setForeground(1, self.palette().placeholderText())
        item.setData(0, PATH, folder)
        item.setData(0, KIND, "folder")
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setToolTip(0, folder)
        if key in planned:
            self._detail(item, "", True)
        self.items[key] = item
        return item

    def _detail(self, item, text: str, new: bool) -> None:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        if new:
            row.addWidget(QLabel("NEW", objectName="newBadge"))
        if text:
            row.addWidget(QLabel(text, objectName="hint"))
        row.addStretch(1)
        self.tree.setItemWidget(item, 1, box)

    # ---------------------------------------------------------------- the details box
    def selected_files(self) -> list[str]:
        return [i.data(0, PATH) for i in self._selected() if i.data(0, KIND) in ("file", "kept")]

    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        from .opening import add_file_actions

        item = self.tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        folders = self.selected_folders()
        if len(folders) > 1:
            menu.addAction(f"Put these {len(folders)} folders into one folder…", lambda: self.too_many_folders(folders))
        if item.data(0, KIND) == "folder":
            folder = item.data(0, PATH)
            if len(folders) <= 1 and self.flow.look_alike([f for f in self._children(folder) if os.path.isdir(f)]):
                menu.addAction("Too many folders in here? Put look-alike folders together…",
                               lambda: self.too_many_folders([folder]))
            menu.addAction("New folder here…", lambda: self.new_folder())
            remove = menu.addAction("Delete this folder from the plan", self.delete_folder)
            remove.setEnabled(not os.path.isdir(folder))
            add_file_actions(menu, [folder], self.window.open_folder, delete=False)
        else:
            files = [p for p in self.selected_files() if self.flow.plan.for_path(p) is not None]
            if files:
                menu.addAction("Leave where it is" if len(files) == 1 else f"Leave these {len(files)} where they are",
                               lambda: self.leave_here(files))
            add_file_actions(menu, self.selected_files(), self.window.open_folder)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def drop(self, paths: list[str]) -> None:
        """Files that went to “To delete” have left the plan already: the tree follows."""
        if self.flow is not None:
            self.refresh_plan()

    def _selected(self) -> list[QTreeWidgetItem]:
        return self.tree.selectedItems()

    def _selected_folder(self) -> str | None:
        items = self._selected()
        if not items:
            return None
        item = items[0]
        if item.data(0, KIND) != "folder":
            item = item.parent()
        return item.data(0, PATH) if item is not None else None

    def _show_details(self) -> None:
        self._save_note()
        items = self._selected()
        item = items[0] if items else None
        kind = item.data(0, KIND) if item else None
        path = item.data(0, PATH) if item else None
        self._path = path if kind == "file" else None
        _clear(self.chips)
        self.note.blockSignals(True)
        if kind == "file":
            s = self.flow.plan.for_path(path)
            self.details_caption.setText("SELECTED FILE" if len(items) == 1 else f"{len(items)} SELECTED")
            self.details_name.setText(os.path.basename(path))
            for label in self.service.labels_of(path):
                chip = QLabel(label, objectName="labelChip")
                chip.setToolTip("Right-click to rename or delete this label")
                label_menu_on(chip, label, self.window)
                self.chips.addWidget(chip)
            where = self.service.display(s.destination) + (" (new)" if s.new_folder else "") if s else ""
            reasons = "; ".join(r.text for r in (s.reasons if s else []) if r.supports)
            if s is None:
                self.details_why.setText("Already in this folder. Drag it onto another folder to move it there.")
            elif not s.destination:
                self.details_why.setText("SortZen has no folder for it yet: it stays where it is unless you drag "
                                         "it onto a folder.")
            else:
                sure = f" SortZen is {s.percent}% sure: check it." if self.flow.is_unsure(s) else ""
                self.details_why.setText((f"Goes to {where}: {reasons}." if reasons else f"Goes to {where}.") + sure)
            self.details_facts.setText(describe_facts(self.service.file_facts([path])[path]))
            self.details_facts.show()
            self.note.setPlainText(self.service.file_note(path))
            for w in (self.note_label, self.note):
                w.show()
        elif kind in ("folder", "kept"):
            self.details_facts.hide()
            self.details_caption.setText("SELECTED FOLDER")
            self.details_name.setText(os.path.basename(path) or path)
            if kind == "kept":
                f = self.flow.plan.folder(path)
                self.details_why.setText(f"Moves as it is, with its {f.files:,} file{'s' if f.files != 1 else ''}, "
                                         f"to {self.service.display(f.destination)}." if f else "")
            else:
                new = not os.path.isdir(path)
                self.details_why.setText("Still to be made: it is made when files move into it." if new else
                                         self.service.folder_note(path))
            for w in (self.note_label, self.note):
                w.hide()
        else:
            self.details_facts.hide()
            self.details_caption.setText("")
            self.details_name.setText("Select a file or folder")
            self.details_why.setText("")
            for w in (self.note_label, self.note):
                w.hide()
        self.note.blockSignals(False)
        folder = self._selected_folder()
        self.rules_box.setVisible(bool(folder))
        if folder:
            self.rules_caption.setText(f"RULES FOR {(os.path.basename(folder) or folder).upper()}")
            _clear(self.rules)
            rules = self.flow.rules_for(folder)
            if not rules:
                self.rules.addWidget(_label("No rules send files here yet.", "hint"))
            for rule in rules:
                row = QHBoxLayout()
                row.addWidget(_label(self.service.describe_rule(rule) + "."), 1)
                row.addWidget(_link("Change…", lambda _=False, x=rule: self.change_rule(x)))
                row.addWidget(_link("Remove", lambda _=False, x=rule: self.remove_rule(x)))
                self.rules.addLayout(row)
        self.delete_button.setEnabled(bool(folder) and not os.path.isdir(folder or ""))

    def _save_note(self) -> None:
        self._note_timer.stop()
        if self._path and self.note.isVisible():
            text = self.note.toPlainText()
            if text != self.service.file_note(self._path):
                self.service.set_file_note(self._path, text)

    def add_rule(self, label: str | None = None) -> None:
        folder = self._selected_folder()
        if not folder:
            return
        from ..engine.rules import Rule

        if label is None:
            from .dialogs import RuleDialog

            dialog = RuleDialog(self, self.service, None, self.flow.plan if self.flow else None, "Add a rule",
                                destination=folder)
            if not dialog.exec() or dialog.chosen is None:
                return
            rule = dialog.chosen
        else:
            rule = Rule("", folder, label=label)
        before = self.service.add_rule(rule)
        self.window._push_undo("Make a rule", lambda: self.service.restore_rules(before))
        self.window.statusBar().showMessage("Rule saved: it places files in the next plans.", 6000)
        self._show_details()

    def change_rule(self, rule, chosen=None) -> None:
        """A rule gets another folder, label or word; files it places follow in the next plan."""
        if chosen is None:
            from .dialogs import RuleDialog

            dialog = RuleDialog(self, self.service, rule, self.flow.plan if self.flow else None)
            if not dialog.exec() or dialog.chosen is None:
                return
            chosen = dialog.chosen
        before = self.service.change_rule(rule, chosen)
        self.window._push_undo("Change a rule", lambda: self.service.restore_rules(before))
        self.window.statusBar().showMessage(f"{self.service.describe_rule(chosen)}. Used in the next plan.", 6000)
        self._show_details()

    def remove_rule(self, rule) -> None:
        before = self.service.remove_rule(rule)
        self.window._push_undo("Remove a rule", lambda: self.service.restore_rules(before))
        self._show_details()

    # ---------------------------------------------------------------- changing the plan
    def dropped(self, paths: list, folder: str) -> None:
        if self.flow is None or not folder:
            return
        planned = {_key(f) for f in self.flow.planned_folders()}
        moved_folders = [p for p in paths if _key(p) in planned]
        files = [p for p in paths if _key(p) not in planned and self.flow.plan.for_path(p) is not None]
        existing = [p for p in paths if os.path.isdir(p) and _key(p) not in planned]
        existing = [p for p in existing if not any(_key(p).startswith(_key(o) + os.sep) for o in existing)]
        try:
            for p in moved_folders:
                new = self.flow.move_planned_folder(p, folder)
                self.window._push_undo("Move a folder", lambda a=new, b=os.path.dirname(p):
                                       (self.flow.move_planned_folder(a, b), self.refresh_plan()))
        except ValueError as exc:
            QMessageBox.information(self, "Move a folder", str(exc))
        if files:
            before = self.flow.move_file(files, folder)
            self.window._push_undo("Change where files go", lambda: (self.flow.undo_move_file(before),
                                                                     self.refresh_plan()))
            self.window.statusBar().showMessage(
                f"{len(files):,} file{'s' if len(files) != 1 else ''} now go to {self.service.display(folder)}. "
                "SortZen learns from it.", 6000)
        if existing:
            self.move_folders(existing, folder)
            return
        self.refresh_plan()

    def move_folders(self, folders: list[str], target: str) -> None:
        """Folders go, as they are, into another folder when the files move; SortZen remembers it."""
        try:
            undo = self.flow.move_folders(folders, target)
        except ValueError as exc:
            QMessageBox.information(self, "Move folders", str(exc))
            return
        n = len(folders)
        self.window._push_undo("Move folders" if n > 1 else "Move a folder",
                               lambda: (self.flow.undo_move_folders(undo), self.refresh_plan()))
        self.window._report(f"{n:,} folder{'s' if n != 1 else ''} go{'es' if n == 1 else ''} into "
                            f"{self.service.display(target)} as {'they are' if n > 1 else 'it is'}. Nothing moves "
                            "until you click Move.")
        self.refresh_plan()

    def selected_folders(self) -> list[str]:
        """Existing folders chosen in the tree (not the folders added themselves)."""
        return [i.data(0, PATH) for i in self._selected()
                if i.data(0, KIND) in ("folder", "kept") and i.parent() is not None and os.path.isdir(i.data(0, PATH))]

    def too_many_folders(self, chosen: list[str] | None = None, name: str | None = None) -> None:
        """Gather folders into one new folder: the chosen ones, or the look-alike folders in the chosen folder."""
        if self.flow is None:
            return
        folders = chosen if chosen is not None else self.selected_folders()
        if chosen is None and not folders and self._selected_folder():
            folders = [self._selected_folder()]         # an added folder: the look-alike folders in it
        if len(folders) == 1:                           # one folder: the look-alike folders inside it
            inside = [f for f in self._children(folders[0]) if os.path.isdir(f)]
            groups = self.flow.look_alike(inside)
            folders = groups[0] if groups else inside
        if len(folders) < 2:
            QMessageBox.information(self, "Too many folders", "Select the folders to put together (Ctrl- or "
                                    "Shift-click), or a folder whose folders look alike, then click "
                                    "“Too many folders?” again. You can also drag folders onto another folder.")
            return
        parent = os.path.dirname(folders[0])
        if name is None:
            from .dialogs import GroupFoldersDialog

            dialog = GroupFoldersDialog(self, folders, parent, self.service.display)
            if not dialog.exec():
                return
            folders, name = dialog.chosen(), dialog.name()
        try:
            new, undo = self.flow.group_folders(folders, parent, name)
        except ValueError as exc:
            QMessageBox.information(self, "Too many folders", str(exc))
            return
        self.window._push_undo("Put folders together", lambda: (self.flow.undo_group_folders(undo), self.refresh_plan()))
        self.window._report(f"{len(folders):,} folders go into “{os.path.basename(new)}” (new). Nothing moves until "
                            "you click Move.")
        self.refresh_plan()

    def _children(self, folder: str) -> list[str]:
        """The folders in a folder: those in it now and those the plan moves into it."""
        found = {}
        item = self.items.get(_key(folder))
        if item is not None:
            for i in range(item.childCount()):
                if item.child(i).data(0, KIND) in ("folder", "kept"):
                    found[_key(item.child(i).data(0, PATH))] = item.child(i).data(0, PATH)
        try:
            for entry in os.scandir(folder):
                if entry.is_dir() and not entry.name.startswith((".", "$")):
                    found.setdefault(_key(entry.path), entry.path)
        except OSError:
            pass
        return sorted(found.values(), key=str.lower)

    def new_folder(self, name: str | None = None) -> str | None:
        parent = self._selected_folder() or next(iter(self.service.destination_folders()), None)
        if not parent:
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, "New folder", f"Name of the new folder in "
                                            f"{self.service.display(parent)}:")
            if not ok:
                return None
        try:
            folder = self.flow.new_folder(parent, name)
        except ValueError as exc:
            QMessageBox.information(self, "New folder", str(exc))
            return None
        self.window._push_undo("New folder", lambda: (self.flow.session.new_folders.remove(folder), self.refresh_plan()))
        self.refresh_plan()
        item = self.items.get(_key(folder))
        if item is not None:
            self.tree.clearSelection()
            item.setSelected(True)
            self.tree.scrollToItem(item)
        return folder

    def delete_folder(self) -> None:
        folder = self._selected_folder()
        if not folder:
            return
        try:
            undo = self.flow.delete_folder(folder)
        except ValueError as exc:
            QMessageBox.information(self, "Delete folder", str(exc))
            return
        self.window._push_undo("Delete folder", lambda: (self.flow.undo_delete_folder(undo), self.refresh_plan()))
        self.window.statusBar().showMessage(f"“{os.path.basename(folder)}” deleted from the plan; its files go to "
                                            f"{self.service.display(os.path.dirname(folder))}.", 6000)
        self.refresh_plan()

    # ---------------------------------------------------------------- footer
    def move(self) -> None:
        self._save_note()
        if self.flow is not None:
            self.window.session_move(self.flow)

    def show_rules(self) -> None:
        """Every rule in one list (Edit › Rules…); changed rules make the plan again, with the session kept."""
        before = [r.key for r in self.service.rules()] + [str(r.on) for r in self.service.rules()]
        self.window.show_settings("Rules")
        if [r.key for r in self.service.rules()] + [str(r.on) for r in self.service.rules()] != before:
            self.window.replan_review()

    def leave_here(self, paths: list[str]) -> None:
        if not paths:
            return
        undo = self.flow.leave_here(paths)
        self.window._push_undo("Leave where it is", lambda: (self.flow.undo_leave_here(undo), self.refresh_plan()))
        self.window._report(f"{len(paths):,} file{'s' if len(paths) != 1 else ''} stay where "
                            f"{'they are' if len(paths) != 1 else 'it is'}. SortZen remembers it.")
        self.refresh_plan()
