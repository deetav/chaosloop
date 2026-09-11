"""The data-only contract between the event loop and scheduling strategies."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen= True, slots=True)
class Candidate:
    """One runnable callback, without access to its live Handle or Task."""

    index: int
    task_id: str | None
    kind: str
    label: str
    location: str | None

@dataclass(frozen=True, slots=True)
class StepEvent:
    """Feedback after one callback"""
    step: int
    vtime: float
    chosen: int
    task_id: str | None
    n_candidates: int

@runtime_checkable
class Scheduler(Protocol):
    """Select the next callback using only reproducible, scheduler-owned state.
    ``decisions`` records every actual choice, including singleton choices.
    """

    def choose(self, candidates: tuple[Candidate, ...]) -> int:
        """Return a tuple position, and append it to the decision history."""
        ...

    def observe(self, event: StepEvent) -> None:
        """Receive completed-step feedback; stateless strategies ignore it."""
        ...

    @property
    def decisions(self) -> list[int]:
        """A defensive copy of choices made, in replay order."""
        ...
