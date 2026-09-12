"""chaosloop: deterministic scheduler fuzzing for pure-async asyncio programs"""

from .clock import VirtualClock
from .exceptions import (
    ChaosloopError,
    Deadlock,
    ReplayMismatch,
    StepBudgetExceeded,
    TimeBudgetExceeded,
    UnsupportedOperation,
    UnsupportedPython,
)
from .runner import Trial, run, trial
from .schedulers import Candidate, Fifo, Random, Replay, Scheduler, StepEvent
from .trace import Step, Trace, Tracer

__version__ = "0.2.0"


__all__ = [
    "Candidate",
    "ChaosloopError",
    "Deadlock",
    "Fifo",
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

from .exceptions import OracleExecutionError, OracleFailure
from .oracles import (
    DeadlockOracle,
    Finding,
    LivelockOracle,
    Oracle,
    OracleBase,
    Outcome,
    RunContext,
    Severity,
    TaskInfo,
    TimeBudgetOracle,
    UnhandledException,
)

__all__ += [
    "Bucket",
    "Corpus",
    "CorpusEntry",
    "DeadlockOracle",
    "Finding",
    "FuzzResult",
    "LivelockOracle",
    "Oracle",
    "OracleBase",
    "OracleExecutionError",
    "OracleFailure",
    "Outcome",
    "Progress",
    "RunContext",
    "Severity",
    "TaskInfo",
    "TaskLeak",
    "TimeBudgetOracle",
    "UnhandledException",
    "UnretrievedException",
    "bucket_failures",
    "default_progress",
    "fuzz",
    "invariant",
]

