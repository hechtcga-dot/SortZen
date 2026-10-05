"""Delivers job events from the worker thread to the window thread as a Qt signal."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBridge(QObject):
    event = Signal(object)

    def post(self, event) -> None:      # called from the worker thread
        self.event.emit(event)
