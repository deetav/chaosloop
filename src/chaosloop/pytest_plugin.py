"""Run marked async tests through the same trial/fuzz API as the CLI"""

from __future__ import annotations

import inspect
import json
import math
import shlex
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from . import __version__
from .cli.main import _checks
from .fuzz import _failure_findings, fuzz
from .runner import Trial, trial
from .schedulers import Fifo, Random, Replay


class ChaosFixtureWarning(UserWarning):
    """A fixture may carry mutable state from one schedule to the next."""


class ChaosFindingWarning(UserWarning):
    """An oracle warning from an otherwise passing chaos test."""


@dataclass(frozen=True)
class ChaosConfig:
    trials: int = 100
    scheduler: str = "random"
    seed: int | None = None
    max_steps: int = 1_000_000
    max_time: float | None = None
    corpus: bool = True
    fail_fast: bool = True
    fail_on_task_leak: bool = False
    decisions: tuple[int, ...] | None = None


@dataclass
class Stats:
    tests: int = 0
    trials: int = 0
    passed: int = 0
    failed: int = 0
    elapsed: float = 0.0
    recorded: int = 0
    forgotten: int = 0
    replayed: int = 0
    signatures: set[tuple[str, str]] = field(default_factory=set)


# A per-Config stash survives hooks but cannot leak into a second pytester run.
_STATS: pytest.StashKey[Stats] = pytest.StashKey()
_CONFIG: pytest.StashKey[ChaosConfig] = pytest.StashKey()
_FUNCTION: pytest.StashKey[Callable[..., Any]] = pytest.StashKey()
_SAFE_FIXTURES = frozenset(
    {
        "request",
        "tmp_path",
        "tmp_path_factory",
        "capsys",
        "capfd",
        "caplog",
        "monkeypatch",
        "recwarn",
        "pytestconfig",
        "record_property",
    }
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("chaosloop")
    group.addoption("--chaos-trials", type=int, default=None, help="fresh schedules per chaos test")
    group.addoption("--chaos-seed", type=int, default=None, help="run exactly one seeded schedule")
    group.addoption("--chaos-scheduler", choices=("fifo", "random"), default=None)
    group.addoption("--chaos-no-corpus", action="store_true", default=None)
    group.addoption("--chaos-max-steps", type=int, default=None)
    group.addoption("--chaos-max-time", type=float, default=None)
    group.addoption("--chaos-fail-on-task-leak", action="store_true", default=None)
    group.addoption(
        "--chaos-decisions",
        default=None,
        help="one strict replay from a JSON list; mutually exclusive with --chaos-seed",
    )
    parser.addini("chaos_trials", "default fresh schedules per test", default="100")
    parser.addini("chaos_scheduler", "default scheduler: fifo or random", default="random")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "chaos(**options): explore an async test with chaosloop")
    config.stash[_STATS] = Stats()


