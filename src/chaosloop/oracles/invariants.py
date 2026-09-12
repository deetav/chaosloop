"""Check states after each callback"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..trace import Step
from .base import Finding, OracleBase, RunContext, Severity, failure_site


@dataclass(frozen=True, slots=True)
class Invariant:
    name: str
    predicate: Callable[[], bool]
    severity: Severity = Severity.FAILURE
    detail: Callable[[], str] | None = None


class InvariantOracle(OracleBase):
    name = "invariant"

    def __init__(self, invariants: Sequence[Invariant] = ()) -> None:
        self.configured = tuple(invariants)
        self._invariants: list[Invariant] = []
        self._warned: set[int] = set()

    def add(self, invariant: Invariant) -> None:
        if not isinstance(invariant, Invariant) or not callable(invariant.predicate):
            raise TypeError("expected an Invariant with a callable predicate")
        self._invariants.append(invariant)

    def on_start(self, ctx: RunContext) -> None:
        self._invariants = list(self.configured)
        self._warned.clear()

    def on_step(self, ctx: RunContext, step: Step) -> Finding | None:
        warning = None
        for index, inv in enumerate(self._invariants):
            try:
                held = inv.predicate()
                if type(held) is not bool:
                    raise TypeError("invariant predicate must return bool")
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                return Finding(
                    self.name,
                    Severity.FAILURE,
                    f"invariant {inv.name!r} raised {type(error).__name__}: {error}",
                    step=ctx.step,
                    site=failure_site(error) or step.location,
                )
            if held:
                continue
            detail = None
            if inv.detail is not None:
                try:
                    detail = str(inv.detail())
                except Exception as error:
                    detail = f"<detail callback failed: {type(error).__name__}: {error}>"
            finding = Finding(
                self.name,
                inv.severity,
                f"invariant {inv.name!r} violated",
                detail,
                ctx.step,
                step.location,
            )
            if inv.severity is Severity.FAILURE:
                return finding
            # A persistent warning must not flood the trace, or hide a later
            # failing predicate. Return one new warning per step in input order.
            if index not in self._warned and warning is None:
                self._warned.add(index)
                warning = finding
        return warning
