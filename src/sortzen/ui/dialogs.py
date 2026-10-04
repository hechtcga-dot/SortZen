"""Small dialogs: how to sort a folder, and choosing a destination."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
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
    """Pick a destination: a recently chosen folder, any folder SortZen knows, a new folder, or another one.

    ``rename(folder)`` renames a folder and returns its new path (None when nothing changed).
    """

    def __init__(self, parent, choices: list[str], display, title: str = "Choose a destination",
                 recent: list[str] = (), rename=None, note=lambda folder: ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 600)
        self.chosen: str | None = None
        self.display = display
        self.rename = rename
        self.note = note
        col = QVBoxLayout(self)
        col.addWidget(_hint("SortZen remembers your choice and learns from it for similar files. Nothing moves "
                            "until you use “Move ticked…” and confirm."))
        self.recent = QListWidget()
        if recent:
            col.addWidget(QLabel("Recently chosen", objectName="cardTitle"))
            self._fill(self.recent, recent)
            self.recent.setMaximumHeight(min(170, 26 * len(recent) + 8))
            self.recent.itemDoubleClicked.connect(lambda item: self._pick(item))
            self.recent.itemClicked.connect(lambda _: self.list.clearSelection())
            col.addWidget(self.recent)
            col.addWidget(QLabel("All folders", objectName="cardTitle"))
        self.search = QLineEdit(placeholderText="Type to filter folders")
        col.addWidget(self.search)
        self.list = QListWidget()
        self._fill(self.list, choices)
        self.list.itemDoubleClicked.connect(lambda item: self._pick(item))
        self.list.itemClicked.connect(lambda _: self.recent.clearSelection())
        col.addWidget(self.list, 1)
        self.search.textChanged.connect(self._filter)
        new = QPushButton("New folder…")
        new.setToolTip("A new folder inside the selected one; it is made when the files move")
        new.clicked.connect(self._new_folder)
        rename_button = QPushButton("Rename…")
        rename_button.setToolTip("Give the selected folder a new name")
        rename_button.clicked.connect(self._rename)
        rename_button.setVisible(rename is not None)
        browse = QPushButton("Another folder…")
        browse.clicked.connect(self._browse)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for button in (new, rename_button, browse):
            box.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)

    def _fill(self, widget: QListWidget, folders) -> None:
        widget.clear()
        for folder in folders:
            text = self.note(folder)
            item = QListWidgetItem(self.display(folder) + ("" if os.path.isdir(folder) else "  (new folder)")
                                   + (f"  —  {text[:70]}" if text else ""))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(folder + (f"\n{text}" if text else ""))
            widget.addItem(item)

    def _filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text not in item.text().lower())

    def selected_folder(self) -> str | None:
        for widget in (self.recent, self.list):
            item = widget.currentItem()
            if item is not None and item.isSelected() and not item.isHidden():
                return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _pick(self, item) -> None:
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        super().accept()

    def _new_folder(self) -> None:
        parent = self.selected_folder()
        if parent is None:
            QMessageBox.information(self, self.windowTitle(), "Select the folder to make the new folder in first.")
            return
        name, ok = QInputDialog.getText(self, "New folder", f"Name of the new folder inside “{os.path.basename(parent)}”:")
        name = (name or "").strip().rstrip(". ")
        if not ok or not name:
            return
        if set(name) & set('\\/:*?"<>|'):
            QMessageBox.warning(self, "New folder", 'Folder names can\'t contain \\ / : * ? " < > |')
            return
        self.chosen = os.path.join(parent, name)
        super().accept()

    def _rename(self) -> None:
        folder = self.selected_folder()
        if folder is None:
            QMessageBox.information(self, self.windowTitle(), "Select the folder to rename first.")
            return
        new = self.rename(folder)
        if not new:
            return
        for widget in (self.recent, self.list):
            for i in range(widget.count()):
                item = widget.item(i)
                old = item.data(Qt.ItemDataRole.UserRole)
                if os.path.normcase(old) == os.path.normcase(folder) or \
                        os.path.normcase(old).startswith(os.path.normcase(folder) + os.sep):
                    path = new + old[len(folder):]
                    item.setData(Qt.ItemDataRole.UserRole, path)
                    item.setText(self.display(path) + ("" if os.path.isdir(path) else "  (new folder)"))
                    item.setToolTip(path)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder")
        if folder:
            self.chosen = os.path.abspath(folder)
            super().accept()

    def accept(self) -> None:
        folder = self.selected_folder()
        if folder:
            self.chosen = folder
            super().accept()


class MissingFoldersDialog(QDialog):
    """A loaded profile names folders this PC doesn't have: point each at its new place, or leave it out."""

    def __init__(self, parent, missing: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Some folders aren't on this PC")
        self.resize(620, 360)
        self.moved: dict[str, str] = {}
        self.missing = list(missing)
        col = QVBoxLayout(self)
        col.addWidget(_hint("These folders from the profile can't be found here. Choose where each one is on this "
                            "PC, or leave it out: its answers and choices then simply aren't used."))
        self.list = QListWidget()
        col.addWidget(self.list, 1)
        choose = QPushButton("Choose where it is now…")
        choose.clicked.connect(self._choose)
        self.list.itemDoubleClicked.connect(lambda _: self._choose())
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.addButton(choose, QDialogButtonBox.ButtonRole.ActionRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for folder in self.missing:
            new = self.moved.get(folder)
            item = QListWidgetItem(f"{folder}  →  {new}" if new else f"{folder}  (left out)")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def set_new_place(self, folder: str, new: str) -> None:
        self.moved[folder] = os.path.abspath(new)
        self._fill()

    def _choose(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        folder = item.data(Qt.ItemDataRole.UserRole)
        new = QFileDialog.getExistingDirectory(self, f"Where is “{os.path.basename(folder)}” on this PC?")
        if new:
            self.set_new_place(folder, new)

    @property
    def dropped(self) -> list[str]:
        return [f for f in self.missing if f not in self.moved]


class LabelChoiceDialog(QDialog):
    """The labels the AI suggested, each with a tick box; ticked ones are added to users' list."""

    def __init__(self, parent, found: list[tuple[str, str]], existing: list[str]):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem

        super().__init__(parent)
        self.setWindowTitle("Labels the AI suggests")
        self.resize(520, 440)
        col = QVBoxLayout(self)
        intro = QLabel("Untick any you don't want; you can rename or remove labels later. Labels you already have "
                       "are kept.")
        intro.setWordWrap(True)
        col.addWidget(intro)
        self.list = QListWidget()
        have = {x.lower() for x in existing}
        for name, why in found:
            item = QListWidgetItem(f"{name}" + (f"  ·  {why}" if why else ""))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if name.lower() in have else Qt.CheckState.Checked)
            self.list.addItem(item)
        col.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def chosen(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class RuleDialog(QDialog):
    """Change a rule before or after it is made: the folder its files go to, and its label or name word."""

    def __init__(self, parent, service, rule, plan=None, title: str = "Change the rule"):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QHBoxLayout

        from .to_place_page import FolderPicker

        self.service, self.rule, self.chosen = service, rule, None
        self.setWindowTitle(title)
        self.resize(620, 260)
        col = QVBoxLayout(self)
        row = QHBoxLayout()
        self.label = self.word = None
        if rule.label:
            row.addWidget(QLabel("Files labelled"))
            self.label = QComboBox()
            self.label.setEditable(True)
            self.label.addItems(service.labels())
            self.label.setEditText(rule.label)
            self.label.setAccessibleName("Label")
            self.label.editTextChanged.connect(self._preview)
            row.addWidget(self.label, 1)
        elif not rule.shape:
            row.addWidget(QLabel("Names with the word"))
            self.word = QLineEdit(rule.word)
            self.word.setAccessibleName("Word in the name")
            self.word.textChanged.connect(self._preview)
            row.addWidget(self.word, 1)
        else:
            row.addWidget(QLabel(rule.describe(service.display).split(" go to ")[0]))
            row.addStretch(1)
        col.addLayout(row)
        col.addWidget(QLabel("go to"))
        self.folder = FolderPicker(service, plan, service.destination_choices(plan), service.recent_destinations(plan),
                                   rule.destination)
        self.folder.changed.connect(self._preview)
        col.addWidget(self.folder)
        col.addWidget(_hint("Pick a folder, or type one such as “Downloads/Program projects/Tide Log”. A folder that "
                            "doesn't exist yet is made when files first move into it."))
        self.preview = QLabel(objectName="cardTitle")
        self.preview.setWordWrap(True)
        col.addWidget(self.preview)
        col.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Save the rule")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)
        self._preview()

    def _edited(self):
        return self.service.edited_rule(self.rule, self.folder.folder() or "",
                                        self.label.currentText() if self.label else "",
                                        self.word.text() if self.word else "")

    def _preview(self, *_) -> None:
        try:
            self.preview.setText(self.service.describe_rule(self._edited()) + ".")
        except ValueError as exc:
            self.preview.setText(str(exc))

    def accept(self) -> None:
        try:
            self.chosen = self._edited()
        except ValueError as exc:
            QMessageBox.information(self, self.windowTitle(), str(exc))
            return
        super().accept()
