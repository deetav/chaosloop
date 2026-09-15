"""Apply a saved schedule or edited schedule while shrinking"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..exceptions import ReplayMismatch
from .base import Candidate, StepEvent

if TYPE_CHECKING:
    from ..trace import Trace

@dataclass(frozen=True, slots=True)
class Divergence:
    step:int
    kind: str
    expected_index: int
    expected_task: str | None
    actual_index: int
    n_candidates: int

    @property
    def hard(self) -> bool:
        return self.kind in ("absent", "range")


class Replay:
    """Follow task identity where available, otherwise a candidate position"""

    def __init__(
        self,
        decisions: Sequence[int],
        *,
        task_ids: Sequence[str | None] | None = None,
        strict: bool = False,
    ) -> None:
        if any(type(decision) is not int for decision in decisions):
            raise TypeError("replay decisions must all be integers")
        if task_ids is not None and (
            len(task_ids) != len(decisions)
            or any(
                task is not None and (not isinstance(task, str) or not task) for task in task_ids
            )
        ):
            raise ValueError("task_ids must match decisions and contain nonempty strings or None")
        self._requested = tuple(decisions)
        self._task_ids = None if task_ids is None else tuple(task_ids)
        self._strict = strict
        self._position = 0
        self._made: list[int] = []
        self._divergences: list[Divergence] = []

    @classmethod
    def from_trace(cls, trace: Trace, *, strict: bool = False) -> Replay:
        """Use the actual choices and task identities of a recorded execution."""
        return cls(trace.decisions, task_ids=trace.task_ids, strict=strict)

    @classmethod
    def from_decisions(cls, decisions: Sequence[int], *, strict: bool = False) -> Replay:
        """Lower-fidelity positional replay, also used for deliberate shrink edits."""
        return cls(decisions, strict=strict)

    def _note(self, kind: str, want: int, task: str | None, actual: int, count: int) -> None:
        note = Divergence(self._position, kind, want, task, actual, count)
        self._divergences.append(note)
        if self._strict and note.hard:
            raise ReplayMismatch(
                f"replay {kind} at step {self._position}: wanted task {task!r} "
                f"at index {want}, {count} candidates; choice is outside the recording's "
                "applicable schedule"
            )

    def choose(self, candidates: tuple[Candidate, ...]) -> int:
        count = len(candidates)
        if not count:
            raise ValueError("cannot schedule an empty candidate tuple")
        chosen = 0
        if self._position >= len(self._requested):
            self._note("exhausted", -1, None, 0, count)
        else:
            want = self._requested[self._position]
            task = None if self._task_ids is None else self._task_ids[self._position]
            if task is not None:
                found = next(
                    (i for i, candidate in enumerate(candidates) if candidate.task_id == task), None
                )
                if found is None:
                    self._note("absent", want, task, 0, count)
                else:
                    chosen = found
                    if chosen != want:
                        self._note("drift", want, task, chosen, count)
            elif 0 <= want < count:
                chosen = want
            else:
                self._note("range", want, None, 0, count)
        self._position += 1
        self._made.append(chosen)
        return chosen

    def observe(self, event: StepEvent) -> None:
        """Replay follows its saved input and does not adapt to feedback"""

    @property
    def decisions(self) -> list[int]:
        return self._made.copy()

    @property
    def divergences(self) -> list[Divergence]:
        return self._divergences.copy()

    @property
    def diverged(self) -> bool:
        return any(note.hard for note in self._divergences)

    @property
    def remaining(self) -> int:
        """Unused recorded choices; an early finish may leave an untested tail."""
        return max(0, len(self._requested) - self._position)
