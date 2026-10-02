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

    @property
    def action(self) -> str:
        if self.destination is None:
            return REVIEW
        return STAY if self.destination == self.current_folder else MOVE

    def ready(self, autonomy: int) -> bool:
        """At or above the autonomy level: shown ticked in Ready."""
        return self.destination is not None and self.percent >= autonomy


@dataclass
class Plan:
    files: list[Suggestion] = field(default_factory=list)

    def moves(self) -> list[Suggestion]:
        return [s for s in self.files if s.action == MOVE]

    def for_path(self, path: str) -> Suggestion | None:
        return next((s for s in self.files if s.path == path), None)
