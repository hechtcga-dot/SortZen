"""Typed progress events sent from background jobs to the window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class JobEvent:
    pass


@dataclass(frozen=True)
class Log(JobEvent):
    message: str


@dataclass(frozen=True)
class Status(JobEvent):
    primary: str
    detail: str = ""


@dataclass(frozen=True)
class Progress(JobEvent):
    done: int
    total: int


@dataclass(frozen=True)
class JobFinished(JobEvent):
    name: str
    result: Any = None


@dataclass(frozen=True)
class JobFailed(JobEvent):
    name: str
    message: str
