"""Measure detection frequency, report observations"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import chaosloop
from benchmarks.bugs import BUGS
from chaosloop.fuzz import SchedulerFactory


@dataclass(frozen=True)
class Measurement:
    rate: float
    median_first: float | None
    failures: int
    minimum_deviations: int | None


def measure(
    bug: ModuleType, scheduler_factory: SchedulerFactory, trials: int = 1000, repeats: int = 5
) -> Measurement:
    if trials <= 0 or repeats <= 0:
        raise ValueError("trials and repeats must be positive")
    hits = 0
    firsts = []
    deviations = []
    # A leaked task is a warning by default; this benchmark explicitly treats b06's expected leak
    # as a failure
    checks = [chaosloop.TaskLeak(chaosloop.Severity.FAILURE)] if bug.BUG_ID == "b06" else None
    for repeat in range(repeats):
        offset = repeat * trials
        result = chaosloop.fuzz(
            bug.scenario,
            trials=trials,
            seeds=range(offset, offset + trials),
            scheduler_factory=scheduler_factory,
            oracles=checks,
            invariants=bug.invariants(),
            fail_fast=False,
            corpus=None,
        )
        detected = [
            run
            for run in result.failures
            if any(
                f.oracle == bug.EXPECTED_ORACLE and f.severity is chaosloop.Severity.FAILURE
                for f in run.findings
            )
        ]
        hits += len(detected)
        firsts.append(
            min(
                (run.seed - offset + 1 for run in detected if run.seed is not None),
                default=trials + 1,
            )
        )
        deviations.extend(sum(choice != 0 for choice in run.decisions) for run in detected)
    median = statistics.median(firsts)
    return Measurement(
        hits / (trials * repeats),
        median if median <= trials else None,
        hits,
        min(deviations) if deviations else None,
    )


def benchmark(
    bug_module: ModuleType,
    scheduler_factory: SchedulerFactory,
    trials: int = 1000,
    repeats: int = 5,
) -> tuple[float, float | None]:
    """Detection rate and median first-hit position, None means median not reached"""
    result = measure(bug_module, scheduler_factory, trials, repeats)
    return result.rate, result.median_first


def render_results(trials: int = 1000, repeats: int = 5) -> str:
    rows = [
        "Detection measurements",
        "",
        f"{trials} trials per repeat, {repeats} disjoint seed blocks per strategy. "
        "Core defaults, with TaskLeak promoted to FAILURE only for b06. Corpus disabled.",
        "",
        "| Bug | Expected oracle | FIFO rate | Random rate | Random median first | "
        "Observed min deviations (Random) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for bug in BUGS:
        fifo = measure(bug, lambda seed: chaosloop.Fifo(), trials, repeats)
        random = measure(bug, chaosloop.Random, trials, repeats)
        rows.append(
            f"| {bug.BUG_ID} | {bug.EXPECTED_ORACLE} | {fifo.rate:.4f} | {random.rate:.4f} | "
            f"{random.median_first if random.median_first is not None else 'not reached'} | "
            f"{random.minimum_deviations} |"
        )
    rows.extend(
        [
            "Rates are failing trials / attempted trials for the expected oracle "
        ]
    )
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    table = render_results()
    print(table)
    Path(__file__).with_name("results.md").write_text(table, encoding="utf-8")