def _resolve_config(item: pytest.Function, marker: pytest.Mark) -> ChaosConfig:
    """Defaults < ini < nearest marker < command line; None means no CLI override."""
    if marker.args:
        raise pytest.UsageError("chaos marker options must be keyword arguments")
    allowed = set(ChaosConfig.__dataclass_fields__) - {"decisions"}
    unknown = set(marker.kwargs) - allowed
    if unknown:
        raise pytest.UsageError(f"unknown chaos option(s): {', '.join(sorted(unknown))}")
    try:
        values: dict[str, Any] = {
            "trials": int(item.config.getini("chaos_trials")),
            "scheduler": item.config.getini("chaos_scheduler"),
            **marker.kwargs,
        }
        for name in ("trials", "seed", "scheduler", "max_steps", "max_time", "fail_on_task_leak"):
            override = item.config.getoption(f"chaos_{name}")
            if override is not None:
                values[name] = override
        if item.config.getoption("chaos_no_corpus"):
            values["corpus"] = False
        raw = item.config.getoption("chaos_decisions")
        if raw is not None:
            decisions = json.loads(raw)
            if not isinstance(decisions, list) or any(
                type(d) is not int or d < 0 for d in decisions
            ):
                raise ValueError("--chaos-decisions needs a JSON list of nonnegative integers")
            # Explicit replay overrides a marker seed, but two CLI sources are a mistake.
            if item.config.getoption("chaos_seed") is not None:
                raise ValueError("choose --chaos-seed or --chaos-decisions")
            values.update(seed=None, decisions=tuple(decisions))
        result = ChaosConfig(**values)
        for name in ("trials", "max_steps"):
            value = getattr(result, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if result.seed is not None and type(result.seed) is not int:
            raise ValueError("seed must be an integer")
        if result.scheduler not in ("fifo", "random"):
            raise ValueError("scheduler must be fifo or random")
        if result.max_time is not None and (
            type(result.max_time) not in (int, float)
            or not math.isfinite(result.max_time)
            or result.max_time < 0
        ):
            raise ValueError("max_time must be finite and nonnegative")
        for name in ("corpus", "fail_fast", "fail_on_task_leak"):
            if type(getattr(result, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        return result
    except (ValueError, TypeError) as error:
        raise pytest.UsageError(f"{item.nodeid}: invalid chaos configuration: {error}") from error


def _warn_about_fixtures(item: pytest.Function) -> None:
    parameters = set(getattr(getattr(item, "callspec", None), "params", {}))
    plugin_owned = {
        name
        for name, definitions in item._fixtureinfo.name2fixturedefs.items()
        if definitions and definitions[-1].func.__module__ == "pytest_asyncio.plugin"
    }
    plugin_owned.update(
        name
        for name, definition in item._request._fixture_defs.items()
        if definition.func.__module__ == "pytest_asyncio.plugin"
    )
    used = sorted(
        name for name in item.fixturenames if name not in _SAFE_FIXTURES | parameters | plugin_owned
    )
    if used:
        warnings.warn(
            f"{item.nodeid}: fixture(s) {', '.join(used)} are created ONCE per test, "
            "not once per trial. Create per-trial state inside the async test body. "
            "Loop-bound async fixtures cannot be shared with a Chaosloop trial.",
            ChaosFixtureWarning,
            stacklevel=2,
        )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Validate before test execution; malformed markers are usage errors"""
    for item in items:
        if not isinstance(item, pytest.Function):
            continue
        marker = item.get_closest_marker("chaos")
        if marker is None:
            continue
        if not inspect.iscoroutinefunction(item.obj):
            raise pytest.UsageError(f"{item.nodeid}: chaos requires an 'async def' test function")
        item.stash[_CONFIG] = _resolve_config(item, marker)
        item.stash[_FUNCTION] = item.obj


def _reproduction(item: pytest.Function, config: ChaosConfig, run: Trial) -> str:
    selection = str(item.path.resolve()) + "::" + item.nodeid.split("::", 1)[1]
    args = ["pytest", selection, "--chaos-no-corpus", "--chaos-max-steps", str(config.max_steps)]
    if run.trace.scheduler == "Replay" or run.seed is None:
        args += ["--chaos-decisions", json.dumps(run.decisions, separators=(",", ":"))]
    else:
        args += ["--chaos-seed", str(run.seed), "--chaos-scheduler", config.scheduler]
    if config.max_time is not None:
        args += ["--chaos-max-time", str(config.max_time)]
    if config.fail_on_task_leak:
        args += ["--chaos-fail-on-task-leak"]
    return shlex.join(args)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    marker = pyfuncitem.get_closest_marker("chaos")
    if marker is None:
        return None  # Let normal pytest / pytest-asyncio handle its own tests.
    func = pyfuncitem.stash[_FUNCTION]
    config = pyfuncitem.stash[_CONFIG]
    _warn_about_fixtures(pyfuncitem)
    kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}

    def scenario() -> Any:
        return func(**kwargs)

    scenario.__module__ = func.__module__
    scenario.__qualname__ = func.__qualname__
    if hasattr(pyfuncitem, "callspec"):
        scenario.__qualname__ += f"[{pyfuncitem.callspec.id}]"
    stats = pyfuncitem.config.stash[_STATS]
    started = time.perf_counter()
    run: Trial | None
    if config.seed is not None or config.decisions is not None:
        strategy = (
            Replay(config.decisions, strict=True)
            if config.decisions is not None
            else Fifo()
            if config.scheduler == "fifo"
            else Random(config.seed or 0)
        )
        run = trial(
            scenario,
            scheduler=strategy,
            max_steps=config.max_steps,
            max_time=config.max_time,
            oracles=_checks(config.fail_on_task_leak),
        )
        mismatch = config.decisions is not None and len(run.decisions) != len(config.decisions)
        ok = run.ok and not mismatch
        failures = [] if ok else [run]
        observed_warnings = list(run.warnings)
        stats.trials += 1
        report = (
            "Replay mismatch: unused or missing decisions.\n" if mismatch else ""
        ) + run.report(trace_limit=40)
    else:
        result = fuzz(
            scenario,
            trials=config.trials,
            scheduler_factory=Random if config.scheduler == "random" else lambda seed: Fifo(),
            max_steps=config.max_steps,
            max_time=config.max_time,
            oracles=_checks(config.fail_on_task_leak),
            fail_fast=config.fail_fast,
            corpus=pyfuncitem.config.rootpath / ".chaosloop" if config.corpus else None,
        )
        ok, failures = result.ok, result.failures
        observed_warnings = [f for warning_run in result.warnings for f in warning_run.warnings]
        stats.trials += result.trials_run
        stats.recorded += result.corpus_recorded
        stats.forgotten += result.corpus_forgotten
        stats.replayed += result.corpus_replayed
        report = result.report(show_warnings=True)
        run = result.buckets[0].exemplar if failures else None
    stats.tests += 1
    stats.elapsed += time.perf_counter() - started
    stats.passed += int(ok)
    stats.failed += int(not ok)
    stats.signatures.update(
        (pyfuncitem.nodeid, f.signature) for failed in failures for f in _failure_findings(failed)
    )
    if ok:
        # Pytest otherwise hides the passing report, which would silently lose
        # warning-severity findings
        seen = set()
        for finding in observed_warnings:
            if finding.signature not in seen:
                seen.add(finding.signature)
                warnings.warn(
                    f"{finding.oracle}: {finding.message}", ChaosFindingWarning, stacklevel=2
                )
    if not ok:
        assert run is not None
        pytest.fail(
            f"{report}\n\nReproduce this pytest case:\n  {_reproduction(pyfuncitem, config, run)}",
            pytrace=False,
        )
    return True


def pytest_report_header(config: pytest.Config) -> list[str]:
    trials = config.getoption("chaos_trials") or config.getini("chaos_trials")
    scheduler = config.getoption("chaos_scheduler") or config.getini("chaos_scheduler")
    corpus = (
        "disabled" if config.getoption("chaos_no_corpus") else str(config.rootpath / ".chaosloop")
    )
    return [f"chaosloop {__version__}: defaults {trials} trials/test, {scheduler}, corpus {corpus}"]


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    stats = config.stash[_STATS]
    if not stats.tests:
        return
    terminalreporter.section("chaosloop summary")
    terminalreporter.write_line(
        f"{stats.tests} chaos tests; {stats.trials} trials; {stats.elapsed:.2f}s"
    )
    terminalreporter.write_line(
        f"{stats.passed} passed, {stats.failed} failed ({len(stats.signatures)} distinct bugs)"
    )
    terminalreporter.write_line(
        f"corpus: {stats.replayed} replayed, {stats.recorded} entries recorded/replaced, "
        f"{stats.forgotten} forgotten (no longer reproduce)"
    )
