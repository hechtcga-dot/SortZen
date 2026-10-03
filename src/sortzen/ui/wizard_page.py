"""The cataloguing wizard: labels first, then only what SortZen isn't sure about, round after round.

Step 1: users make their label list (the top label counts most), optionally with the AI's suggestions,
and choose how files get their first labels: SortZen on the PC, or the AI for a sample of files with
SortZen labelling the rest from them. Step 2: the files SortZen isn't sure about, in groups one answer
settles, with labels, rules and notes. A meter shows how often SortZen's guesses matched users' changes;
when it has learned enough from them it offers to catalog again, and says when the rest can be left
to it. Finish opens the Cataloguing tab.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QRadioButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .to_place_page import ToPlacePage


def _label(text: str = "", name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text, objectName=name) if name else QLabel(text)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class WizardPage(QWidget):
    start = Signal(str)                      # "local" or "ai": label the files and catalog them
    suggest_labels = Signal()                # ask the AI for a label list
    add_label = Signal()
    edit_label = Signal(str, str)            # label, "rename" / "remove"
    reorder = Signal(list)                   # labels, the most important first
    again = Signal()                         # catalog again with what SortZen learned
    ask_ai_rest = Signal()                   # the AI labels the files SortZen is still unsure of
    finish = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        col.addWidget(self.stack)
        self.stack.addWidget(self._labels_step())
        self.stack.addWidget(self._check_step())

    # ---------------------------------------------------------------- step 1
    def _labels_step(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)
        col.addWidget(_label("Cataloguing wizard · Step 1 of 2: your labels", "pageTitle", wrap=False))
        col.addWidget(_label("Labels describe what files are about, such as Work, Taxes, School or Photo session. "
                             "A file can have several. Drag labels up or down: the top label counts most when "
                             "SortZen decides where files go. Folders come later: SortZen learns which folders "
                             "your labels belong in.", "hint"))
        row = QHBoxLayout()
        self.label_list = QListWidget()
        self.label_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.label_list.setMaximumWidth(360)
        self.label_list.model().rowsMoved.connect(lambda *_: self.reorder.emit(self.labels_shown()))
        row.addWidget(self.label_list, 1)
        side = QVBoxLayout()
        add = QPushButton("Add a label…")
        add.clicked.connect(self.add_label)
        rename = QPushButton("Rename…")
        rename.clicked.connect(lambda: self._current() and self.edit_label.emit(self._current(), "rename"))
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self._current() and self.edit_label.emit(self._current(), "remove"))
        self.ai_list_button = QPushButton("Ask AI to suggest labels…")
        self.ai_list_button.setToolTip("Sends file names (long numbers removed) and folder names; shows the cost first")
        self.ai_list_button.clicked.connect(self.suggest_labels)
        for b in (add, rename, remove, self.ai_list_button):
            side.addWidget(b)
        side.addStretch(1)
        row.addLayout(side)
        row.addStretch(1)
        col.addLayout(row, 1)
        col.addWidget(_label("How should files get their first labels?", "sectionCaps"))
        self.mode = QButtonGroup(self)
        local = QRadioButton("SortZen labels them on this PC (free): from words in names, folders and contents")
        ai = QRadioButton("The AI labels a sample of files, and SortZen labels the rest from them (the cost is shown "
                          "first)")
        local.setChecked(True)
        self.mode.addButton(local, 0)
        self.mode.addButton(ai, 1)
        col.addWidget(local)
        col.addWidget(ai)
        bottom = QHBoxLayout()
        self.step1_hint = _label("", "muted")
        bottom.addWidget(self.step1_hint, 1)
        self.start_button = QPushButton("Label and catalog the files", objectName="primary")
        self.start_button.clicked.connect(lambda: self.start.emit("ai" if self.mode.checkedId() == 1 else "local"))
        bottom.addWidget(self.start_button)
        col.addLayout(bottom)
        return page

    def labels_shown(self) -> list[str]:
        return [self.label_list.item(i).text() for i in range(self.label_list.count())]

    def _current(self) -> str | None:
        item = self.label_list.currentItem()
        return item.text() if item else None

    # ---------------------------------------------------------------- step 2
    def _check_step(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(16, 12, 16, 0)
        col.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(_label("Cataloguing wizard · Step 2 of 2: check what SortZen isn't sure about", "pageTitle",
                             wrap=False), 1)
        back = QPushButton("Back to labels")
        back.clicked.connect(lambda: self.show_step(0))
        top.addWidget(back)
        col.addLayout(top)
        self.meter = _label("", "muted")
        col.addWidget(self.meter)
        self.banner = QFrame(objectName="card")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(12, 8, 12, 8)
        self.banner_text = _label("")
        row.addWidget(self.banner_text, 1)
        self.again_button = QPushButton("Catalog again", objectName="primary")
        self.again_button.clicked.connect(self.again)
        row.addWidget(self.again_button)
        self.ai_rest_button = QPushButton("Ask AI about the rest…")
        self.ai_rest_button.setToolTip("The AI labels only the files SortZen is still unsure of; the cost is shown first")
        self.ai_rest_button.clicked.connect(self.ask_ai_rest)
        row.addWidget(self.ai_rest_button)
        self.finish_button = QPushButton("Finish: see the catalog")
        self.finish_button.clicked.connect(self.finish)
        row.addWidget(self.finish_button)
        col.addWidget(self.banner)
        self.check = ToPlacePage(self.service)
        self.check.layout().setContentsMargins(0, 0, 0, 12)
        self.check.title.hide()
        col.addWidget(self.check, 1)
        return page

    # ---------------------------------------------------------------- showing
    def show_step(self, step: int) -> None:
        self.stack.setCurrentIndex(step)
        self.refresh()

    def refresh(self) -> None:
        """The label list, the meter and what SortZen offers next."""
        keep = self._current()
        self.label_list.blockSignals(True)
        self.label_list.clear()
        for name in self.service.labels():
            self.label_list.addItem(name)
        self.label_list.blockSignals(False)
        found = self.label_list.findItems(keep or "", Qt.MatchFlag.MatchExactly)
        if found:
            self.label_list.setCurrentItem(found[0])
        n = len(self.service.labels())
        self.step1_hint.setText("Add at least one label, or let the AI suggest some." if not n else
                                f"{n} label{'s' if n != 1 else ''}. You can change them at any time.")
        self.start_button.setEnabled(bool(n))
        agreed, total = self.service.agreement()
        waiting = self.check.count()
        learned = self.service.learned_since_plan()
        meter = f"{waiting:,} file{'s' if waiting != 1 else ''} need you."
        if total:
            meter += f" SortZen's guess matched your choice {agreed} times out of your last {total} changes."
        self.meter.setText(meter)
        if self.service.learned_enough():
            text = ("SortZen has learned enough: its guesses match yours most of the time. The rest can be left to "
                    "it, or keep going.")
        elif self.service.ready_to_recatalog():
            text = f"SortZen has learned from your last {learned} changes. Catalog again to settle more files."
        elif learned:
            text = (f"{learned} change{'s' if learned != 1 else ''} so far. Label a few more groups, then catalog "
                    "again: each round should leave fewer files.")
        else:
            text = ("Select a group or files and click a label, or right-click for “Looks right”, notes and "
                    "rules. One answer for a group settles all its files.")
        self.banner_text.setText(text)
        self.again_button.setEnabled(learned > 0)
        self.ai_rest_button.setEnabled(self.service.ai_ready() and waiting > 0)
        self.finish_button.setObjectName("primary" if self.service.learned_enough() or not waiting else "")
        self.finish_button.style().unpolish(self.finish_button)
        self.finish_button.style().polish(self.finish_button)
