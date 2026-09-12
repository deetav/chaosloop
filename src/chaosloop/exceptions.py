#ruff: noqa: N818
class ChaosloopError(Exception):
    """Base class for errors and findings raised by chaosloop"""

class UnsupportedPython(ChaosloopError):
    """The interpreter's asyncio internals are not supported"""
class UnsupportedOperation(ChaosloopError):
    """A scenario requested an operation outside deterministic simulation.
    """

class Deadlock(ChaosloopError):
    """No runnable callbacks and no future timers"""

class StepBudgetExceeded(ChaosloopError):
    """The scenario exhausted its callback budget; it may be livelocked."""


class TimeBudgetExceeded(ChaosloopError):
    """Advancing the virtual clock would exceed its configured budget."""


class ReplayMismatch(ChaosloopError):
    """A strict replay cannot apply its next recorded scheduling decision."""

class OracleFailure(ChaosloopError):
    """run() detected a FAILURE finding without a direct scenario exception."""

class OracleExecutionError(ChaosloopError):
    """An oracle implementation raised instead of returning a finding."""
