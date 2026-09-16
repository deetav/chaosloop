"""Friendly entry points and a deterministic, explicitly owned loop lifecycle"""

from __future__ import annotations

import asyncio
import copy
import inspect
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, cast

from . import invariants as _inv
from .clock import VirtualClock
from .exceptions import OracleExecutionError, OracleFailure
from .loop import ChaosEventLoop
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
TaskLeak,
    TimeBudgetOracle,
    UnhandledException,
)
from .oracles.base import failure_site
from .oracles.outcome import CONTROL_ERRORS
from .runtime import ErrorInfo, TaskInfo, TraceView
from .schedulers.base import Scheduler
from .schedulers.fifo import Fifo
from .schedulers.random_ import Random
from .schedulers.replay import Divergence, Replay
from .trace import Step, Trace

Scenario = Callable[[], Coroutine[Any, Any, Any]]

DEFAULT_ORACLES: tuple[type[OracleBase], ...] = (
    UnhandledException,
    DeadlockOracle,
    LivelockOracle,
    TimeBudgetOracle,
)


class _InvalidScenarioError(TypeError):
    """Separate API misuse from TypeError raised inside legitimate user code."""

class _OracleAbortError(Exception):
    """Internal control flow only; Trial exposes the Finding instead."""

class _RunView:

    def __init__(self, loop: ChaosEventLoop, trace: Trace) -> None:
        self.__loop = loop
        self.__trace = trace

    @property
    def step(self) -> int:
        return self.__loop.step

    @property
    def vtime(self) -> float:
        return self.__loop.vtime

    @property
    def ready_count(self) -> int:
        return self.__loop.ready_count

    @property
    def timers_pending(self) -> int:
        return self.__loop.timers_pending

    def pending_tasks(self) -> tuple[TaskInfo, ...]:
        return self.__loop.task_snapshots()

    def trace(self) -> TraceView:
        return TraceView(tuple(self.__trace.steps))

    def captured_errors(self) -> tuple[ErrorInfo, ...]:
        out = []
        for context in self.__loop.exceptions:
            error = context.get("exception")
            if isinstance(error, BaseException):
                out.append(ErrorInfo(type(error).__name__, str(error), failure_site(error)))
            else:
                out.append(
                    ErrorInfo("RuntimeError", str(context.get("message", "callback failed")), None)
                )
        return tuple(out)

@dataclass(frozen=True)
class Trial:
    """One outcome. Step and time counts describe the scenario, before cleanup"""
    seed: int | None
    value: Any
    error: BaseException | None
    trace: Trace
    steps: int
    vtime: float
    findings: tuple[Finding, ...] = ()
    max_steps: int = 1_000_000
    max_time: float | None = None
    custom_checks: bool = False
    replay_divergences: tuple[Divergence, ...] = ()
    unused_decisions: int = 0
    fail_on_task_leak: bool = False

    @property
    def diverged(self) -> bool:
        return any(note.hard for note in self.replay_divergences)

    @property
    def ok(self) -> bool:
        return self.error is None and not any(f.severity is Severity.FAILURE for f in self.findings)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def decisions(self) -> list[int]:
        return self.trace.decisions

    @property
    def digest(self) -> str:
        return self.trace.digest()

    def reproduction(self) -> str:
        bounds = f", max_steps={self.max_steps}, max_time={self.max_time!r}"
        checks = ", oracles=oracles, invariants=invariants" if self.custom_checks else ""
        if self.seed is not None and self.trace.scheduler == "Random":
            schedule = f"seed={self.seed}"
        else:
            schedule = f"scheduler=chaosloop.Replay({self.decisions!r}, strict=True)"
        return f"chaosloop.trial(scenario, {schedule}{bounds}{checks})"

    def report(self, *, trace_limit: int | None = None, show_trace: bool = True) -> str:
        lines = [
            f"{'PASSED' if self.ok else 'FAILED'}  seed={self.seed}  "
            f"scheduler={self.trace.scheduler}"
        ]
        if self.error is not None:
            lines.append(f"  {type(self.error).__name__}: {self.error}")
        for finding in self.findings:
            lines.append(f"  [{finding.severity.value}] {finding.oracle}: {finding.message}")
            if finding.site:
                lines.append(f"    at {finding.site}")
            if finding.detail:
                lines.append(finding.detail)
        deviations = sum(d != 0 for d in self.decisions)
        lines.extend(
            [
                f"  {deviations} deviations from the default schedule, {self.steps} steps",
                f"  virtual time={self.vtime:g}; digest={self.digest}",
                "",
                self.trace.render(limit=trace_limit) if show_trace else "",
                "",
                f"Reproduce: {self.reproduction()}",
                "Use the same scenario, inputs, code, Python, and oracle/invariant configuration.",
            ]
        )
        if self.custom_checks:
            lines.append(
                "Here oracles and invariants are the original explicit arguments (use () if empty)."
            )
        return "\n".join(lines)


