"""The file list of the cataloguing wizard: the files SortZen isn't sure about, labelled by users, and its questions.

Users make labels ("Work", "Taxes", "Photo session"), select files (several at once, or a whole group
such as "39 PDFs whose names are only numbers") and click a label. A file's labels together choose its
folder (Work and Taxes: Work/Taxes), and SortZen suggests labels for files like them. Users can also say
a file is similar to, or different from, another file: that makes SortZen surer or less sure, and
never moves anything by itself. A group can go to any folder in one go, and become a rule. A question
can take one of its suggested answers or any other folder.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QRadioButton,
    QScrollArea, QSplitter, QTreeWidget, QVBoxLayout, QWidget,
)

from .sortable import SortItem, natural

PATH = Qt.ItemDataRole.UserRole
MAX_PICKED_SHOWN = 300


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text, objectName=name) if name else QLabel(text)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class FolderPicker(QWidget):
    """Pick a folder from the list (recent ones first), type one, or browse for one."""

    changed = Signal()

    def __init__(self, service, plan, folders: list[str], recent: list[str], preset: str | None = None):
        super().__init__()
        self.service, self.plan = service, plan
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.box = QComboBox()
        self.box.setEditable(True)
        self.box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.box.setMinimumContentsLength(30)
        self.box.lineEdit().setPlaceholderText("Pick a folder, or type a name for a new one")
        seen = set()
        for folder in [*recent, *folders]:
            key = os.path.normcase(folder)
            if key in seen:
                continue
            seen.add(key)
            self.box.addItem(service.display(folder), folder)
        self.box.setEditText(service.display(preset) if preset else "")
        self.box.editTextChanged.connect(lambda _: self.changed.emit())
        row.addWidget(self.box, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder")
        if folder:
            self.box.setEditText(self.service.display(os.path.abspath(folder)) or folder)

    def folder(self) -> str | None:
        text = self.box.currentText().strip()
        index = self.box.findText(text)
        if index >= 0:
            return self.box.itemData(index)
        return self.service.resolve_folder(text, self.plan)


def label_menus(menu: QMenu, service, paths: list[str], emit, new_label=None) -> None:
    """"Give a label" and "Take a label away" for the chosen files, whichever labels each of them has.
    ``emit(paths, label, on)`` makes the change."""
    names = service.labels()
    have = {name: sum(1 for p in paths if name in service.labels_of(p)) for name in names}
    n = len(paths)
    give = menu.addMenu("Give a label")
    for name in names:
        if have[name] < n:
            give.addAction(name + (f"  ({have[name]:,} of {n:,} have it)" if have[name] else ""),
                           lambda x=name: emit(paths, x, True))
    if new_label is not None:
        give.addSeparator()
        give.addAction("New label…", new_label)
    give.setEnabled(bool(give.actions()))
    take = menu.addMenu("Take a label away")
    for name in names:
        if have[name]:
            take.addAction(name + (f"  ({have[name]:,} of {n:,} have it)" if have[name] < n else ""),
                           lambda x=name: emit(paths, x, False))
    take.setEnabled(bool(take.actions()))


class FlowLayout(QLayout):
    """Buttons in rows that wrap when the window is narrow."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


class GroupDialog(QDialog):
    """Send a whole group to one folder, and, when ticked, files like them in future plans."""

    def __init__(self, parent, service, plan, group, folders, recent):
        super().__init__(parent)
        self.setWindowTitle("Put them in a folder")
        self.setMinimumWidth(620)
        col = QVBoxLayout(self)
        lean = f"Most lean towards {service.display(group.suggestion)}." if group.suggestion else \
            "No folder fits them yet."
        col.addWidget(_label(f"{group.title}. {lean}"))
        self.picker = FolderPicker(service, plan, folders, recent, group.suggestion)
        col.addWidget(self.picker)
        self.rule = QCheckBox("Also files like these in future plans (makes a rule)")
        col.addWidget(self.rule)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Put them there", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)


class FilePickerDialog(QDialog):
    """Pick the file the selected files are similar to, or different from: type part of its name."""

    def __init__(self, parent, files: list[str], display, title: str, prompt: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 460)
        self.files, self.display, self.chosen = files, display, None
        col = QVBoxLayout(self)
        col.addWidget(_label(prompt))
        self.search = QLineEdit(placeholderText="Type part of the file's name")
        self.search.textChanged.connect(self._fill)
        col.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        col.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._fill("")

    def _fill(self, text: str) -> None:
        words = text.lower().split()
        self.list.clear()
        shown = 0
        for path in self.files:
            if all(w in os.path.basename(path).lower() for w in words):
                item = QListWidgetItem(f"{os.path.basename(path)}    ·    {self.display(os.path.dirname(path))}")
                item.setData(PATH, path)
                self.list.addItem(item)
                shown += 1
                if shown >= MAX_PICKED_SHOWN:
                    break
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.chosen = item.data(PATH)
            self.accept()


