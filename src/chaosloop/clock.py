"""A monotonic virtual clock
Waiting changes a number not wall clock
"""

import math
from dataclasses import dataclass

from .exceptions import TimeBudgetExceeded


@dataclass(slots=True)
class VirtualClock:
    """The loop's source of time, measured in virtual seconds."""
    now: float = 0.0
    max_time: float | None = None

    def __post_init__(self) -> None:
        """Reject invalid initial state before the loop can use the clock."""
        if not math.isfinite(self.now) or self.now < 0:
            raise ValueError("now must be finite and nonnegative")
        if self.max_time is not None:
            if not math.isfinite(self.max_time) or self.max_time < 0:
                raise ValueError("max_time must be finite and nonnegative")
            if self.now > self.max_time:
                raise TimeBudgetExceeded(f"virtual time {self.now} exceeds maximum {self.max_time}")
    def advance_to(self, when: float) -> None:
        """Advance to a finite deadline"""
        if not math.isfinite(when):
            raise ValueError(f"invalid time: {when!r}")
        if when <= self.now:
            return
        if self.max_time is not None and when > self.max_time:
            raise TimeBudgetExceeded(f"virtual time {when} exceeds maximum {self.max_time}")
        self.now = when

    def advance_by(self, delta: float) -> None:
        """Move forward by a finite, nonnegative duration."""
        if not math.isfinite(delta) or delta < 0:
            raise ValueError(f"invalid duration: {delta!r}")
        self.advance_to(self.now + delta)
