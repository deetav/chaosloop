"""Oracles that inspect how a run ended"""

from ..exceptions import Deadlock, StepBudgetExceeded, TimeBudgetExceeded
from .base import Finding, OracleBase, Outcome, RunContext, Severity, failure_site

CONTROL_ERRORS = (Deadlock, StepBudgetExceeded, TimeBudgetExceeded)

class UnhandledException(OracleBase):
    name = "unhandled_exception"

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        error = outcome.error
        if error is None or isinstance(error, CONTROL_ERRORS):
            return None
        return Finding(
            self.name,
            Severity.FAILURE,
            f"{type(error).__name__}: {error}",
            step=ctx.step,
            site=failure_site(error),
        )


class DeadlockOracle(OracleBase):
    name = "deadlock"

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        if not isinstance(outcome.error, Deadlock):
            return None
        tasks = ctx.pending_tasks()
        detail = "\n".join(
            f"{t.task_id} ({t.name}) blocked at {t.location or '?'} awaiting {t.awaiting or '?'}"
            for t in tasks
        )
        return Finding(
            self.name,
            Severity.FAILURE,
            f"deadlock with {len(tasks)} task(s) pending",
            detail,
            ctx.step,
            next((t.location for t in tasks if t.location), None),
        )


class LivelockOracle(OracleBase):
    name = "livelock"

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        if not isinstance(outcome.error, StepBudgetExceeded):
            return None
        return Finding(
            self.name,
            Severity.FAILURE,
            f"step budget exhausted after {ctx.step} steps; possible livelock, "
            "or a legitimate scenario needing a larger max_steps",
            step=ctx.step,
        )


class TimeBudgetOracle(OracleBase):
    name = "time_budget"

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        if not isinstance(outcome.error, TimeBudgetExceeded):
            return None
        return Finding(
            self.name,
            Severity.FAILURE,
            f"virtual-time budget exhausted: {outcome.error}",
            step=ctx.step,
        )
