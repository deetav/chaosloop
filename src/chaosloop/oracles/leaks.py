"""Observe leftovers before runner cancellation erases the evidence"""

from .base import Finding, OracleBase, Outcome, RunContext, Severity


class TaskLeak(OracleBase):
    name = "task_leak"

    def __init__(self, severity: Severity = Severity.WARNING) -> None:
        self.severity = severity

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        tasks = ctx.pending_tasks()
        if not outcome.completed or not tasks:
            return None
        detail = "\n".join(
            f"{task.task_id} ({task.name}) at {task.location or '?'} "
            f"awaiting {task.awaiting or '?'}"
            for task in tasks
        )
        return Finding(
            self.name,
            self.severity,
            f"{len(tasks)} task(s) left pending",
            detail,
            ctx.step,
            next((t.location for t in tasks if t.location), None),
        )


class UnretrievedException(OracleBase):
    name = "unretrieved_exception"

    def on_finish(self, ctx: RunContext, outcome: Outcome) -> Finding | None:
        errors = ctx.captured_errors()
        if not errors:
            return None
        first = errors[0]
        # One stable primary finding, with every captured error preserved in detail.
        return Finding(
            self.name,
            Severity.FAILURE,
            f"{first.kind}: {first.message}",
            "\n".join(f"{e.kind}: {e.message} at {e.site or '?'}" for e in errors),
            ctx.step,
            first.site,
        )
