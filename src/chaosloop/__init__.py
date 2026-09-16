"""chaosloop: deterministic scheduler fuzzing for pure-async asyncio programs"""


from .clock import VirtualClock
from .diff import DiffRow, diff_traces, render_diff
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
from .schedulers import Candidate, Divergence, Fifo, Random, Replay, Scheduler, StepEvent
from .shrink import ShrinkBudget, ShrinkError, ShrinkResult, shrink
from .trace import Step, Trace, Tracer

__version__ = "0.4.0"

__all__ = [
    "Candidate",
    "ChaosloopError",
    "Deadlock",
    "Divergence",
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

from .corpus import Corpus, CorpusEntry
from .decorators import chaos_test
from .exceptions import OracleExecutionError, OracleFailure
from .fuzz import Bucket, FuzzResult, Progress, bucket_failures, default_progress, fuzz
from .invariants import invariant
from .oracles import (
    DeadlockOracle,
    Finding,
    Invariant,
    InvariantOracle,
    LivelockOracle,
    Oracle,
    OracleBase,
    Outcome,
    RunContext,
    Severity,
    TaskInfo,
    TaskLeak,
    TimeBudgetOracle,
    UnhandledException,
    UnretrievedException,
)

__all__ += [
    "Bucket",
    "Corpus",
    "CorpusEntry",
    "DeadlockOracle",
    "Finding",
    "FuzzResult",
    "Invariant",
    "InvariantOracle",
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
    "chaos_test",
    "default_progress",
    "fuzz",
    "invariant",
]


__all__ += [
    "DiffRow",
    "ShrinkBudget",
    "ShrinkError",
    "ShrinkResult",
    "diff_traces",
    "render_diff",
    "shrink",
]
