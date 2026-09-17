"""Doctor restores its patches and reports observations without claiming proof"""

import importlib
import json
import os
import random
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace

import pytest

from chaosloop.cli import doctor
from chaosloop.cli.main import main
from chaosloop.cli.specs import load_scenario
from chaosloop.compat import SUPPORTED_VERSIONS


@pytest.mark.parametrize("interrupt", [False, True])
def test_probe_observes_calls_and_always_restores(interrupt):
    originals = (
        time.time,
        time.monotonic,
        time.perf_counter,
        random.random,
        uuid.uuid4,
        os.urandom,
    )
    try:
        with doctor.hazard_probe() as seen:
            time.time()
            time.monotonic()
            time.perf_counter()
            random.random()
            random.randint(1, 2)
            uuid.uuid4()
            if interrupt:
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert {"time.time()", "time.monotonic()", "random.random() [global]", "uuid.uuid4()"} <= seen
    assert originals == (
        time.time,
        time.monotonic,
        time.perf_counter,
        random.random,
        uuid.uuid4,
        os.urandom,
    )


def test_probe_skips_unexecuted_code_and_local_seeded_random():
    with doctor.hazard_probe() as seen:
        random.Random(42).random()
    assert not seen


def test_environment_reports_bad_layout_and_policy(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("layout missing")

    monkeypatch.setattr(doctor, "check_supported", broken)
    monkeypatch.setattr(doctor.asyncio.events, "_event_loop_policy", object())
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    checks = doctor.diagnose_environment()
    assert not checks[1].ok and checks[1].fix
    assert checks[-1].warning and checks[2].ok

def test_environment_without_spec(monkeypatch, capsys):
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    supported = (
        sys.implementation.name == "cpython"
        and sys.version_info[:2] in SUPPORTED_VERSIONS
    )
    assert main(["doctor", "--json"]) == (0 if supported else 1)
    rows = json.loads(capsys.readouterr().out)["checks"]
    assert [row["check"] for row in rows] == [
        "python", "internals", "hash_seed", "policy"
    ]
    assert rows[0]["ok"] is supported
    assert rows[2]["warning"]



def test_clean_scenario_including_actual_hash_seed_workers(capsys):
    supported = (
        sys.implementation.name == "cpython"
        and sys.version_info[:2] in SUPPORTED_VERSIONS
    )
    assert main([
        "doctor",
        "tests.cli_scenarios:clean",
        "--json",
    ]) == (0 if supported else 1)
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert next(c for c in checks if c["check"] == "python")["ok"] is supported
    assert all(
        check["ok"] or check["warning"]
        for check in checks
        if check["check"] != "python"
    )

    assert next(
        c for c in checks if c["check"] == "hazards"
    )["ok"]

def test_clock_use_reports_hazard_next_to_repeatability(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "_cross_process", lambda *args: doctor.Diagnosis("cross_process", True, "stub")
    )
    assert main(["doctor", "tests.cli_scenarios:clock_user"]) == 1
    output = capsys.readouterr().out
    assert output.index("repeatable") < output.index("hazards") < output.index("cross_process")
    assert "time.monotonic()" in output and "loop.time()" in output


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(returncode=3, stderr="bad import", stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout="not json"),
        OSError("cannot start"),
        subprocess.TimeoutExpired("worker", 10),
    ],
)
def test_worker_failure_is_diagnostic(monkeypatch, response):
    def execute(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(doctor.subprocess, "run", execute)
    check = doctor._cross_process(load_scenario("tests.cli_scenarios:clean"), 100, None)
    assert not check.ok and check.fix


def test_hash_seed_mismatch(monkeypatch):
    def execute(*args, **kwargs):
        return SimpleNamespace(
            returncode=0, stderr="", stdout=json.dumps(kwargs["env"]["PYTHONHASHSEED"])
        )

    monkeypatch.setattr(doctor.subprocess, "run", execute)
    assert not doctor._cross_process(load_scenario("tests.cli_scenarios:clean"), 100, 2).ok


def test_repeatability_requires_multiple_runs():
    with pytest.raises(ValueError):
        doctor.diagnose_scenario(load_scenario("tests.cli_scenarios:clean"), runs=1)


def test_worker_entry_protocol(monkeypatch, capsys):
    worker = importlib.import_module("chaosloop.cli._doctor_worker")
    monkeypatch.setattr(worker.sys, "argv", ["worker", "tests.cli_scenarios:noisy", "100", "none"])
    assert worker.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["ok"] and "scenario log" in captured.err
    monkeypatch.setattr(worker.sys, "argv", ["worker", "absent.py", "100", "none"])
    assert worker.main() == 3