class QuestionCard(QFrame):
    ANOTHER = 10_000

    def __init__(self, page, question, folders, recent):
        super().__init__(objectName="card")
        self.question = question
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.addWidget(_label(question.text))
        self.buttons = QButtonGroup(self)
        for i, choice in enumerate(question.choices):
            button = QRadioButton(choice.label)
            button.setChecked(question.answer == i)
            self.buttons.addButton(button, i)
            col.addWidget(button)
        row = QHBoxLayout()
        another = QRadioButton("Another folder:")
        self.buttons.addButton(another, self.ANOTHER)
        row.addWidget(another)
        self.picker = FolderPicker(page.service, page.plan, folders, recent)
        self.picker.changed.connect(lambda: another.setChecked(True))
        row.addWidget(self.picker, 1)
        col.addLayout(row)

    def answer(self):
        chosen = self.buttons.checkedId()
        if chosen == self.ANOTHER:
            return self.picker.folder()
        return chosen if chosen >= 0 else None


class ToPlacePage(QWidget):
    place_group = Signal(object, str, bool)      # group, folder, also make a rule
    save = Signal(dict)                          # question key -> choice number, a folder, or None
    label = Signal(list, str, bool)              # files, label, on or off
    new_label = Signal(list)                     # make a label, then give it to these files
    edit_label = Signal(str, str)                # label, "rename" / "up" / "down" / "remove"
    pair = Signal(list, str)                     # files, "similar" or "different"
    forget_pairs = Signal(list)
    put_in_folder = Signal(list)                 # files to send to a folder chosen from a list
    update_plan = Signal()
    open_path = Signal(str)
    confirm = Signal(list)                       # the labels shown for these files look right
    note_file = Signal(str)                      # write a note about one file
    keep_together = Signal(str)                  # a folder whose files move together
    delete_files = Signal(list)                  # files to move into the "To delete" folder

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.plan = None
        self.groups = []
        self.cards: list[QuestionCard] = []
        self.label_buttons: dict[str, QPushButton] = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        self.title = _label("To place", "pageTitle", wrap=False)
        col.addWidget(self.title)
        col.addWidget(_label("Give files labels such as Work, Taxes or Photo session: select files (Shift- or "
                             "Ctrl-click, or a whole group) and click a label. Labels to the left count most. SortZen "
                             "guesses labels for the rest and learns which folders they belong in. "
                             "Right-click to say a file is similar to, or different from, another file; that teaches "
                             "SortZen and moves nothing. Everything is remembered and can be undone.", "hint"))
        bar = QWidget(objectName="labelBar")
        bar.setStyleSheet("#labelBar { background: transparent; }")
        self.label_bar = FlowLayout(bar)
        col.addWidget(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Labels", "SortZen's guess", "Why"])
        for column, width in enumerate((300, 220, 280)):
            self.tree.setColumnWidth(column, width)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda item, _: item.data(0, PATH) and self.open_path.emit(item.data(0, PATH)))
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.tree)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(lambda: self.selected_paths() and self.delete_files.emit(self.selected_paths()))
        split.addWidget(self.tree)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        split.addWidget(self.scroll)
        split.setSizes([480, 220])
        col.addWidget(split, 1)
        row = QHBoxLayout()
        self.selection = _label("", "muted", wrap=False)
        row.addWidget(self.selection, 1)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip("Move the selected files into a “To delete” folder now (Delete key). Nothing is "
                                      "deleted until you delete that folder; Undo puts them back.")
        self.delete_button.clicked.connect(lambda: self.selected_paths() and
                                           self.delete_files.emit(self.selected_paths()))
        row.addWidget(self.delete_button)
        self.looks_right = QPushButton("Looks right")
        self.looks_right.setToolTip("The labels shown for the selected files are right: SortZen learns from them")
        self.looks_right.clicked.connect(lambda: self.selected_paths() and self.confirm.emit(self.selected_paths()))
        row.addWidget(self.looks_right)
        self.refresh_button = QPushButton("Update the plan")
        self.refresh_button.setToolTip("Make the plan again with your labels and what you said about similar files")
        self.refresh_button.clicked.connect(self.update_plan)
        row.addWidget(self.refresh_button)
        self.button = QPushButton("Save answers and update the plan", objectName="primary")
        self.button.clicked.connect(lambda: self.save.emit(self.answers()))
        row.addWidget(self.button)
        col.addLayout(row)
        self._selection_changed()

    # ---------------------------------------------------------------- filling
    def set_contents(self, plan, groups, questions, folders: list[str], recent: list[str]) -> None:
        self.plan, self.groups, self.folders, self.recent = plan, groups, folders, recent
        self._fill_labels()
        self._fill_files()
        body = QWidget()
        q = QVBoxLayout(body)
        q.setSpacing(10)
        self.cards = []
        if questions:
            q.addWidget(_label(f"Questions ({len(questions)})", "sectionCaps"))
            for question in questions:
                card = QuestionCard(self, question, folders, recent)
                self.cards.append(card)
                q.addWidget(card)
        q.addStretch(1)
        self.scroll.setWidget(body)
        self.scroll.setVisible(bool(questions))
        self.button.setVisible(bool(questions))

    def _fill_labels(self) -> None:
        while self.label_bar.count():
            widget = self.label_bar.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.label_buttons = {}
        caption = _label("Labels:", "sectionCaps", wrap=False)
        caption.setMinimumHeight(QPushButton("X").sizeHint().height())
        caption.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.label_bar.addWidget(caption)
        for name in self.service.labels():
            button = QPushButton(name)
            button.setToolTip("Click to give the selected files this label, click again to take it away. Right-"
                              "click to give it or take it away whichever files have it, or to rename, move or "
                              "remove it. Labels to the left count more.")
            button.clicked.connect(lambda _=False, n=name: self.toggle_label(n))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos, n=name, b=button: self._label_menu(n, b, pos))
            self.label_bar.addWidget(button)
            self.label_buttons[name] = button
        new = QPushButton("+ New label…")
        new.clicked.connect(lambda: self.new_label.emit(self.selected_paths()))
        self.label_bar.addWidget(new)

    def _fill_files(self) -> None:
        self.tree.clear()
        self.items: dict[str, SortItem] = {}
        if self.plan is None:
            return
        suggestions = {os.path.normcase(s.path): s for s in self.service.unsure_files(self.plan)}
        labelled = {os.path.normcase(k) for k in self.service.users_labels()}
        placed = set()
        for group in self.groups:
            lean = f" · most lean towards {self.service.display(group.suggestion)}" if group.suggestion else ""
            parent = self._heading(group.title + lean, group)
            for path in group.paths:
                s = suggestions.get(os.path.normcase(path))
                if s is not None:
                    self._file_row(parent, s)
                    placed.add(os.path.normcase(path))
        rest = [s for k, s in suggestions.items() if k not in placed and k not in labelled]
        if rest:
            parent = self._heading(f"Other files SortZen isn't sure about ({len(rest):,})")
            for s in rest:
                self._file_row(parent, s)
        done = [s for k, s in suggestions.items() if k not in placed and k in labelled]
        if done:
            parent = self._heading(f"Labelled ({len(done):,})")
            for s in done:
                self._file_row(parent, s)
        self.tree.expandAll()
        self.refresh_rows()

    def _heading(self, text: str, group=None) -> SortItem:
        item = SortItem(self.tree, [text])
        item.group = group
        item.setFirstColumnSpanned(True)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        return item

    def _file_row(self, parent, s) -> None:
        item = SortItem(parent, [os.path.basename(s.path)])
        item.setData(0, PATH, s.path)
        item.setToolTip(0, s.path)
        item.set_key(0, natural(os.path.basename(s.path)))
        item.suggestion = s
        self.items[os.path.normcase(s.path)] = item

    def refresh_rows(self) -> None:
        """Labels, folders and reasons as they are now (after labelling, without a new plan)."""
        if self.plan is None:
            return
        muted = self.palette().placeholderText()
        for item in self.items.values():
            s = item.suggestion
            guesses = self.service.label_guesses(s.path)
            mine = bool(guesses) and guesses[0][2] == "You"
            item.setText(1, ", ".join(g[0] if mine else f"{g[0]}? {g[1]}%" for g in guesses))
            item.setForeground(1, self.palette().text() if mine else muted)
            item.setToolTip(1, "\n".join(f"{g[0]}: {g[1]}% ({g[2]})" for g in guesses))
            item.setText(2, f"{s.percent}% · {self.service.display(s.destination)}" if s.destination else "No folder fits")
            item.setToolTip(2, item.text(2))
            said = self.service.pairs_of(s.path)
            why = [f"You said: {'similar to' if kind == 'similar' else 'different from'} “{os.path.basename(other)}”"
                   for kind, other in said]
            note = self.service.file_note(s.path)
            if note:
                why.insert(0, f"Your note: “{note[:60]}”")
            why += [r.text for r in s.reasons[:2] if not r.text.startswith(("You said", "Your note"))]
            item.setText(3, "; ".join(why))
            item.setToolTip(3, "\n".join(why))
        self._selection_changed()

    # ---------------------------------------------------------------- choosing
    def selected_paths(self) -> list[str]:
        """The selected files, with every file of a selected group."""
        found = []
        for item in self.tree.selectedItems():
            if item.data(0, PATH):
                found.append(item.data(0, PATH))
            else:
                found += [item.child(i).data(0, PATH) for i in range(item.childCount())]
        return list(dict.fromkeys(found))

    def _selection_changed(self) -> None:
        paths = self.selected_paths()
        self.selection.setText(f"{len(paths):,} file{'s' if len(paths) != 1 else ''} selected" if paths else
                               "Select files, then click a label")
        self.looks_right.setEnabled(bool(paths))
        self.delete_button.setEnabled(bool(paths))
        for name, button in self.label_buttons.items():
            some = sum(1 for p in paths if name in self.service.labels_of(p))
            have = bool(paths) and some == len(paths)
            button.setText(f"{name}  {some:,}/{len(paths):,}" if 0 < some < len(paths) else name)
            button.setObjectName("primary" if have else "")
            button.style().unpolish(button)
            button.style().polish(button)

    def toggle_label(self, name: str) -> None:
        paths = self.selected_paths()
        if paths:
            on = not all(name in self.service.labels_of(p) for p in paths)
            self.label.emit(paths, name, on)

    def _label_menu(self, name: str, button, pos) -> None:
        menu = QMenu(self)
        paths = self.selected_paths()
        if paths:
            some = sum(1 for p in paths if name in self.service.labels_of(p))
            menu.addAction(f"Give it to the {len(paths):,} selected files", lambda: self.label.emit(paths, name, True))
            take = menu.addAction(f"Take it away from the selected files ({some:,} have it)",
                                  lambda: self.label.emit(paths, name, False))
            take.setEnabled(bool(some))
            menu.addSeparator()
        menu.addAction("Rename…", lambda: self.edit_label.emit(name, "rename"))
        menu.addAction("Move left (counts more)", lambda: self.edit_label.emit(name, "up"))
        menu.addAction("Move right (counts less)", lambda: self.edit_label.emit(name, "down"))
        menu.addAction("Remove the label", lambda: self.edit_label.emit(name, "remove"))
        menu.exec(button.mapToGlobal(pos))

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.tree.setCurrentItem(item)
        paths = self.selected_paths()
        if not paths:
            return
        some = f"these {len(paths):,} files" if len(paths) != 1 else "this file"
        menu = QMenu(self)
        menu.addAction("Looks right (keep the labels shown)", lambda: self.confirm.emit(paths))
        label_menus(menu, self.service, paths, self.label.emit, lambda: self.new_label.emit(paths))
        menu.addAction(f"Similar to another file…", lambda: self.pair.emit(paths, "similar"))
        menu.addAction(f"Different from another file…", lambda: self.pair.emit(paths, "different"))
        if any(self.service.pairs_of(p) for p in paths):
            menu.addAction("Forget what I said about similar files", lambda: self.forget_pairs.emit(paths))
        if len(paths) == 1:
            menu.addAction("Note about this file…", lambda: self.note_file.emit(paths[0]))
        folder = os.path.dirname(paths[0])
        if all(os.path.dirname(p) == folder for p in paths):
            menu.addAction(f"Keep “{os.path.basename(folder)}” together (move it as it is)",
                           lambda: self.keep_together.emit(folder))
        menu.addSeparator()
        group = getattr(item, "group", None)
        if group is not None and not item.data(0, PATH):
            menu.addAction(f"Put all {len(group.paths):,} in a folder…", lambda: self._put_group(group))
        else:
            menu.addAction(f"Put {some} in a folder…", lambda: self.put_in_folder.emit(paths))
        menu.addAction(f"Delete {some}… (to the “To delete” folder)", lambda: self.delete_files.emit(paths))
        if len(paths) == 1 and item.data(0, PATH):
            menu.addAction("Open", lambda: self.open_path.emit(paths[0]))
            menu.addAction("Open the folder it's in", lambda: self.open_path.emit(os.path.dirname(paths[0])))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _put_group(self, group) -> None:
        dialog = GroupDialog(self, self.service, self.plan, group, self.folders, self.recent)
        if dialog.exec() and dialog.picker.folder():
            self.place_group.emit(group, dialog.picker.folder(), dialog.rule.isChecked())

    def answers(self) -> dict:
        return {card.question.key: card.answer() for card in self.cards}

    def count(self) -> int:
        unlabelled = sum(1 for k, item in getattr(self, "items", {}).items()
                         if not self.service.labels_of(item.suggestion.path, 70))
        return unlabelled + sum(1 for c in self.cards if c.question.answer is None)
