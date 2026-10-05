"""One background job at a time, with a cooperative cancel token ("Stop Safely").

A job's work function receives ``(emit, token)``: ``emit`` sends a ``JobEvent`` to the
window, and the work checks ``token.cancelled`` between steps and stops cleanly.
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from .events import JobEvent, JobFailed, JobFinished


class CancelToken:
    def __init__(self):
        self.event = threading.Event()

    def cancel(self) -> None:
        self.event.set()

    @property
    def cancelled(self) -> bool:
        return self.event.is_set()


class Job:
    def __init__(self, name: str, work: Callable, on_event: Callable[[JobEvent], None]):
        self.name = name
        self.token = CancelToken()
        self._work = work
        self._on_event = on_event
        self.result = None
        self.error: BaseException | None = None
        self.traceback = ""
        self.thread = threading.Thread(target=self._run, name=f"sortzen-{name}", daemon=True)

    def _run(self):
        try:
            self.result = self._work(self._on_event, self.token)
            self._on_event(JobFinished(self.name, self.result))
        except BaseException as exc:  # reported to the window, never swallowed
            self.error = exc
            self.traceback = traceback.format_exc()
            self._on_event(JobFailed(self.name, str(exc) or type(exc).__name__))

    def start(self) -> "Job":
        self.thread.start()
        return self

    def join(self, timeout=None) -> None:
        self.thread.join(timeout)

    @property
    def running(self) -> bool:
        return self.thread.is_alive()


class JobRunner:
    def __init__(self):
        self.current: Job | None = None

    @property
    def busy(self) -> bool:
        return bool(self.current and self.current.running)

    def start(self, name: str, work: Callable, on_event: Callable[[JobEvent], None]) -> Job:
        if self.busy:
            raise RuntimeError(f"'{self.current.name}' is still running.")
        self.current = Job(name, work, on_event).start()
        return self.current

    def cancel(self) -> None:
        if self.current:
            self.current.token.cancel()
