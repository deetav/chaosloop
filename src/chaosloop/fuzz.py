"""Bounded seed search, deterministic bug grouping, and replay-first persistence."""

from __future__ import annotations

import itertools
import math
import sys
import time
from collections.abc import Callable, Iterable, Sequence, Sized
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from .clock import VirtualClock
from .corpus import DEFAULT_DIR, Corpus, CorpusEntry
from .oracles import Finding, Invariant, Oracle, Severity
from .oracles.base import failure_site
from .runner import Scenario, Trial, _check_not_running, trial
from .schedulers import Random, Replay, Scheduler
from .trace import Trace

SchedulerFactory = Callable[[int], Scheduler]


def _failure_findings(result: Trial) -> tuple[Finding, ...]:
    failures = tuple(f for f in result.findings if f.severity is Severity.FAILURE)
    if failures or result.error is None:
        return failures
    #  Cleanup errors also need a bucket even without an oracle.
    return (
        Finding(
            "execution_error",
            Severity.FAILURE,
            f"{type(result.error).__name__}: {result.error}",
            step=result.steps,
            site=failure_site(result.error),
        ),
    )


def _rank(result: Trial) -> tuple[int, int, int, tuple[int, ...]]:
    #deviations, seed, steps, decisions
    return (
        sum(d != 0 for d in result.decisions),
        result.seed if result.seed is not None else 2**63,
        result.steps,
        tuple(result.decisions),
    )


@dataclass
class Bucket:
    signature: str
    finding: Finding
    exemplar: Trial
    seeds: list[int] = field(default_factory=list)
    count: int = 0

    @property
    def deviations(self) -> int:
        return sum(d != 0 for d in self.exemplar.decisions)


def bucket_failures(trials: Iterable[Trial]) -> list[Bucket]:
    """Count a signature once per trial; retain every distinct FAILURE finding."""
    buckets: dict[str, Bucket] = {}
    for result in trials:
        seen: set[str] = set()
        for finding in _failure_findings(result):
            signature = finding.signature
            if signature in seen:
                continue
            seen.add(signature)
            bucket = buckets.setdefault(signature, Bucket(signature, finding, result))
            bucket.count += 1
            if result.seed is not None:
                bucket.seeds.append(result.seed)
            if _rank(result) < _rank(bucket.exemplar):
                bucket.exemplar, bucket.finding = result, finding
    ordered = sorted(buckets.values(), key=lambda bucket: (-bucket.count, bucket.signature))
    for bucket in ordered:
        bucket.seeds = sorted(set(bucket.seeds))
    return ordered


def _trace_excerpt(result: Trial, limit: int) -> str:
    if limit <= 0:
        return ""
    # Prioritize the finding and actual deviations, with nearby context
    selected: set[int] = set()
    targets = [f.step - 1 for f in result.findings if f.step is not None]
    targets.extend(i for i, step in enumerate(result.trace.steps) if step.chosen != 0)
    if not targets:
        targets = list(range(min(limit, result.steps)))
    for target in targets:
        for index in (target, target - 1, target + 1):
            if 0 <= index < result.steps and len(selected) < limit:
                selected.add(index)
    steps = [result.trace.steps[i] for i in sorted(selected)]
    text = Trace(steps=steps).render()
    if len(steps) < result.steps:
        text += f"\n  ({result.steps - len(steps)} other trace steps omitted)"
    return text


