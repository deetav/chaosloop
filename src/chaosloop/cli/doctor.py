"""Bounded reproducibility diagnostics, not a proof of determinism"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ..compat import SUPPORTED_VERSIONS, check_supported
from ..runner import Trial, trial
from .render import json_value
from .specs import ScenarioRef

_PACKAGE = Path(__file__).resolve().parents[1]
_ASYNCIO = Path(asyncio.__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Diagnosis:
    check: str
    ok: bool
    message: str
    fix: str | None = None
    warning: bool = False


@contextmanager
def hazard_probe() -> Iterator[set[str]]:
    """Record exercised sources and restore every patch even on interruption."""
    seen: set[str] = set()
    originals: list[tuple[ModuleType, str, Any]] = []

    def spy(module: ModuleType, name: str, label: str) -> None:
        real = getattr(module, name)
        originals.append((module, name, real))

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            caller = Path(sys._getframe(1).f_code.co_filename).resolve()
            # Virtual-loop setup and the fuzzer's own measurements are not
            # evidence that the scenario depends on a wall clock.
            if not caller.is_relative_to(_PACKAGE) and not caller.is_relative_to(_ASYNCIO):
                seen.add(label)
            return real(*args, **kwargs)

        setattr(module, name, wrapper)

    try:
        for name in ("time", "monotonic", "perf_counter"):
            spy(time, name, f"time.{name}()")
        for name in ("random", "randint", "randrange", "choice", "shuffle", "getrandbits"):
            spy(random, name, f"random.{name}() [global]")
        spy(uuid, "uuid4", "uuid.uuid4()")
        spy(os, "urandom", "os.urandom()")
        yield seen
    finally:
        for module, name, real in reversed(originals):
            setattr(module, name, real)


def diagnose_environment() -> list[Diagnosis]:
    supported = sys.implementation.name == "cpython" and sys.version_info[:2] in SUPPORTED_VERSIONS
    checks = [
        Diagnosis(
            "python",
            supported,
            f"{sys.implementation.name} {sys.version.split()[0]}",
            None if supported else "Use CPython 3.12 or 3.13.",
        )
    ]
    try:
        check_supported(allow_unsupported=True)
        checks.append(Diagnosis("internals", True, "event loop and callback layouts present"))
    except Exception as error:
        checks.append(Diagnosis("internals", False, str(error), "Use a supported CPython build."))
    hash_seed = os.environ.get("PYTHONHASHSEED")
    fixed_hash = hash_seed is not None and hash_seed != "random"
    checks.append(
        Diagnosis(
            "hash_seed",
            fixed_hash,
            f"PYTHONHASHSEED={hash_seed or 'unset'}",
            None
            if fixed_hash
            else "Use stable ordering; fix PYTHONHASHSEED for cross-process repro.",
            warning=not fixed_hash,
        )
    )
    # Reading the existing policy avoids creating a global policy as a side effect.
    policy = getattr(asyncio.events, "_event_loop_policy", None)
    stock = policy is None or type(policy) is asyncio.DefaultEventLoopPolicy
    checks.append(
        Diagnosis(
            "policy",
            stock,
            "default asyncio policy" if stock else "custom asyncio policy installed",
            None
            if stock
            else "Chaosloop owns its loop; verify integrations that assume another policy.",
            warning=not stock,
        )
    )
    return checks


def fingerprint(run: Trial) -> dict[str, Any]:
    """Compare schedule AND plain return data/findings, without address-based repr."""
    return {
        "digest": run.digest,
        "ok": run.ok,
        "value": json_value(run.value),
        "error": None if run.error is None else [type(run.error).__name__, str(run.error)],
        "findings": [finding.signature for finding in run.findings],
    }


def _cross_process(ref: ScenarioRef, max_steps: int, max_time: float | None) -> Diagnosis:
    values = []
    for hash_seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        # The worker must see the same package and scenario modules as this CLI
        env["PYTHONPATH"] = os.pathsep.join(str(Path(p or ".").resolve()) for p in sys.path)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "chaosloop.cli._doctor_worker",
                    ref.spec,
                    str(max_steps),
                    "none" if max_time is None else str(max_time),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode != 0:
                return Diagnosis(
                    "cross_process",
                    False,
                    f"worker failed for hash seed {hash_seed}: {completed.stderr.strip()}",
                    "Ensure the scenario imports and runs in a fresh process.",
                )
            values.append(json.loads(completed.stdout))
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            return Diagnosis(
                "cross_process",
                False,
                f"worker unavailable: {error}",
                "Check imports and synchronous blocking work; workers have a 10s limit.",
            )
    stable = all(value == values[0] for value in values[1:])
    return Diagnosis(
        "cross_process",
        stable,
        "compared schedule/outcome under PYTHONHASHSEED 0, 1, 12345",
        None if stable else "Sort unordered inputs and remove process-dependent state.",
    )


def diagnose_scenario(
    ref: ScenarioRef,
    *,
    runs: int = 10,
    max_steps: int = 50_000,
    max_time: float | None = 60.0,
) -> list[Diagnosis]:
    if runs < 2:
        raise ValueError("repeatability needs at least two runs")
    attempts = [
        trial(ref.factory, seed=1234, max_steps=max_steps, max_time=max_time) for _ in range(runs)
    ]
    first = attempts[0]
    checks = [
        Diagnosis(
            "execution",
            first.ok,
            f"scenario executed: {first.steps} steps, {first.vtime:g} virtual seconds",
            None if first.ok else "Inspect the run report: the scenario produced a failure.",
        )
    ]
    stable = all(fingerprint(run) == fingerprint(first) for run in attempts[1:])
    checks.append(
        Diagnosis(
            "repeatable",
            stable,
            f"same seed: compared schedule and outcome in {runs} runs",
            None if stable else "Reset state inside the coroutine; inspect the hazard check below.",
        )
    )
    with hazard_probe() as seen:
        trial(ref.factory, seed=1234, max_steps=max_steps, max_time=max_time)
    checks.append(
        Diagnosis(
            "hazards",
            not seen,
            ", ".join(sorted(seen)) or "no selected runtime sources observed",
            "Use loop.time(), a seeded local Random, and injected deterministic IDs."
            if seen
            else None,
        )
    )
    checks.append(_cross_process(ref, max_steps, max_time))
    checks.append(
        Diagnosis(
            "size",
            first.steps < 50_000,
            f"{first.steps} callbacks per first trial",
            "Reduce the scenario before a large seed search." if first.steps >= 50_000 else None,
            warning=first.steps >= 50_000,
        )
    )
    return checks
