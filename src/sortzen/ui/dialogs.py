"""Small dialogs: how to sort a folder, and choosing a destination."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget,
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
    """Make or change a rule: what the files have in common (any of: a label, text in the name, a kind of file,
    an ending, the folder they are in), where they go (with a folder for each year or month if wanted), a name,
    and whether it is on. A preview shows which files of the plan it places."""

    def __init__(self, parent, service, rule=None, plan=None, title: str = "Change the rule", destination: str = ""):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout

        from ..engine.rules import Rule, KINDS
        from .to_place_page import FolderPicker

        rule = rule or Rule("", destination or "")
        self.service, self.rule, self.plan, self.chosen = service, rule, plan, None
        self.setWindowTitle(title)
        self.resize(720, 620)
        col = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name", objectName="fieldLabel"))
        self.name = QLineEdit(rule.name, placeholderText="Optional, for example: Tax slips")
        self.name.setAccessibleName("Name of the rule")
        name_row.addWidget(self.name, 1)
        col.addLayout(name_row)

        col.addWidget(QLabel("Files that…", objectName="cardTitle"))
        box = QFrame(objectName="card")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setColumnStretch(1, 1)
        choices = service.destination_choices(plan)
        recent = service.recent_destinations(plan)

        def condition(row: int, text: str, widget, on: bool):
            check = QCheckBox(text, checked=on)
            grid.addWidget(check, row, 0)
            grid.addWidget(widget, row, 1)
            widget.setEnabled(on)
            check.toggled.connect(widget.setEnabled)
            check.toggled.connect(self._changed)
            return check

        self.label = QComboBox()
        self.label.setEditable(True)
        self.label.addItems(service.labels())
        self.label.setEditText(rule.label)
        self.label.setAccessibleName("Label")
        self.use_label = condition(0, "have the label", self.label, bool(rule.label))
        text_row = QWidget()
        tr = QHBoxLayout(text_row)
        tr.setContentsMargins(0, 0, 0, 0)
        self.text = QLineEdit(rule.word or rule.contains, placeholderText="For example: T4, invoice, IMG_")
        self.text.setAccessibleName("Text in the name")
        self.whole_word = QCheckBox("as a whole word", checked=bool(rule.word))
        tr.addWidget(self.text, 1)
        tr.addWidget(self.whole_word)
        self.use_text = condition(1, "have in their name", text_row, bool(rule.word or rule.contains))
        self.kind = QComboBox()
        for key, plural in KINDS.items():
            self.kind.addItem(plural[0].upper() + plural[1:], key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(rule.kind)))
        self.kind.setAccessibleName("Kind of file")
        self.use_kind = condition(2, "are", self.kind, bool(rule.kind))
        self.ext = QLineEdit(rule.ext, placeholderText=".pdf")
        self.ext.setAccessibleName("Ending")
        self.use_ext = condition(3, "end in", self.ext, bool(rule.ext))
        self.inside = FolderPicker(service, plan, [f["path"] for f in service.source_folders()] + choices, [],
                                   rule.inside or None)
        self.use_inside = condition(4, "are in the folder", self.inside, bool(rule.inside))
        self.use_shape = None
        if rule.shape:
            what = "names that are only numbers" if rule.shape == "#" else f"names like “{rule.example or rule.shape}”"
            self.use_shape = QCheckBox(f"have {what}", checked=True)
            self.use_shape.toggled.connect(self._changed)
            grid.addWidget(self.use_shape, 5, 0, 1, 2)
        col.addWidget(box)
        col.addWidget(_hint("Every ticked condition must fit. Typing in a box ticks it."))

        col.addWidget(QLabel("go to", objectName="cardTitle"))
        self.folder = FolderPicker(service, plan, choices, recent, rule.destination or None)
        col.addWidget(self.folder)
        by_row = QHBoxLayout()
        self.use_by = QCheckBox("in a folder for each", checked=bool(rule.by))
        self.by = QComboBox()
        self.by.addItem("year (from the name, or when the file was saved)", "year")
        self.by.addItem("month (when the file was saved)", "month")
        self.by.setCurrentIndex(1 if rule.by == "month" else 0)
        self.by.setEnabled(bool(rule.by))
        self.use_by.toggled.connect(self.by.setEnabled)
        by_row.addWidget(self.use_by)
        by_row.addWidget(self.by, 1)
        col.addLayout(by_row)
        col.addWidget(_hint("Pick a folder, or type one such as “Downloads/Program projects/Tide Log”. A folder that "
                            "doesn't exist yet is made when files first move into it."))
        self.on = QCheckBox("This rule is on", checked=rule.on)
        col.addWidget(self.on)
        self.preview = QLabel(objectName="cardTitle")
        self.preview.setWordWrap(True)
        col.addWidget(self.preview)
        self.examples = _hint("")
        col.addWidget(self.examples)
        col.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save the rule")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._preview)
        for check, widget in ((self.use_label, self.label), (self.use_ext, self.ext)):
            signal = widget.editTextChanged if hasattr(widget, "editTextChanged") else widget.textChanged
            signal.connect(lambda _=None, c=check: (c.setChecked(True), self._changed()))
        self.text.textChanged.connect(lambda _: (self.use_text.setChecked(True), self._changed()))
        self.kind.currentIndexChanged.connect(lambda _: self._changed())
        self.inside.changed.connect(lambda: (self.use_inside.setChecked(True), self._changed()))
        for widget in (self.whole_word, self.use_by, self.on):
            widget.toggled.connect(self._changed)
        self.by.currentIndexChanged.connect(lambda _: self._changed())
        self.folder.changed.connect(self._changed)
        self.name.textChanged.connect(self._changed)
        self._preview()

    def _changed(self, *_) -> None:
        self._timer.start()

    def _edited(self):
        keep_shape = self.use_shape is not None and self.use_shape.isChecked()
        return self.service.build_rule(
            self.folder.folder() or "",
            label=self.label.currentText() if self.use_label.isChecked() else "",
            text=self.text.text() if self.use_text.isChecked() else "",
            whole_word=self.whole_word.isChecked(),
            kind=self.kind.currentData() if self.use_kind.isChecked() else "",
            ext=self.ext.text() if self.use_ext.isChecked() else "",
            inside=(self.inside.folder() or "") if self.use_inside.isChecked() else "",
            by=self.by.currentData() if self.use_by.isChecked() else "",
            name=self.name.text(), on=self.on.isChecked(),
            shape=self.rule.shape if keep_shape else "", example=self.rule.example if keep_shape else "")

    def _preview(self) -> None:
        try:
            rule = self._edited()
        except ValueError as exc:
            self.preview.setText(str(exc))
            self.examples.setText("")
            return
        self.preview.setText(self.service.describe_rule(rule) + ".")
        if self.plan is None:
            self.examples.setText("")
            return
        found = self.service.rule_matches(rule, self.plan)
        names = ", ".join(os.path.basename(p) for p in found[:6]) + (", …" if len(found) > 6 else "")
        self.examples.setText(f"In this plan it places {len(found):,} file{'s' if len(found) != 1 else ''}"
                              + (f": {names}" if found else ". Files you placed yourself keep your choice."))

    def accept(self) -> None:
        try:
            self.chosen = self._edited()
        except ValueError as exc:
            QMessageBox.information(self, self.windowTitle(), str(exc))
            return
        super().accept()


class GroupFoldersDialog(QDialog):
    """Too many folders: which of them go together into one new folder, and its name."""

    def __init__(self, parent, folders: list[str], where: str, display):
        super().__init__(parent)
        import re

        self.setWindowTitle("Put folders together")
        self.resize(560, 460)
        col = QVBoxLayout(self)
        col.addWidget(_hint(f"These folders go, as they are, into one new folder in {display(where)}. Untick any "
                            "that should stay where they are. Nothing moves until you click Move, and "
                            "Undo puts it back."))
        self.list = QListWidget()
        for folder in folders:
            item = QListWidgetItem(os.path.basename(folder))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(folder)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        col.addWidget(self.list, 1)
        col.addWidget(QLabel("Name of the new folder", objectName="fieldLabel"))
        names = [os.path.basename(f) for f in folders]
        base = os.path.commonprefix(names).rstrip(" -_.(0123456789v").strip() or names[0]
        base = re.sub(r"[\s_\-.]+$", "", base)
        self.name_box = QLineEdit(f"{base} (old versions)")
        self.name_box.setAccessibleName("Name of the new folder")
        col.addWidget(self.name_box)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Put them together")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)

    def chosen(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def name(self) -> str:
        return self.name_box.text().strip()

    def accept(self) -> None:
        if len(self.chosen()) < 1 or not self.name():
            QMessageBox.information(self, self.windowTitle(), "Tick the folders and type a name for the new folder.")
            return
        super().accept()


class LabelsDialog(QDialog):
    """Every label, the most important first, with how many files have it: rename, delete, put two labels
    together, make a new one, or change the order. Changes happen at once and Edit › Undo puts them back."""

    def __init__(self, parent, window):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout

        self.window, self.service = window, window.service
        self.setWindowTitle("Manage labels")
        self.resize(560, 480)
        col = QVBoxLayout(self)
        col.addWidget(_hint("The top label counts most when SortZen weighs labels. Renaming or deleting a label "
                            "changes every file and rule that has it; no file moves. Edit › Undo puts it back."))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._rename())
        col.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in (("New label…", self._new), ("Rename…", self._rename), ("Put into another…", self._merge),
                           ("Delete…", self._delete), ("Move up", lambda: self._move(-1)),
                           ("Move down", lambda: self._move(1))):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        col.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        col.addWidget(box)
        self.fill()

    def fill(self, select: str | None = None) -> None:
        counts = self.service.label_counts()
        current = select or self.selected()
        self.list.clear()
        for name in self.service.labels():
            mine, guessed = counts.get(name, (0, 0))
            item = QListWidgetItem(f"{name}    ·  {mine:,} labelled by you  ·  {guessed:,} by SortZen or the AI")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        if not self.list.count():
            self.list.addItem("No labels yet. Click “New label…” to make one.")
            self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "New label", "Name of the label (for example Work, Taxes or "
                                        "Photo session):")
        if ok and name.strip():
            self.window.new_label([], name)
            self.fill(" ".join(name.split()))

    def _rename(self) -> None:
        name = self.selected()
        if name:
            self.fill(self.window.rename_label(name) or name)

    def _delete(self) -> None:
        name = self.selected()
        if name and self.window.delete_label(name):
            self.fill()

    def _merge(self) -> None:
        name = self.selected()
        others = [x for x in self.service.labels() if x != name]
        if not name or not others:
            return
        into, ok = QInputDialog.getItem(self, "Put into another label", f"Every file and rule with “{name}” gets:",
                                        others, 0, False)
        if ok and into:
            self.fill(self.window.rename_label(name, into, merge=True) or into)

    def _move(self, step: int) -> None:
        name = self.selected()
        if name:
            self.window.edit_label(name, "up" if step < 0 else "down")
            self.fill(name)
