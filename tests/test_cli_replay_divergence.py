import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

import chaosloop as c
from chaosloop.cli import main as cli
from chaosloop.cli.render import render_divergences
from chaosloop.cli.specs import load_scenario


@pytest.fixture
def recorded_case(tmp_path, monkeypatch):

    mode = {"fixed": False, "changed": False}

    async def child():
        await asyncio.sleep(0)

    async def scenario():
        if mode["changed"]:
            return
        await asyncio.gather(child(), child())
        if not mode["fixed"]:
            raise AssertionError("recorded bug")

    ref = replace(load_scenario("tests.cli_scenarios:broken"), factory=scenario)
    monkeypatch.setattr(cli, "load_scenario", lambda spec: ref)
    original = c.trial(scenario)
    finding = next(f for f in original.findings if f.severity is c.Severity.FAILURE)
    store = c.Corpus(tmp_path)
    store.record(
        c.CorpusEntry(
            ref.key,
            finding.signature,
            None,
            original.decisions,
            finding.message,
            finding.site,
            sum(d != 0 for d in original.decisions),
            datetime.now(UTC).isoformat(),
            task_ids=original.trace.task_ids,
        )
    )
    args = ["replay", ref.spec, "--corpus-all", "--corpus", str(tmp_path)]
    return mode, original, store, ref, args


def test_unmodified_corpus_entry_reproduces_exit_one(recorded_case, capsys):
    _, original, _, _, args = recorded_case
    assert cli.main([*args, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "STILL FAILS"
    assert data["result"]["digest"] == original.digest
    assert not data["result"]["diverged"]


def test_fixed_version_is_clean_exit_zero(recorded_case, capsys):
    mode, _, store, ref, args = recorded_case
    mode["fixed"] = True
    assert cli.main([*args, "--forget", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["result"]["ok"] and not data["result"]["diverged"]
    assert data["result"]["unused_decisions"] == 0
    assert data["forgotten"] and not store.load(ref.key)


def test_structurally_changed_version_is_unknown_exit_five(recorded_case, capsys):
    mode, _, store, ref, args = recorded_case
    mode["changed"] = True
    assert cli.main([*args, "--forget"]) == 5
    output = capsys.readouterr().out
    assert "DIVERGED" in output and "cannot confirm the recorded schedule" in output
    assert store.load(ref.key)  # Unknown evidence must never be forgotten.


def test_divergence_names_step_and_missing_task(recorded_case, capsys):
    mode, original, _, _, args = recorded_case
    mode["changed"] = True
    missing = original.trace.steps[1].task_id
    assert missing is not None
    assert cli.main(args) == 5
    output = capsys.readouterr().out
    assert f"expected {missing}" in output
    assert "divergence at step 2: absent" in output


def test_more_than_three_divergences_are_summarized(recorded_case):
    _, original, _, _, _ = recorded_case
    notes = tuple(c.Divergence(i, "absent", 0, f"missing-{i}", 0, 1) for i in range(6))
    output = render_divergences(replace(original, replay_divergences=notes))
    assert output.count("HARD divergence at step") == 3
    assert "3 further divergences suppressed" in output
    assert "missing-3" not in output and "missing-5" not in output


def test_strict_hard_divergence_captures_error_instead_of_continuing(recorded_case, capsys):
    mode, _, _, _, args = recorded_case
    mode["changed"] = True
    assert cli.main([*args, "--json"]) == 5
    lenient = json.loads(capsys.readouterr().out)["result"]
    assert lenient["error"] is None  # Diagnostic only; fallback executed.

    assert cli.main([*args, "--strict", "--json"]) == 5
    strict = json.loads(capsys.readouterr().out)["result"]
    assert strict["error"]["type"] == "ReplayMismatch"
    assert strict["diverged"] and strict["steps"] < lenient["steps"]
