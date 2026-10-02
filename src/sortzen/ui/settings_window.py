"""Settings: General, AI, Privacy and Advanced. Changes are saved when OK is pressed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .ai_widgets import AIServiceBox, PrivacyListsBox, PrivacyModeBox, hint

OPTION_TEXT = {
    "gentle": ("Be gentle with my computer", "SortZen works at the lowest priority with short rests, so other "
                                             "programs stay quick and the fan stays quiet. Plans take a little longer."),
    "stop_reading_learned": ("Stop reading left-out folders once SortZen has learned enough from them",
                             "Unticked folders with plenty of files already read are then read by name only, "
                             "unless many of their files are new."),
    "read_google_drive": ("Read file contents on Google Drive",
                          "Google Drive for desktop may download each file to read it, which is slow and uses "
                          "data. When off, files there are sorted by name."),
}


def _page(*widgets) -> QScrollArea:
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(16, 14, 16, 14)
    col.setSpacing(8)
    for w in widgets:
        col.addWidget(w)
    col.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    return area


class SettingsWindow(QDialog):
    def __init__(self, parent, service, tab: str = "General"):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Settings")
        self.resize(640, 620)
        col = QVBoxLayout(self)
        self.tabs = QTabWidget()
        col.addWidget(self.tabs, 1)

        general = QWidget()
        g = QVBoxLayout(general)
        g.setContentsMargins(0, 0, 0, 0)
        level = QHBoxLayout()
        level.addWidget(QLabel("Move without asking when at least"))
        self.level = QSpinBox(minimum=50, maximum=100, suffix="% sure", value=service.autonomy())
        level.addWidget(self.level)
        level.addStretch(1)
        g.addLayout(level)
        g.addWidget(hint("Suggestions at or above this go to Ready, ticked. Nothing moves until you confirm."))
        self.ask_all = QCheckBox("Ask me about everything", checked=service.ask_everything())
        g.addWidget(self.ask_all)
        g.addWidget(hint("Nothing goes to Ready: every file waits in Review for you."))
        self.options = {}
        for name in ("gentle",):
            g.addWidget(self._option(name))
        self.tabs.addTab(_page(general), "General")

        self.ai_box = AIServiceBox(service)
        self.tabs.addTab(_page(self.ai_box), "AI")

        self.privacy_mode = PrivacyModeBox(service)
        self.privacy_lists = PrivacyListsBox(service)
        forget = QPushButton("Forget remembered AI answers")
        forget.setToolTip("The next time you ask, every unsure file is asked about again (and paid for)")
        forget.clicked.connect(self._forget_answers)
        row = QHBoxLayout()
        row.addWidget(forget)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.tabs.addTab(_page(self.privacy_mode, self.privacy_lists, holder), "Privacy")

        rules = QWidget()
        r = QVBoxLayout(rules)
        r.setContentsMargins(0, 0, 0, 0)
        r.addWidget(hint("Rules place every matching file at 100%. SortZen suggests a rule when you send several "
                         "files with a word in common to the same folder. Files you place yourself keep your choice."))
        self.rules = QListWidget()
        self.rules.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for rule in service.rules():
            item = QListWidgetItem(service.describe_rule(rule))
            item.setData(Qt.ItemDataRole.UserRole, rule)
            self.rules.addItem(item)
        if not self.rules.count():
            self.rules.addItem("No rules yet.")
            self.rules.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        r.addWidget(self.rules, 1)
        row = QHBoxLayout()
        remove_rule = QPushButton("Remove")
        remove_rule.clicked.connect(lambda: [self.rules.takeItem(self.rules.row(i)) for i in self.rules.selectedItems()])
        row.addWidget(remove_rule)
        row.addStretch(1)
        r.addLayout(row)
        self.tabs.addTab(_page(rules), "Rules")

        advanced = QWidget()
        a = QVBoxLayout(advanced)
        a.setContentsMargins(0, 0, 0, 0)
        for name in ("stop_reading_learned", "read_google_drive"):
            a.addWidget(self._option(name))
        self.tabs.addTab(_page(advanced), "Advanced")

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        col.addWidget(box)
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == tab:
                self.tabs.setCurrentIndex(i)

    def _option(self, name: str) -> QWidget:
        title, text = OPTION_TEXT[name]
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 4, 0, 4)
        box = QCheckBox(title, checked=self.service.option(name))
        self.options[name] = box
        col.addWidget(box)
        col.addWidget(hint(text))
        return holder

    def _forget_answers(self) -> None:
        if QMessageBox.question(self, "Settings", "Forget every remembered AI answer?") == QMessageBox.StandardButton.Yes:
            self.service.forget_ai_answers()

    def accept(self) -> None:
        self.service.set_autonomy(self.level.value())
        self.service.set_ask_everything(self.ask_all.isChecked())
        for name, box in self.options.items():
            self.service.set_option(name, box.isChecked())
        self.ai_box.apply()
        self.privacy_mode.apply()
        self.privacy_lists.apply()
        kept = [self.rules.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.rules.count())]
        self.service.restore_rules([{"word": x.word, "ext": x.ext, "destination": x.destination} for x in kept if x])
        super().accept()