@dataclass
class FuzzResult:
    scenario: str
    trials_run: int = 0
    elapsed: float = 0.0
    failures: list[Trial] = field(default_factory=list)
    warnings: list[Trial] = field(default_factory=list)
    stopped_early: str | None = None
    fresh_trials_run: int = 0 #new seeds explored
    corpus_replayed: int = 0 # saved failures
    corpus_still_failing: int = 0 #same failure still reproduces
    corpus_forgotten: int = 0 # ola failure passes
    corpus_changed: int = 0 # replay fails with different failure

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def buckets(self) -> list[Bucket]:
        return bucket_failures(self.failures)

    @property
    def trials_per_second(self) -> float:
        return self.trials_run / self.elapsed if self.elapsed > 0 else 0.0

    def summary(self) -> str:
        return (
            f"{self.trials_run} trials, {len(self.failures)} failures "
            f"({len(self.buckets)} distinct), {self.elapsed:.3f}s, {self.trials_per_second:.0f}/s"
        )

    def report(
        self,
        *,
        max_buckets: int = 5,
        trace_lines: int = 20,
        show_warnings: bool = False,
        include_timing: bool = False,
    ) -> str:
        """Stable by default. Opt into variable wall-clock measurements explicitly."""
        if max_buckets < 0 or trace_lines < 0:
            raise ValueError("report limits must be nonnegative")
        buckets = self.buckets
        lines = [
            f"chaosloop: {self.scenario}",
            f"  corpus: {self.corpus_replayed} replayed; {self.corpus_still_failing} still fail; "
            f"{self.corpus_forgotten} no longer reproduce (forgotten); "
            f"{self.corpus_changed} changed",
            f"  {self.fresh_trials_run} fresh trials; {len(self.failures)} failing trials "
            f"in {len(buckets)} distinct buckets; "
            f"stopped={self.stopped_early or 'seeds_exhausted'}",
        ]
        if include_timing:
            lines.append(f"  {self.elapsed:.3f}s; {self.trials_per_second:.0f} trials/s")
        if self.ok:
            lines.append("  No failures found in the schedules tried.")
        for number, bucket in enumerate(buckets[:max_buckets], 1):
            lines.extend(
                [
                    "",
                    f"--- Bug {number}: {bucket.count} occurrences; "
                    f"{bucket.deviations} deviations ---",
                    f"  {bucket.finding.oracle}: {bucket.finding.message}",
                    f"  at {bucket.finding.site or '?'}; seed={bucket.exemplar.seed}; "
                    f"steps={bucket.exemplar.steps}",
                ]
            )
            if bucket.finding.detail:
                lines.append(bucket.finding.detail)
            if trace_lines:
                lines.append(_trace_excerpt(bucket.exemplar, trace_lines))
            lines.append(f"  Reproduce: {bucket.exemplar.reproduction()}")
            others = [seed for seed in bucket.seeds if seed != bucket.exemplar.seed]
            if others:
                suffix = f" ({len(others) - 5} more)" if len(others) > 5 else ""
                lines.append(f"  Also found by: {', '.join(map(str, others[:5]))}{suffix}")
        if len(buckets) > max_buckets:
            lines.append(f"  {len(buckets) - max_buckets} additional buckets omitted.")
        warnings = [finding for result in self.warnings for finding in result.warnings]
        if warnings:
            if show_warnings:
                lines.extend(f"  WARNING {f.oracle}: {f.message}" for f in warnings)
            else:
                lines.append(f"  {len(warnings)} warnings suppressed; use show_warnings=True.")
        if any(b.exemplar.custom_checks for b in buckets):
            lines.append(
                "  Repro inputs: scenario, oracles, invariants are the original arguments; "
                "use () for empty checks."
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Progress:
    trials_done: int
    trials_total: int
    failures: int
    distinct: int
    elapsed: float
    current_seed: int | None


def default_progress(progress: Progress) -> None:
    """Write one bounded ASCII bar on terminals; keep redirected CI logs quiet."""
    if not sys.stderr.isatty():
        return
    filled = min(24, int(24 * progress.trials_done / max(progress.trials_total, 1)))
    bar = "#" * filled + "-" * (24 - filled)
    sys.stderr.write(
        f"\r  [{bar}] {progress.trials_done}/{progress.trials_total} "
        f"{progress.failures} failures ({progress.distinct} distinct) {progress.elapsed:.1f}s"
    )
    sys.stderr.flush()


def _scenario_key(scenario: Scenario) -> str:
    module = getattr(scenario, "__module__", type(scenario).__module__)
    name = getattr(scenario, "__qualname__", type(scenario).__qualname__)
    return f"{module}.{name}"


#public search engine
def fuzz(
    scenario: Scenario, #coroutine factory
    *,
    trials: int = 1000, #max fresh schedules to try
    seeds: Iterable[int] | None = None, #custom seed iterable
    scheduler_factory: SchedulerFactory | None = None, #maps seed to scheduler
    max_steps: int = 1_000_000, #per-trial scheduling step limit
    max_time: float | None = None, ## virtual time limit per trial
    oracles: Sequence[Oracle] | None = None,
    invariants: Sequence[Invariant] = (),
    fail_fast: bool = True,
    time_budget: float | None = None, # for entire fuzz campaign (wall clock)
    on_progress: Callable[[Progress], None] | None = None,
    corpus: Corpus | Path | None = DEFAULT_DIR, #persistent store of known failing schedules
) -> FuzzResult:
    """Replay stored failures, then consume at most trials fresh seeds lazily"""

    _check_not_running()
    if not callable(scenario):
        raise TypeError("scenario must be a coroutine factory")
    if type(trials) is not int or trials < 0:
        raise ValueError("trials must be a nonnegative integer")
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    VirtualClock(max_time=max_time)  # Validate even if no trial will run.
    if time_budget is not None and (not math.isfinite(time_budget) or time_budget < 0):
        raise ValueError("time_budget must be finite and nonnegative")
    store = corpus if isinstance(corpus, Corpus) else Corpus(corpus) if corpus is not None else None
    factory = scheduler_factory if scheduler_factory is not None else Random
    source = seeds if seeds is not None else range(trials)
    total = min(trials, len(source)) if isinstance(source, Sized) else trials
    result = FuzzResult(_scenario_key(scenario))
    started = time.perf_counter()
    last_progress = 0
    last_seed: int | None = None
    distinct: set[str] = set()

    def timed_out() -> bool:
        if time_budget is not None and time.perf_counter() - started >= time_budget:
            result.stopped_early = "time_budget"
            return True
        return False

    #throttle progress callback
    def progress(force: bool = False) -> None:
        nonlocal last_progress
        if (
            on_progress is not None
            and result.trials_run != last_progress
            and (force or result.trials_run % 25 == 0)
        ):
            on_progress(
                Progress(
                    result.trials_run,
                    total + result.corpus_replayed,
                    len(result.failures),
                    len(distinct),
                    time.perf_counter() - started,
                    last_seed,
                )
            )
            last_progress = result.trials_run

    def accept(run: Trial) -> None:
        result.trials_run += 1
        if run.warnings:
            result.warnings.append(run)
        if not run.ok:
            result.failures.append(run)
        for finding in _failure_findings(run):
            distinct.add(finding.signature)
            if store is not None:
                store.record(
                    CorpusEntry(
                        result.scenario,
                        finding.signature,
                        run.seed,
                        run.decisions,
                        finding.message,
                        finding.site,
                        sum(d != 0 for d in run.decisions),
                        datetime.now(UTC).isoformat(),
                    )
                )

    try:
        entries = store.load(result.scenario) if store is not None and not timed_out() else []
        for entry in entries:
            if timed_out():
                break
            last_seed = entry.seed
            run = trial(
                scenario,
                scheduler=Replay(entry.decisions),
                max_steps=max_steps,
                max_time=max_time,
                oracles=oracles,
                invariants=invariants,
            )
            run = replace(run, seed=entry.seed)
            result.corpus_replayed += 1
            signatures = {f.signature for f in _failure_findings(run)}
            if entry.signature in signatures:
                result.corpus_still_failing += 1
            elif run.ok:
                if store is not None and store.forget(result.scenario, entry.signature):
                    result.corpus_forgotten += 1
            else:
                result.corpus_changed += 1
            accept(run)
            progress()
            if fail_fast and not run.ok:
                result.stopped_early = "fail_fast"
                break
        if result.stopped_early is None:
            for seed in itertools.islice(source, trials):
                if timed_out():
                    break
                if type(seed) is not int:
                    raise TypeError("every seed must be an integer")
                last_seed = seed
                run = trial(
                    scenario,
                    scheduler=factory(seed),
                    max_steps=max_steps,
                    max_time=max_time,
                    oracles=oracles,
                    invariants=invariants,
                )
                run = replace(run, seed=seed)
                result.fresh_trials_run += 1
                accept(run)
                progress()
                if fail_fast and not run.ok:
                    result.stopped_early = "fail_fast"
                    break
            else:
                if result.fresh_trials_run == trials:
                    result.stopped_early = "trials"
    finally:
        result.elapsed = time.perf_counter() - started
        progress(force=True)
    return result
