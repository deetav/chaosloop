"""chaosloop: deterministic scheduler fuzzing for pure-async asyncio programs"""

from .clock import VirtualClock
from .exceptions import (
    ChaosloopError,
    Deadlock,
    OracleExecutionError,
    OracleFailure,
    ReplayMismatch,
    StepBudgetExceeded,
    TimeBudgetExceeded,
    UnsupportedOperation,
    UnsupportedPython,
)
from .runner import Trial, run, trial
from .schedulers import Candidate, Fifo, Random, Replay, Scheduler, StepEvent
from .trace import Step, Trace, Tracer

__all__ = [
    "Candidate",
    "ChaosloopError",
    "Deadlock",
    "Fifo",
    "OracleExecutionError",
    "OracleFailure",
    "Random",
    "Replay",
    "ReplayMismatch",
    "Scheduler",
    "Step",
    "StepBudgetExceeded",
    "StepEvent",
    "TimeBudgetExceeded",
    "Trace",
    "Tracer",
    "Trial",
    "UnsupportedOperation",
    "UnsupportedPython",
    "VirtualClock",
    "run",
    "trial",
]

from .oracles import Finding, RunContext, Severity

__all__ += [
    "Finding",
    "RunContext",
    "Severity",
]