def _resolve_scheduler(seed: int | None, scheduler: Scheduler | None) -> Scheduler:
    if seed is not None and scheduler is not None:
        raise TypeError("supply seed or scheduler, not both")
    if seed is not None:
        if type(seed) is not int:
            raise TypeError("seed must be an integer")
        return Random(seed)
    if scheduler is None:
        return Fifo()
    if not isinstance(scheduler, Scheduler):
        raise TypeError("scheduler must implement choose, observe, and decisions")
    return scheduler


def _check_not_running() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError("chaosloop.run/trial cannot run inside an already running event loop")


def _build_oracles(
    oracles: Sequence[Oracle] | None, invariants: Sequence[Invariant]
) -> list[Oracle]:
    if oracles is None:
        selected: list[Oracle] = [make() for make in DEFAULT_ORACLES]
        selected.append(InvariantOracle())  # Makes in-scenario registration work by default.
    else:
        selected = [copy.deepcopy(oracle) for oracle in oracles]
    if any(not isinstance(oracle, Oracle) for oracle in selected):
        raise TypeError("oracles must implement name, on_start, on_step, and on_finish")
    detectors = [o for o in selected if isinstance(o, InvariantOracle)]
    if len(detectors) > 1:
        raise ValueError("supply at most one InvariantOracle")
    if invariants:
        if detectors:
            detectors[0].configured += tuple(invariants)
        else:
            selected.append(InvariantOracle(invariants))
    return selected


async def _invoke(scenario: Scenario) -> Any:
    # Construct inside the running loop: factories may create loop-bound state.
    coroutine = scenario()
    if not inspect.iscoroutine(coroutine):
        raise _InvalidScenarioError("scenario factory must return a fresh coroutine object")
    return await coroutine


async def _join_cancelled(tasks: list[asyncio.Task[Any]]) -> None:
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _shutdown(loop: ChaosEventLoop) -> None:
    """Cancel in creation order, join finally blocks, close async generators."""
    while pending := loop.pending_tasks():
        for task in pending:
            task.cancel()
        loop.run_until_complete(_join_cancelled(pending))
    loop.run_until_complete(loop.shutdown_asyncgens())
    while pending := loop.pending_tasks():
        for task in pending:
            task.cancel()
        loop.run_until_complete(_join_cancelled(pending))
    loop.run_until_complete(loop.shutdown_default_executor())


