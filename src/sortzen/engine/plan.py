"""What the engine returns: suggestions with their percentages and reasons."""
from __future__ import annotations

from dataclasses import dataclass, field

MOVE, STAY, REVIEW = "move", "stay", "review"


@dataclass(frozen=True)
class Reason:
    supports: bool          # True: evidence for the suggestion; False: against it
    text: str


@dataclass
class Suggestion:
    path: str
    current_folder: str
    destination: str | None             # None: no folder fits
    percent: int                        # how sure SortZen is that the destination is right
    reasons: list[Reason] = field(default_factory=list)
    runner_up: tuple[str, int] | None = None
    note: str = ""                      # e.g. "looks empty"
    new_folder: bool = False            # the destination does not exist yet
    topic: str = ""

    @property
    def action(self) -> str:
        if self.destination is None:
            return REVIEW
        return STAY if self.destination == self.current_folder else MOVE

    def ready(self, autonomy: int) -> bool:
        """At or above the autonomy level: shown ticked in Ready."""
        return self.destination is not None and self.percent >= autonomy


STAYS, KEEP_TOGETHER, SORT_INSIDE, FOLDER_REVIEW = "stays", "keep together", "sort inside", "review"


@dataclass
class FolderSuggestion:
    """What happens to a subfolder of a source folder."""
    path: str
    outcome: str                        # STAYS, KEEP_TOGETHER, SORT_INSIDE or FOLDER_REVIEW
    percent: int
    reasons: list[Reason] = field(default_factory=list)
    destination: str | None = None      # where a kept-together folder goes (None: where it is)
    files: int = 0
    topic: str = ""


@dataclass(frozen=True)
class Choice:
    label: str
    destination: str | None             # None: leave as it is
    outcome: str = ""                   # for folder questions: the outcome this choice gives


@dataclass
class Question:
    key: str                            # stable across runs, so answers are remembered
    text: str
    choices: list[Choice]
    about: list[str]                    # paths of the files and folders it concerns
    answer: int | None = None


@dataclass
class Topic:
    name: str
    members: list[str]                  # files and folders, wherever they are
    home: str
    new_folder: bool = False


@dataclass
class Plan:
    files: list[Suggestion] = field(default_factory=list)
    folders: list[FolderSuggestion] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    new_folders: list[str] = field(default_factory=list)
    copies: list = field(default_factory=list)          # duplicates.CopyGroup: exact copies
    companions: dict = field(default_factory=dict)      # a subtitle file, sidecar... -> the file it goes with

    def folder(self, path: str) -> FolderSuggestion | None:
        return next((f for f in self.folders if f.path == path), None)

    def moves(self) -> list[Suggestion]:
        return [s for s in self.files if s.action == MOVE]

    def for_path(self, path: str) -> Suggestion | None:
        return next((s for s in self.files if s.path == path), None)
