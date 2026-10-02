"""The AI service and privacy panels, used in Settings and when asking the AI about unsure files."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..ai import privacy
from ..ai.services import SERVICES

OFF = "off"
WHAT_LEAVES = ("What leaves this PC: the names of the files SortZen couldn't place, where they are now, and the "
               "names of your folders with a few example file names. Nothing else unless you choose “The beginning "
               "of the file” below. Files SortZen placed by itself are never sent.")
PRIVACY_TEXT = {
    privacy.NAME_ONLY: ("Name only", "Most private. Only names and folders are sent; least accurate."),
    privacy.BEGINNING: ("The beginning of the file", f"Most accurate. The first {privacy.WORDS_SENT} words of a "
                                                     "document are sent when the name alone isn't enough, with "
                                                     "numbers and email addresses removed."),
}


def hint(text: str) -> QLabel:
    label = QLabel(text, objectName="hint")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class AIServiceBox(QWidget):
    """Which AI service, its model and its key (kept in Windows Credential Manager)."""

    changed = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        for key, info in SERVICES.items():
            self.choice.addItem(info.caption, key)
        self.choice.addItem("Off: never ask an AI service", OFF)
        current = service.ai_service() if service.ai_value("ai_enabled") else OFF
        self.choice.setCurrentIndex(self.choice.findData(current))
        form.addRow("AI service", self.choice)
        self.model = QLineEdit()
        form.addRow("Model", self.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_row = QWidget()
        key_line = QHBoxLayout(self.key_row)
        key_line.setContentsMargins(0, 0, 0, 0)
        key_line.addWidget(self.key, 1)
        self.forget = QPushButton("Forget key")
        self.forget.clicked.connect(self._forget)
        key_line.addWidget(self.forget)
        form.addRow("API key", self.key_row)
        self.how_to = hint("")
        self.how_to.setTextFormat(Qt.TextFormat.RichText)
        form.addRow("", self.how_to)
        form.addRow("", hint("Keys are kept in Windows Credential Manager, encrypted for your Windows account, "
                             "never in SortZen's files."))
        self.choice.currentIndexChanged.connect(self._show)
        self._show()

    def selected(self) -> str:
        return self.choice.currentData()

    def _show(self) -> None:
        key = self.selected()
        on = key != OFF
        self.model.setEnabled(on)
        if not on:
            self.model.clear()
            self.model.setPlaceholderText("")
            self.key.setEnabled(False)
            self.forget.setEnabled(False)
            self.how_to.setText("SortZen sorts everything by itself and asks you about the rest.")
            self.changed.emit()
            return
        info = SERVICES[key]
        saved = self.service.model(key)
        self.model.setText("" if saved == info.default_model else saved)
        self.model.setPlaceholderText(info.default_model)
        self.key.setEnabled(info.needs_key)
        self.key.clear()
        has = info.needs_key and self.service.has_api_key(key)
        self.key.setPlaceholderText("A key is saved" if has else "Paste your key here" if info.needs_key
                                    else "No key needed")
        self.forget.setEnabled(has)
        self.how_to.setText(info.how_to)
        self.changed.emit()

    def _forget(self) -> None:
        self.service.clear_api_key(self.selected())
        self._show()

    def apply(self) -> None:
        key = self.selected()
        self.service.set_ai_value("ai_enabled", key != OFF)
        if key == OFF:
            return
        self.service.set_ai_service(key)
        self.service.set_model(self.model.text(), key)
        if self.key.text().strip():
            self.service.save_api_key(self.key.text().strip(), key)
            self.key.clear()


class PrivacyModeBox(QWidget):
    """Name only, or the beginning of the file; and picture previews."""

    changed = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(hint(WHAT_LEAVES))
        self.group = QButtonGroup(self)
        self.buttons = {}
        for mode, (title, text) in PRIVACY_TEXT.items():
            button = QRadioButton(title)
            button.setChecked(service.ai_value("ai_privacy") == mode)
            self.group.addButton(button)
            self.buttons[mode] = button
            col.addWidget(button)
            col.addWidget(hint(text))
            button.toggled.connect(lambda _: self.changed.emit())
        self.previews = QCheckBox("Also send a small preview of pictures SortZen can't place")
        self.previews.setChecked(bool(service.ai_value("ai_previews")))
        self.previews.toggled.connect(lambda _: self.changed.emit())
        col.addWidget(self.previews)
        col.addWidget(hint("Off by default: pictures are sorted by name and photo details."))

    def mode(self) -> str:
        return next(m for m, b in self.buttons.items() if b.isChecked())

    def apply(self) -> None:
        self.service.set_ai_value("ai_privacy", self.mode())
        self.service.set_ai_value("ai_previews", self.previews.isChecked())


class PrivacyListsBox(QWidget):
    """Folders and words that are only ever sent by name, house rules and the spending cap."""

    def __init__(self, service):
        super().__init__()
        self.service = service
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(QLabel("Always name only: these folders", objectName="cardTitle"))
        self.folders = QListWidget()
        self.folders.addItems(service.ai_value("ai_name_only_folders"))
        self.folders.setMaximumHeight(110)
        col.addWidget(self.folders)
        buttons = QHBoxLayout()
        add = QPushButton("Add a folder…")
        add.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i))
                                        for i in self.folders.selectedItems()])
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        col.addLayout(buttons)
        col.addWidget(QLabel("…and files whose name or folder contains these words", objectName="cardTitle"))
        self.words = QLineEdit(", ".join(service.ai_value("ai_name_only_words")))
        self.words.setPlaceholderText("tax, bank, passport")
        col.addWidget(self.words)
        col.addWidget(QLabel("House rules", objectName="cardTitle"))
        self.rules = QPlainTextEdit(service.ai_value("house_rules"))
        self.rules.setPlaceholderText("Plain-English notes sent with every question, e.g. “Resumes are personal "
                                      "even if they mention my employer”.")
        self.rules.setMaximumHeight(90)
        col.addWidget(self.rules)
        cap = QHBoxLayout()
        cap.addWidget(QLabel("Spend at most"))
        self.cap = QDoubleSpinBox(prefix="$", decimals=2, minimum=0.01, maximum=5.0, singleStep=0.05)
        self.cap.setValue(float(service.ai_value("ai_cap_per_1000")))
        cap.addWidget(self.cap)
        cap.addWidget(QLabel("per 1,000 files in the plan"))
        cap.addStretch(1)
        col.addLayout(cap)
        col.addWidget(hint(f"Spent this month: ${service.ai_spent():.4f}. Answers are remembered, so the same file "
                           "is never paid for twice."))

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Only ever send names from this folder")
        if folder:
            self.folders.addItem(folder)

    def apply(self) -> None:
        self.service.set_ai_value("ai_name_only_folders", [self.folders.item(i).text()
                                                           for i in range(self.folders.count())])
        self.service.set_ai_value("ai_name_only_words", [w.strip() for w in self.words.text().split(",") if w.strip()])
        self.service.set_ai_value("house_rules", self.rules.toPlainText().strip())
        self.service.set_ai_value("ai_cap_per_1000", round(self.cap.value(), 2))
