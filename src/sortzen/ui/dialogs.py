"""Small dialogs: how to sort a folder, and choosing a destination."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QRadioButton, QVBoxLayout,
)

from ..engine.planner import SORT_OUT, TIDY

MODE_TEXT = {
    SORT_OUT: ("Sort into other folders", "For folders like Downloads: its files and subfolders go to your "
                                          "destination folders."),
    TIDY: ("Tidy this folder", "For folders like a cloud drive: organised subfolders stay where they are; loose "
                               "files and messy subfolders are sorted into them."),
}


def _hint(text: str) -> QLabel:
    label = QLabel(text, objectName="hint")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ModeDialog(QDialog):
    """Asks how a newly added folder should be sorted."""

    def __init__(self, parent, folder: str, mode: str = SORT_OUT):
        super().__init__(parent)
        self.setWindowTitle("How should SortZen sort this folder?")
        col = QVBoxLayout(self)
        col.addWidget(QLabel(f"How should SortZen sort “{os.path.basename(folder) or folder}”?", objectName="cardTitle"))
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, (title, hint) in MODE_TEXT.items():
            button = QRadioButton(title)
            button.setChecked(key == mode)
            self.group.addButton(button)
            self.buttons[key] = button
            col.addWidget(button)
            col.addWidget(_hint(hint))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)

    def mode(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())


class DestinationDialog(QDialog):
    """Pick a destination from the folders SortZen knows, or browse for another."""

    def __init__(self, parent, choices: list[str], display, title: str = "Choose a destination"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 520)
        self.chosen: str | None = None
        col = QVBoxLayout(self)
        col.addWidget(_hint("SortZen remembers your choice and learns from it for similar files. Nothing moves "
                            "until you use “Move ticked…” and confirm."))
        self.search = QLineEdit(placeholderText="Type to filter folders")
        col.addWidget(self.search)
        self.list = QListWidget()
        for folder in choices:
            item = QListWidgetItem(display(folder))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(folder)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        col.addWidget(self.list, 1)
        self.search.textChanged.connect(self._filter)
        browse = QPushButton("Another folder…")
        browse.clicked.connect(self._browse)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.addButton(browse, QDialogButtonBox.ButtonRole.ActionRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)

    def _filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text not in item.text().lower())

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder")
        if folder:
            self.chosen = os.path.abspath(folder)
            super().accept()

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            super().accept()
