"""Apply a saved schedule or edited schedule while shrinking"""

from collections.abc import Sequence

from ..exceptions import ReplayMismatch
from .base import Candidate, StepEvent


class Replay:
    """Replay candidate tuple positions, recording what was actually chosen"""

    def __init__(self, decisions: Sequence[int], *, strict: bool = False) -> None:
        if any(type(decision) is not int for decision in decisions):
            raise TypeError("replay decisions must all be integers")
        self._requested = tuple(decisions)
        self._strict = strict
        self._position = 0
        self._made: list[int] = []

    def choose(self, candidates: tuple[Candidate, ...]) -> int:
        count = len(candidates)
        if count == 0:
            raise ValueError("cannot schedule an empty candidate tuple")
        if self._position >= len(self._requested):
            if self._strict:
                raise ReplayMismatch(
                    f"ran out of decisions at step {self._position} ({count} candidates)"
                )
            chosen = 0
        else:
            requested = self._requested[self._position]
            if self._strict and not 0 <= requested < count:
                raise ReplayMismatch(
                    f"decision {requested} at step {self._position} is outside range (0, {count})"
                )
            chosen = max(0, min(requested, count - 1))
        self._position += 1
        self._made.append(chosen)
        return chosen

    def observe(self, event: StepEvent) -> None:
        """Replay follows its saved input and does not adapt to feedback"""

    @property
    def decisions(self) -> list[int]:
        return self._made.copy()
