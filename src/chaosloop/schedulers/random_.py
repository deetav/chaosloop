"""Reproducible exploration without touching Python's shared random state"""

import random

from .base import Candidate, StepEvent


class Random:
    """Uniform choices from one private seeded pseudo random generator"""

    def __init__(self, seed: int) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an integer")
        self.seed = seed
        self._random = random.Random(seed)
        self._decisions: list[int] = []

    def choose(self, candidates: tuple[Candidate, ...]) -> int:
        if not candidates:
            raise ValueError("cannot schedule empty candidate tuple")
        chosen = self._random.randrange(len(candidates))
        self._decisions.append(chosen)
        return chosen

    def observe(self, event: StepEvent) -> None:
        """uniform random exploration does not learn from completed steps"""

    @property
    def decisions(self) -> list[int]:
        return self._decisions.copy()
