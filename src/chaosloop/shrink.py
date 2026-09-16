"""Search for a simpler schedule that still produces one pinned finding"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from .exceptions import ChaosloopError
from .oracles import Finding, Invariant, InvariantOracle, Oracle, Severity, TaskLeak
from .oracles.base import failure_site
from .runner import DEFAULT_ORACLES, Scenario, Trial, trial
from .schedulers import Replay


class _TrialOptions(TypedDict):
    max_steps: int
    max_time: float | None
    oracles: Sequence[Oracle] | None
    invariants: Sequence[Invariant]


Interesting = Callable[[list[int]], bool]


class ShrinkError(ChaosloopError):
    """The original or final schedule did not reproduce the pinned finding."""


def failure_findings(run: Trial) -> tuple[Finding, ...]:
    """Direct errors still count when the caller explicitly disables oracles."""
    failures = tuple(f for f in run.findings if f.severity is Severity.FAILURE)
    if failures or run.error is None:
        return failures
    return (
        Finding(
            "execution_error",
            Severity.FAILURE,
            f"{type(run.error).__name__}: {run.error}",
            step=run.steps,
            site=failure_site(run.error),
        ),
    )


def _prefix(decisions: Sequence[int]) -> list[int]:
    end = len(decisions)
    while end and decisions[end - 1] == 0:
        end -= 1
    return list(decisions[:end])


def _rank(decisions: Sequence[int]) -> tuple[int, int, int, tuple[int, ...]]:
    return sum(d != 0 for d in decisions), sum(decisions), len(decisions), tuple(decisions)


@dataclass
class ShrinkBudget:
    """A cooperative budget shared by entry checks, search and verification"""

    max_replays: int = 5000
    max_seconds: float = 60.0
    replays_used: int = field(default=0, init=False)
    _started: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.max_replays) is not int or self.max_replays < 0:
            raise ValueError("max_replays must be a nonnegative integer")
        if (
            type(self.max_seconds) not in (int, float)
            or not math.isfinite(self.max_seconds)
            or self.max_seconds < 0
        ):
            raise ValueError("max_seconds must be finite and nonnegative")

    @property
    def elapsed(self) -> float:
        return 0.0 if self._started is None else time.perf_counter() - self._started

    def available(self, reserve: int = 0) -> bool:
        return self.replays_used + reserve < self.max_replays and self.elapsed < self.max_seconds

    @property
    def exhausted(self) -> bool:
        return not self.available()

    def spend(self) -> bool:
        if self._started is None:
            self._started = time.perf_counter()
        if not self.available():
            return False
        self.replays_used += 1
        return True


@dataclass(frozen=True, slots=True)
class _Evidence:
    interesting: bool
    decisions: tuple[int, ...]
    task_ids: tuple[str | None, ...]
    digest: str


class _Search:
    """Callable predicate plus compact evidence; no Trial/tracebacks in cache."""

    def __init__(
        self,
        scenario: Scenario,
        target: Finding,
        budget: ShrinkBudget,
        options: _TrialOptions,
        record_trace: bool,
        reserve: int,
    ) -> None:
        self.scenario, self.target, self.budget = scenario, target, budget
        self.options, self.record_trace, self.reserve = options, record_trace, reserve
        self.cache: dict[tuple[int, ...], _Evidence] = {}
        self.stopped = False
        self.cache_hits = 0

    def remember(self, requested: Sequence[int], run: Trial) -> _Evidence:
        actual = _prefix(run.decisions)
        evidence = _Evidence(
            any(f.signature == self.target.signature for f in failure_findings(run)),
            tuple(actual),
            tuple(run.trace.task_ids[: len(actual)]),
            run.digest,
        )
        self.cache[tuple(requested)] = evidence
        # The canonical prefix describes the actual positional run, including
        # every fallback, followed by FIFO. It is safe to reuse its verdict.
        self.cache.setdefault(tuple(actual), evidence)
        return evidence

    def __call__(self, decisions: list[int]) -> bool:
        if any(type(d) is not int or d < 0 for d in decisions):
            raise ValueError("shrink candidates must contain nonnegative integers")
        key = tuple(decisions)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key].interesting
        if not self.budget.available(self.reserve) or not self.budget.spend():
            self.stopped = True
            return False  # Never accept an untested proposal.
        run = trial(
            self.scenario,
            scheduler=Replay.from_decisions(decisions),
            record_trace=self.record_trace,
            **self.options,
        )
        return self.remember(decisions, run).interesting


def make_interesting(
    scenario: Scenario,
    target: Finding,
    *,
    max_steps: int = 1_000_000,
    max_time: float | None = None,
    oracles: Sequence[Oracle] | None = None,
    invariants: Sequence[Invariant] = (),
    budget: ShrinkBudget | None = None,
    record_trace: bool = False,
) -> Interesting:
    """Memoized positional search, pinned to target.signature (any FAIL finding)"""
    if target.severity is not Severity.FAILURE:
        raise ValueError("target must be a FAILURE finding")
    return _Search(
        scenario,
        target,
        budget if budget is not None else ShrinkBudget(),
        _TrialOptions(
            max_steps=max_steps, max_time=max_time, oracles=oracles, invariants=invariants
        ),
        record_trace,
        reserve=0,
    )


def _stop(interesting: Interesting, budget: ShrinkBudget) -> bool:
    return budget.exhausted or (isinstance(interesting, _Search) and interesting.stopped)


def _accept(candidate: list[int], best: list[int], interesting: Interesting) -> list[int]:
    if not interesting(candidate):
        return best
    actual = (
        list(interesting.cache[tuple(candidate)].decisions)
        if isinstance(interesting, _Search)
        else candidate
    )
    # Lenient invalid indices become 0; using the ACTUAL prefix is essential.
    return actual if _rank(actual) < _rank(best) else best


def zero_spans(decisions: list[int], interesting: Interesting, budget: ShrinkBudget) -> list[int]:
    """Phase A: coarse span zeroing, width <=256, then halve down to one."""
    best = list(decisions)
    width = min(len(best), 256)
    while width >= 1 and not _stop(interesting, budget):
        for start in range(0, len(best), width):
            if _stop(interesting, budget):
                break
            span = best[start : start + width]
            if any(span):  # All-zero spans are free and need no predicate call.
                candidate = best[:start] + [0] * len(span) + best[start + width :]
                best = _accept(candidate, best, interesting)
        width //= 2
    return best


def lower_each(decisions: list[int], interesting: Interesting, budget: ShrinkBudget) -> list[int]:
    """Phase B/D: try at most four lower values per position, repeat on success"""
    best = list(decisions)
    while not _stop(interesting, budget):
        before = tuple(best)
        for index in range(len(best)):
            if index >= len(best) or _stop(interesting, budget):
                break
            value = best[index]
            for smaller in sorted({0, 1, value // 2, value - 1}):
                if 0 <= smaller < value:
                    candidate = best.copy()
                    candidate[index] = smaller
                    accepted = _accept(candidate, best, interesting)
                    if accepted != best:
                        best = accepted
                        break
        if tuple(best) == before:
            break
    return best


def truncate(decisions: list[int], interesting: Interesting, budget: ShrinkBudget) -> list[int]:
    """Phase C: try shorter prefixes, then FIFO forever, never stop execution"""
    best = list(decisions)
    if best and not _stop(interesting, budget):
        best = _accept(_prefix(best), best, interesting)
    low, high = 0, len(best)
    while low < high and not _stop(interesting, budget):
        middle = (low + high) // 2
        candidate = best[:middle]
        accepted = _accept(candidate, best, interesting)
        if accepted != best:
            best, high = accepted, len(accepted)
        else:
            low = middle + 1
    # Look immediately below the current boundary without claiming monotonicity.
    for length in range(max(0, len(best) - 8), len(best)):
        if _stop(interesting, budget):
            break
        best = _accept(best[:length], best, interesting)
    return best


@dataclass
class ShrinkResult:
    original: list[int]
    minimal: list[int]
    original_task_ids: list[str | None] | None
    finding: Finding
    replays: int
    elapsed: float
    hit_budget: bool
    minimal_task_ids: list[str | None]
    final_trial: Trial
    baseline: Trial | None = None
    verified: bool = True
    cache_hits: int = 0

    @property
    def original_deviations(self) -> int:
        return sum(d != 0 for d in self.original)

    @property
    def minimal_deviations(self) -> int:
        return sum(d != 0 for d in self.minimal)

    @property
    def reduction(self) -> float:
        before = self.original_deviations
        return (before - self.minimal_deviations) / before if before else 0.0

    def reproduction(self) -> str:
        run = self.final_trial
        checks = ", oracles=oracles, invariants=invariants" if run.custom_checks else ""
        return (
            f"chaosloop.trial(scenario, scheduler=chaosloop.Replay({self.minimal!r}, "
            f"task_ids={self.minimal_task_ids!r}, strict=True), max_steps={run.max_steps}, "
            f"max_time={run.max_time!r}{checks})"
        )

    def report(self, *, include_timing: bool = False, show_diff: bool = True) -> str:
        from .diff import diff_traces, render_diff

        lines = [
            f"Shrunk: {self.original_deviations} -> {self.minimal_deviations} deviations; "
            f"{len(self.original)} -> {len(self.minimal)} recorded choices "
            f"(+ FIFO continuation; {self.final_trial.steps} executed steps)",
            f"  {self.finding.oracle}: {self.finding.message}",
            f"  {self.replays} replays; {self.cache_hits} cache hits; "
            f"verified={self.verified}; budget reached={self.hit_budget}",
        ]
        if include_timing:
            lines.append(f"  Shrink time: {self.elapsed:.3f}s")
        if show_diff and self.baseline is not None:
            lines.append(
                render_diff(
                    diff_traces(self.baseline.trace, self.final_trial.trace),
                    baseline_label=f"FIFO ({'passes' if self.baseline.ok else 'fails'})",
                    failing_label="shrunk schedule (fails)",
                )
            )
        if not self.verified:
            lines.append("  Budget allowed no verification; original evidence retained unchanged.")
        lines.extend(
            [
                "  Best verified result of a bounded greedy search; no minimality proof.",
                f"Reproduce: {self.reproduction()}",
            ]
        )
        return "\n".join(lines)


def shrink(
    scenario: Scenario,
    failing: Trial,
    *,
    finding: Finding | None = None,
    budget: ShrinkBudget | None = None,
    oracles: Sequence[Oracle] | None = None,
    invariants: Sequence[Invariant] = (),
    record_trace: bool = False,
) -> ShrinkResult:
    """Verify -> A 0 spans -> B lower -> C truncate -> D lower -> verify"""
    failures = failure_findings(failing)
    target = finding if finding is not None else next(iter(failures), None)
    if (
        target is None
        or target.severity is not Severity.FAILURE
        or target.signature not in {f.signature for f in failures}
    ):
        raise ShrinkError("shrink requires a failing Trial containing the target signature")
    if failing.diverged or failing.unused_decisions:
        raise ShrinkError("cannot shrink an unfaithful replay; record a current failure first")
    limits = budget if budget is not None else ShrinkBudget()
    start, used = time.perf_counter(), limits.replays_used
    original = failing.decisions
    ids = failing.trace.task_ids
    if oracles is None and failing.fail_on_task_leak:
        oracles = [make() for make in DEFAULT_ORACLES if make is not TaskLeak]
        oracles = [*oracles, TaskLeak(Severity.FAILURE), InvariantOracle()]
    options = _TrialOptions(
        max_steps=failing.max_steps,
        max_time=failing.max_time,
        oracles=oracles,
        invariants=invariants,
    )
    search = _Search(scenario, target, limits, options, record_trace, reserve=1)
    final, baseline, best, best_ids = failing, None, original.copy(), ids.copy()
    verified = False

    def finish(hit: bool) -> ShrinkResult:
        return ShrinkResult(
            original,
            best,
            ids,
            target,
            limits.replays_used - used,
            time.perf_counter() - start,
            hit,
            best_ids,
            final,
            baseline,
            verified,
            search.cache_hits,
        )

    if not limits.spend():
        return finish(True)
    guard = trial(scenario, scheduler=Replay.from_trace(failing.trace, strict=True), **options)
    if (
        guard.diverged
        or guard.unused_decisions
        or guard.digest != failing.digest
        or target.signature not in {f.signature for f in failure_findings(guard)}
    ):
        raise ShrinkError("original did not reproduce faithfully; reset scenario state and checks")
    final, verified = guard, True
    search.remember(original, guard)
    if limits.available(reserve=1) and limits.spend():
        baseline = trial(scenario, scheduler=Replay([]), **options)
        search.remember([], baseline)
    for phase in (zero_spans, lower_each, truncate, lower_each):
        best = phase(best, search, limits)
    if best == original:
        return finish(search.stopped or limits.exhausted)
    evidence = search.cache[tuple(best)]
    if not limits.spend():
        best, best_ids = original.copy(), ids.copy()
        return finish(True)
    best_ids = list(evidence.task_ids)
    final = trial(scenario, scheduler=Replay(best, task_ids=best_ids, strict=True), **options)
    if (
        final.diverged
        or final.unused_decisions
        or final.digest != evidence.digest
        or target.signature not in {f.signature for f in failure_findings(final)}
    ):
        raise ShrinkError("final candidate did not reproduce; scenario/checks are nondeterministic")
    return finish(search.stopped or limits.exhausted)
