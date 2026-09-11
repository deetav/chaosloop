"""The ordinary ready queue ordering used as the comparison baseline"""

from .base import Candidate, StepEvent


class Fifo:
    """Always choose tuple position zero: the first runnable callback"""
    def __init__(self) -> None:
        self._decisions: list[int] = []

    def choose(
            self,
            candidates: tuple[Candidate, ...],
    ) -> int:
        if not candidates:
            raise ValueError("cannot schedule an empty candidate tuple")
        self._decisions.append(0)
        return 0

    def observe(self, event: StepEvent) -> None:
        """No adaptive state to update"""

    @property
    def decisions(self) -> list[int]:
        return self._decisions.copy()
