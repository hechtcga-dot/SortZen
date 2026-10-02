"""The To place tab: groups of files SortZen couldn't place, and its questions, each answered with any folder.

A group ("39 PDFs whose names are only numbers") goes to the folder picked or typed, in one go, and
can become a rule for files like them in future plans. A question can take one of its suggested
answers or any other folder.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QScrollArea, QVBoxLayout, QWidget,
)

MAX_NAMES_SHOWN = 60


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


class GroupCard(QFrame):
    def __init__(self, page, group, folders, recent):
        super().__init__(objectName="card")
        self.group = group
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)
        lean = f" · most lean towards {page.service.display(group.suggestion)}" if group.suggestion else \
            " · no folder fits them yet"
        col.addWidget(_label(group.title + lean, "cardTitle"))
        self.picker = FolderPicker(page.service, page.plan, folders, recent, group.suggestion)
        row = QHBoxLayout()
        row.addWidget(self.picker, 1)
        self.put = QPushButton("Put them there", objectName="primary")
        self.put.clicked.connect(self._put)
        row.addWidget(self.put)
        col.addLayout(row)
        under = QHBoxLayout()
        self.rule = QCheckBox("Also files like these in future plans (makes a rule)")
        under.addWidget(self.rule)
        under.addStretch(1)
        self.toggle = QPushButton(f"Show the {len(group.paths):,} files")
        self.toggle.setFlat(True)
        self.toggle.clicked.connect(self._toggle)
        under.addWidget(self.toggle)
        col.addLayout(under)
        names = [os.path.basename(p) for p in group.paths[:MAX_NAMES_SHOWN]]
        more = len(group.paths) - len(names)
        self.names = _label(", ".join(names) + (f" … and {more:,} more" if more > 0 else ""), "hint")
        self.names.hide()
        col.addWidget(self.names)
        self.page = page

    def _toggle(self) -> None:
        self.names.setVisible(not self.names.isVisible())
        self.toggle.setText(("Hide" if self.names.isVisible() else "Show") + f" the {len(self.group.paths):,} files")

    def _put(self) -> None:
        folder = self.picker.folder()
        if folder:
            self.page.place_group.emit(self.group, folder, self.rule.isChecked())


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

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.plan = None
        self.cards: list[QuestionCard] = []
        self.group_cards: list[GroupCard] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        self.title = _label("To place", "pageTitle", wrap=False)
        col.addWidget(self.title)
        col.addWidget(_label("Files SortZen couldn't place by itself, in groups you can send to one folder in one go, "
                             "and its questions. Pick a folder from the list, type a folder (or a name for a new "
                             "one), or browse. Everything is remembered and can be undone.", "hint"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        col.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.button = QPushButton("Save answers and update the plan", objectName="primary")
        self.button.clicked.connect(lambda: self.save.emit(self.answers()))
        row.addWidget(self.button)
        col.addLayout(row)

    def set_contents(self, plan, groups, questions, folders: list[str], recent: list[str]) -> None:
        self.plan = plan
        body = QWidget()
        col = QVBoxLayout(body)
        col.setSpacing(10)
        self.cards, self.group_cards = [], []
        if groups:
            col.addWidget(_label(f"Groups of files with no clear home ({len(groups)})", "sectionCaps"))
            for group in groups:
                card = GroupCard(self, group, folders, recent)
                self.group_cards.append(card)
                col.addWidget(card)
        if questions:
            col.addWidget(_label(f"Questions ({len(questions)})", "sectionCaps"))
            for q in questions:
                card = QuestionCard(self, q, folders, recent)
                self.cards.append(card)
                col.addWidget(card)
        if not groups and not questions:
            col.addWidget(_label("Nothing to place: SortZen settled everything on its own.", "hint"))
        col.addStretch(1)
        self.scroll.setWidget(body)
        self.button.setVisible(bool(questions))

    def answers(self) -> dict:
        return {card.question.key: card.answer() for card in self.cards}

    def count(self) -> int:
        return len(self.group_cards) + sum(1 for c in self.cards if c.question.answer is None)
