"""PCT: Probabilistic Concurrency Testing

An explicitly documented PCT adaptation and not an impl carrying the original paper's
theorem unchanged.
"""

import random

from .base import Candidate, StepEvent


class Pct:
    """keep priorities between steps
    demote the chosen identity at d-1 points
    """

    def __init__(self, seed: int, *, depth: int = 3, steps: int = 1000) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an integer")
        for name, value in (("depth", depth), ("steps", steps)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.seed, self.depth, self.steps = seed, depth, steps
        self.horizon = max(steps, depth)
        self._random = random.Random(seed)
        self.change_points = tuple(sorted(self._random.sample(range(1, self.horizon), depth - 1)))
        self._points = set(self.change_points)
        self._priorities: dict[tuple[str, str], int] = {}
        self._initial_keys: set[int] = set()
        self._decisions: list[int] = []
        self._demotions: list[tuple[int, tuple[str, str]]] = []

    @staticmethod
    def _identity(candidate: Candidate) -> tuple[str, str]:
        return (
            ("task", candidate.task_id)
            if candidate.task_id is not None
            else ("callback", candidate.label)
        )

    def choose(self, candidates: tuple[Candidate, ...]) -> int:
        if not candidates:
            raise ValueError("cannot schedule an empty candidate tuple")
        identities = [self._identity(candidate) for candidate in candidates]
        for identity in identities:
            if identity not in self._priorities:
                key = self._random.getrandbits(128) + 1
                while key in self._initial_keys:
                    key = self._random.getrandbits(128) + 1
                self._initial_keys.add(key)
                self._priorities[identity] = key
        chosen = max(range(len(candidates)), key=lambda i: (self._priorities[identities[i]], -i))
        self._decisions.append(chosen)
        step = len(self._decisions)
        if step in self._points:
            identity = identities[chosen]
            self._demotions.append((step, identity))
            self._priorities[identity] = -len(self._demotions)
        return chosen

    def observe(self, event: StepEvent) -> None:
        """No additional learning; choosing already advances the step counter."""

    @property
    def decisions(self) -> list[int]:
        return self._decisions.copy()

    @property
    def unused_change_points(self) -> int:
        return len(self.change_points) - len(self._demotions)

    @property
    def demotions(self) -> tuple[tuple[int, tuple[str, str]], ...]:
        return tuple(self._demotions)

    @property
    def priority_classes(self) -> dict[str, int]:
        return {
            kind: sum(key[0] == kind for key in self._priorities) for kind in ("task", "callback")
        }

    @property
    def tasks_seen(self) -> int:
        return self.priority_classes["task"]
