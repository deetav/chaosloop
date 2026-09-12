"""Snapshots for oracle"""

from dataclasses import dataclass

from .trace import Step, Trace


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """A task description at one instant"""

    name: str
    done: bool
    cancelled: bool
    location: str | None
    awaiting: str | None
    task_id: str = ""


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Captured background failure, with no mutable exception/traceback exposed"""

    kind: str
    message: str
    site: str | None


@dataclass(frozen=True, slots=True)
class TraceView:
    """Detached read-only trace snapshot for an oracle."""

    steps: tuple[Step, ...]

    @property
    def decisions(self) -> tuple[int, ...]:
        return tuple(step.chosen for step in self.steps)

    def digest(self) -> str:
        return Trace(steps=list(self.steps)).digest()
