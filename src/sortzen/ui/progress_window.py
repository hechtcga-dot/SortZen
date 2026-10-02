"""The window shown while SortZen works: an animation, overall progress, the current step,
time so far and left, rotating tips, and Stop safely."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from . import theme
from .tips import FACT_EVERY, FACTS, TIPS

TIP_SECONDS = 20


class SortingAnimation(QWidget):
    """Little pages dropping into a folder, in a loop, so it is always clear that work is going on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 96)
        self.phase = 0.0
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.colours = [QColor(theme.ACCENT), QColor(theme.INFO_TEXT), QColor(theme.WARN_TEXT)]

    def _tick(self) -> None:
        self.phase = (self.phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        folder = QRectF(w / 2 - 34, h - 40, 68, 36)
        for k in range(3):
            t = (self.phase + k / 3) % 1.0
            x = w / 2 - 30 + k * 22 + 6 * math.sin(t * math.pi * 2 + k)
            y = -18 + t * (folder.top() + 14)
            opacity = 1.0 if t < 0.85 else max(0.0, (1 - t) / 0.15)
            p.setOpacity(opacity)
            page = QRectF(x, y, 16, 20)
            p.setPen(QPen(QColor(theme.LINE), 1))
            p.setBrush(QColor(theme.WHITE))
            p.drawRoundedRect(page, 2, 2)
            p.setPen(QPen(self.colours[k], 1.6))
            for line in range(3):
                p.drawLine(QPointF(x + 3, y + 5 + line * 4), QPointF(x + 13 - line * 2, y + 5 + line * 4))
        p.setOpacity(1.0)
        path = QPainterPath()
        path.addRoundedRect(QRectF(folder.left(), folder.top() - 7, 28, 10), 3, 3)
        path.addRoundedRect(folder, 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawPath(path.simplified())
        p.setBrush(QColor(theme.ACCENT_TINT))
        p.drawRoundedRect(QRectF(folder.left() + 6, folder.top() + 8, folder.width() - 12, 5), 2, 2)
        p.end()


def _mixed(tips: list[str], facts: list[str]) -> list[tuple[str, str]]:
    """Tips in a random order, with a fact after every few of them."""
    rng = random.Random()
    tips, facts = rng.sample(tips, len(tips)), rng.sample(facts, len(facts))
    mixed = []
    for number, tip in enumerate(tips, start=1):
        mixed.append(("Tip:", tip))
        if number % (FACT_EVERY - 1) == 0 and facts:
            mixed.append(("Did you know?", facts.pop()))
    return mixed + [("Did you know?", f) for f in facts]


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _about(seconds: float) -> str:
    if seconds < 45:
        return "less than a minute left"
    minutes = round(seconds / 60)
    return f"about {minutes} minute{'s' if minutes != 1 else ''} left"


class ProgressWindow(QDialog):
    stop = Signal()

    def __init__(self, parent, title: str, estimate: float | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.started = time.monotonic()
        self.estimate = estimate
        self.fraction = 0.0
        col = QVBoxLayout(self)
        col.setContentsMargins(22, 18, 22, 18)
        col.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(18)
        top.addWidget(SortingAnimation(self))
        words = QVBoxLayout()
        self.step = QLabel("Getting ready", objectName="cardTitle")
        self.step.setWordWrap(True)
        self.detail = QLabel("", objectName="muted")
        self.detail.setWordWrap(True)
        words.addWidget(self.step)
        words.addWidget(self.detail)
        words.addStretch(1)
        top.addLayout(words, 1)
        col.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)
        self.times = QLabel(objectName="hint")
        col.addWidget(self.times)
        tip_row = QHBoxLayout()
        self.tip = QLabel(objectName="hint")
        self.tip.setWordWrap(True)
        self.tip.setMinimumHeight(36)
        self.tip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tip_row.addWidget(self.tip, 1)
        self.next_button = QPushButton("Next ›")
        self.next_button.setToolTip("Show the next tip")
        self.next_button.clicked.connect(self._next_tip)
        tip_row.addWidget(self.next_button, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(tip_row)
        row = QHBoxLayout()
        row.addStretch(1)
        self.stop_button = QPushButton("Stop safely")
        self.stop_button.setToolTip("Stops after the current file; everything read so far is kept")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        col.addLayout(row)
        self.tips = _mixed(TIPS, FACTS)
        self.tip_timer = QTimer(self, interval=TIP_SECONDS * 1000)
        self.tip_timer.timeout.connect(self._next_tip)
        self._next_tip()
        self.clock = QTimer(self, interval=1000)
        self.clock.timeout.connect(self._update_times)
        self.clock.start()
        self._update_times()

    def set_step(self, step: str, detail: str = "") -> None:
        self.step.setText(step)
        self.detail.setText(detail)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.fraction = max(self.fraction, min(1.0, done / total))
            self.bar.setValue(int(self.fraction * 1000))
            self._update_times()

    def _update_times(self) -> None:
        elapsed = time.monotonic() - self.started
        text = f"{int(self.fraction * 100)}% done · time so far {_clock(elapsed)}"
        if self.fraction > 0.05 and elapsed > 3:
            text += f" · {_about(elapsed / self.fraction * (1 - self.fraction))}"
        elif self.estimate:
            text += f" · {_about(max(0.0, self.estimate - elapsed))} (estimate)"
        self.times.setText(text)

    def _next_tip(self) -> None:
        """Show the next tip or fact; each one stays for TIP_SECONDS (the Next button skips ahead)."""
        kind, text = self.tips.pop(0)
        self.tips.append((kind, text))
        self.tip.setText(f"{kind} {text}")
        self.tip_timer.start()

    def _stop(self) -> None:
        self.stop_button.setEnabled(False)
        self.stop_button.setText("Stopping…")
        self.stop.emit()

    def finish(self) -> None:
        for timer in (self.tip_timer, self.clock):
            timer.stop()
        self.accept()
