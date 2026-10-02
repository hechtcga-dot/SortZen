"""Asking the AI service about unsure files: what will be sent, what it may cost, then ask."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFrame, QLabel, QMessageBox, QVBoxLayout

from .ai_widgets import OFF, AIServiceBox, PrivacyModeBox, hint


class AskAIDialog(QDialog):
    def __init__(self, parent, service, plan):
        super().__init__(parent)
        self.service = service
        self.plan = plan
        self.setWindowTitle("Ask an AI service")
        self.resize(620, 640)
        col = QVBoxLayout(self)
        self.title = QLabel(objectName="cardTitle")
        self.title.setWordWrap(True)
        col.addWidget(self.title)
        self.cost = hint("")
        col.addWidget(self.cost)
        col.addWidget(hint("Nothing is moved: the answers appear in the plan as one more piece of evidence, with "
                           "the AI's reasons. An AI answer alone counts for at most 70%, so those files still wait "
                           "in Review for you."))
        line = QFrame(frameShape=QFrame.Shape.HLine)
        col.addWidget(line)
        self.ai_box = AIServiceBox(service)
        col.addWidget(self.ai_box)
        self.privacy = PrivacyModeBox(service)
        col.addWidget(self.privacy)
        col.addStretch(1)
        self.buttons = QDialogButtonBox()
        self.ask = self.buttons.addButton("Ask", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ask.setObjectName("primary")
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        self.ai_box.changed.connect(self._update)
        self.privacy.changed.connect(self._update)
        self.ai_box.key.textChanged.connect(lambda _: self._update())
        self._update()

    def _update(self) -> None:
        """Show the estimate for the choices on screen (saved only when Ask is pressed)."""
        choice = self.ai_box.selected()
        if choice == OFF:
            self.title.setText("Choose an AI service to ask about the files SortZen couldn't place.")
            self.cost.setText("")
            self.ask.setEnabled(False)
            return
        estimate = self.service.ai_estimate(self.plan, ai_service=choice, ai_privacy=self.privacy.mode(),
                                            ai_previews=self.privacy.previews.isChecked())
        n = estimate["files"]
        remembered = (f" {estimate['remembered']:,} more already have an answer, at no cost."
                      if estimate["remembered"] else "")
        if not n:
            self.title.setText("There is nothing new to ask about." + remembered)
            self.cost.setText("")
            self.ask.setEnabled(False)
            return
        self.title.setText(f"Ask {estimate['service']} about {n:,} file{'s' if n != 1 else ''} SortZen couldn't "
                           f"place by itself?{remembered}")
        if estimate["local"]:
            money = "Free: it runs on this PC and nothing leaves it."
        else:
            money = (f"Estimated cost: about ${estimate['cost']:.4f} (at most ${estimate['cap']:.2f} for this plan; "
                     f"SortZen stops at that). Spent this month: ${estimate['spent_this_month']:.4f}.")
        content = estimate["with_content"]
        sends = (f" {content:,} of them may also send the beginning of the file." if content else
                 " Only names are sent.")
        needs_key = not estimate["local"] and not self.service.has_api_key(choice) and not self.ai_box.key.text()
        self.cost.setText(money + sends + (f" Paste your {estimate['service']} API key below first." if needs_key
                                           else ""))
        self.ask.setEnabled(not needs_key)
        self.ask.setToolTip("Paste the API key first" if needs_key else "")

    def accept(self) -> None:
        """Check the service, model and key with a tiny request first; on a problem, say so and stay open."""
        if not self.ai_box.check():
            QMessageBox.warning(self, "This AI service can't be used yet", self.ai_box.problem +
                                "\n\nNothing was sent about your files.")
            return
        self.ai_box.apply()
        self.privacy.apply()
        super().accept()