def _execute(
    scenario: Scenario,
    *,
    seed: int | None,
    scheduler: Scheduler | None,
    max_steps: int,
    max_time: float | None,
    oracles: Sequence[Oracle] | None,
    invariants: Sequence[Invariant],
) -> Trial:
    _check_not_running()
    strategy = _resolve_scheduler(seed, scheduler)
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    clock = VirtualClock(max_time=max_time)
    selected = _build_oracles(oracles, invariants)
    actual_seed = strategy.seed if isinstance(strategy, Random) else None
    trace = Trace(seed=actual_seed, scheduler=type(strategy).__name__)
    findings: list[Finding] = []

    def call_hook(oracle: Oracle, hook: str, *args: Any) -> Finding | None:
        try:
            result = getattr(oracle, hook)(*args)
            if result is not None and not isinstance(result, Finding):
                raise TypeError("oracle hook must return Finding or None")
            return result
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as caught:
            raise OracleExecutionError(
                f"{oracle.name}.{hook} raised {type(caught).__name__}: {caught}"
            ) from caught

    def step_hook(step: Step) -> None:
        for oracle in selected:
            finding = call_hook(oracle, "on_step", ctx, step)
            if finding is not None:
                findings.append(finding)  # Keep WARNINGs too; they do not abort.
                if finding.severity is Severity.FAILURE:
                    raise _OracleAbortError()

    loop = ChaosEventLoop(strategy, clock, trace, max_steps, step_hook=step_hook)
    ctx: RunContext = _RunView(loop, trace)
    inv_oracle = next((o for o in selected if isinstance(o, InvariantOracle)), None)
    token = _inv._bind(loop, inv_oracle)
    value: Any = None
    error: BaseException | None = None
    main: asyncio.Task[Any] | None = None
    aborted = False
    try:
        for oracle in selected:
            call_hook(oracle, "on_start", ctx)
        main = loop.create_task(_invoke(scenario))
        value = loop.run_until_complete(main)
    except _OracleAbortError:
        aborted = True
    except BaseException as caught:
        error = caught
    finally:
        vtime = clock.now
        loop.collect_task_errors()
        completed = (
            main is not None
            and main.done()
            and not aborted
            and not isinstance(error, CONTROL_ERRORS)
        )
        outcome = Outcome(value, error, completed)
        if not isinstance(error, (KeyboardInterrupt, SystemExit, _InvalidScenarioError)):
            for oracle in selected:
                try:
                    finding = call_hook(oracle, "on_finish", ctx, outcome)
                    if finding is not None:
                        findings.append(finding)
                except BaseException as caught:
                    if error is None or isinstance(caught, (KeyboardInterrupt, SystemExit)):
                        error = caught
        _inv._reset(token)
        loop.begin_shutdown()  # Hooks and recording stop before any cleanup steps.
        try:
            _shutdown(loop)
        except BaseException as caught:
            if error is None or isinstance(caught, (KeyboardInterrupt, SystemExit)):
                error = caught
        finally:
            loop.collect_task_errors()
            loop.close()
    if isinstance(error, (KeyboardInterrupt, SystemExit, _InvalidScenarioError)):
        raise error
    if error is None and loop.exceptions:
        captured = loop.exceptions[0].get("exception")
        error = (
            captured
            if isinstance(captured, BaseException)
            else RuntimeError(str(loop.exceptions[0].get("message", "unhandled event loop error")))
        )
    return Trial(
        actual_seed,
        value if error is None else None,
        error,
        trace,
        len(trace.steps),
        vtime,
        tuple(findings),
        max_steps,
        max_time,
        oracles is not None or bool(invariants),
        tuple(strategy.divergences) if isinstance(strategy, Replay) else (),
        strategy.remaining if isinstance(strategy, Replay) else 0,
        any(isinstance(o, TaskLeak) and o.severity is Severity.FAILURE for o in selected),
    )


def run[T](
    coro: Coroutine[Any, Any, T],
    *,
    seed: int | None = None,
    scheduler: Scheduler | None = None,
    max_steps: int = 1_000_000,
    max_time: float | None = None,
    oracles: Sequence[Oracle] | None = None,
    invariants: Sequence[Invariant] = (),
) -> T:
    """Return a value, propagate an error, or raise OracleFailure for a finding."""
    if not inspect.iscoroutine(coro):
        raise TypeError("run() expects a coroutine object; use run(main())")
    try:
        result = _execute(
            lambda: coro,
            seed=seed,
            scheduler=scheduler,
            max_steps=max_steps,
            max_time=max_time,
            oracles=oracles,
            invariants=invariants,
        )
    finally:
        coro.close()
    if result.error is not None:
        raise result.error
    if not result.ok:
        raise OracleFailure(result.report())
    return cast(T, result.value)


def trial(
    scenario: Scenario,
    *,
    seed: int | None = None,
    scheduler: Scheduler | None = None,
    max_steps: int = 1_000_000,
    max_time: float | None = None,
    oracles: Sequence[Oracle] | None = None,
    invariants: Sequence[Invariant] = (),
) -> Trial:
    """Run fresh work; capture scenario failures and oracle findings.

    None enables fresh defaults including InvariantOracle. An explicit sequence
    replaces defaults; () leaves direct execution errors active. Predicates and
    scenario factories must create/use fresh state for each independent trial.
    """
    if not callable(scenario):
        raise TypeError("trial() expects a coroutine factory; use trial(main)")
    return _execute(
        scenario,
        seed=seed,
        scheduler=scheduler,
        max_steps=max_steps,
        max_time=max_time,
        oracles=oracles,
        invariants=invariants,
    )
