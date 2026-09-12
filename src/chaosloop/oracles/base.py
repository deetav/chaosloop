"""Oracle contract: read observations, return verdict without mutation"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..runtime import ErrorInfo, TraceView
from ..runtime import TaskInfo as TaskInfo
from ..trace import Step

_PACKAGE = Path(__file__).resolve().parents[1]
_ASYNCIO = Path(asyncio.__file__).resolve().parent

# is the given traceback from chaosloop/asyncio internals?
def _internal(filename: str) -> bool:
    if filename.startswith("<frozen "):
        return True
    path = Path(filename).resolve()
    return path.is_relative_to(_PACKAGE) or path.is_relative_to(_ASYNCIO)

def failure_site(exc: BaseException | None) -> str | None:
    """Deepest user frame, including the first useful leaf of an ExceptionGroup."""
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            if site := failure_site(child):
                return site
    tb = exc.__traceback__ if exc is not None else None
    site = None
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if not _internal(filename):
            site = f"{Path(filename).name}:{tb.tb_lineno}"
        tb = tb.tb_next
    return site

class Severity(Enum):
    FAILURE = "failure"
    WARNING = "warning"

@dataclass(frozen=True, slots=True)
class Finding:
    """Signature grouping is a heuristic, not proof of bug identity"""

    oracle: str
    severity: Severity
    message: str
    detail: str | None = None
    step: int | None = None
    site: str | None = None

    @property
    def signature(self) -> str:
        # Preserve the source line in site, but normalize variable values in
        # messages. Distinct bugs can over-merge: document and retain exemplars.
        message = re.sub(r"0x[0-9a-fA-F]+", "<address>", self.message)
        message = re.sub(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", "#", message)
        return f"{self.oracle}|{self.severity.value}|{self.site or '?'}|{message}"

@dataclass(frozen=True, slots=True)
class Outcome:
    value: Any
    error: BaseException | None
    completed: bool


@runtime_checkable
class RunContext(Protocol):
    """Read-only public surface. Trace and error observations are detached data."""

    @property
    def step(self) -> int: ...

    @property
    def vtime(self) -> float: ...

    @property
    def ready_count(self) -> int: ...

    @property
    def timers_pending(self) -> int: ...

    def pending_tasks(self) -> tuple[TaskInfo, ...]: ...

    def trace(self) -> TraceView: ...

    def captured_errors(self) -> tuple[ErrorInfo, ...]: ...


@runtime_checkable
class Oracle(Protocol):
    """Deterministic, observational, cheap hooks; None means no verdict"""

    name: str

    def on_start(self, ctx: RunContext) -> None: ...

    def on_step(self, ctx: RunContext, step: Step) -> Finding | None: ...

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None: ...


class OracleBase:
    """Implement only the hooks your detector actually needs."""

    name = "oracle"

    def on_start(self, ctx: RunContext) -> None:
        return None

    def on_step(self, ctx: RunContext, step: Step) -> Finding | None:
        return None

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        return None
