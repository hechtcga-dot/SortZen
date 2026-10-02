"""The Questions tab: what SortZen couldn't settle on its own."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)


class QuestionsPage(QWidget):
    save = Signal(dict)            # question key -> chosen index, or None to forget an answer

    def __init__(self):
        super().__init__()
        self.groups: dict[str, QButtonGroup] = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        title = QLabel("Questions", objectName="pageTitle")
        col.addWidget(title)
        hint = QLabel("SortZen couldn't settle these on its own. Your answers are remembered, so it won't ask "
                      "again; files they concern wait in Review until then.", objectName="hint")
        hint.setWordWrap(True)
        col.addWidget(hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        col.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.button = QPushButton("Save answers and update the plan", objectName="primary")
        self.button.clicked.connect(lambda: self.save.emit(self.answers()))
        row.addWidget(self.button)
        col.addLayout(row)

    def set_questions(self, questions) -> None:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setSpacing(10)
        self.groups.clear()
        for q in questions:
            card = QFrame(objectName="card")
            card_col = QVBoxLayout(card)
            card_col.setContentsMargins(14, 12, 14, 12)
            text = QLabel(q.text)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_col.addWidget(text)
            group = QButtonGroup(card)
            for i, choice in enumerate(q.choices):
                button = QRadioButton(choice.label)
                button.setChecked(q.answer == i)
                group.addButton(button, i)
                card_col.addWidget(button)
            self.groups[q.key] = group
            col.addWidget(card)
        if not questions:
            col.addWidget(QLabel("No questions: SortZen settled everything on its own.", objectName="hint"))
        col.addStretch(1)
        self.scroll.setWidget(body)
        self.button.setEnabled(bool(questions))

    def answers(self) -> dict:
        return {key: (group.checkedId() if group.checkedId() >= 0 else None) for key, group in self.groups.items()}
