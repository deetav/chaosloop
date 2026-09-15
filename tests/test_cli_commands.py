"""Exercise the actual entry function, including machine output and exit codes"""

import importlib
import json
from dataclasses import replace

import pytest

import chaosloop as c
from chaosloop.cli.main import main
from chaosloop.cli.render import json_value
from chaosloop.cli.replay import read_schedule
from chaosloop.cli.specs import ScenarioLoadError, load_scenario

MODULE = "tests.cli_scenarios:"
RACE = "benchmarks.bugs.b01_lost_update:scenario"


@pytest.mark.parametrize(
    "args,code",
    [
        ([], 2),
        (["--help"], 0),
        (["--version"], 0),
        (["run", "--help"], 0),
        (["missing-command"], 2),
        (["run"], 2),
        (["run", MODULE + "clean", "--wat"], 2),
        (["run", MODULE + "clean", "--max-steps", "0"], 2),
        (["run", MODULE + "clean", "--max-time", "nan"], 2),
        (["run", MODULE + "clean", "--max-time", "-1"], 2),
        (["run", MODULE + "clean", "--trace-limit", "-1"], 2),
        (["run", MODULE + "clean", "--seed", "2", "--scheduler", "fifo"], 2),
        (["run", "missing-file.py"], 3),
        (["run", MODULE + "invalid"], 3),
        (["run", MODULE + "exits"], 3),
        (["replay", MODULE + "clean", "--seed", "1", "--decisions", "x"], 2),
        (["replay", MODULE + "clean", "--seed", "1", "--strict"], 2),
        (["replay", MODULE + "clean", "--seed", "1", "--forget"], 2),
    ],
)
def test_exit_contract(args, code):
    assert main(args) == code


@pytest.mark.parametrize(
    "function,code", [("clean", 0), ("broken", 1), ("noisy", 0), ("opaque", 0)]
)
def test_machine_output_is_complete_json(capsys, function, code):
    assert main(["run", MODULE + function, "--json", "--trace-limit", "0"]) == code
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema"] == 1 and data["chaosloop"] == "0.4.0"
    assert len(data["result"]["trace"]) == data["result"]["steps"] > 0
    if function == "noisy":
        assert "scenario log" in captured.err
    if function == "opaque":
        assert data["result"]["value"] == {"$unserializable": "builtins.object"}


def test_json_errors_and_internal_failure(monkeypatch, capsys):
    assert main(["run", "absent.py", "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["exit_code"] == 3
    assert main(["fuzz", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["exit_code"] == 2
    module = importlib.import_module("chaosloop.cli.main")
    monkeypatch.setattr(module, "_run", lambda args: 1 / 0)
    assert main(["run", MODULE + "clean", "--json"]) == 4
    assert "internal error" in json.loads(capsys.readouterr().out)["error"]["message"]


def test_interrupt_exit(monkeypatch, capsys):
    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(importlib.import_module("chaosloop.cli.main"), "_run", interrupt)
    assert main(["run", MODULE + "clean"]) == 130
    assert "interrupted" in capsys.readouterr().err


def test_human_clean_failure_and_trace(capsys):
    assert main(["run", MODULE + "clean"]) == 0
    assert "No findings" in capsys.readouterr().out
    assert main(["run", RACE, "--seed", "2", "--trace"]) == 1
    out = capsys.readouterr().out
    assert "b01_lost_update.py:" in out and "deviations" in out


def test_run_default_random_seed_and_leak_promotion(capsys):
    assert main(["run", MODULE + "clean", "--scheduler", "random", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["seed"] == 0
    assert main(["run", MODULE + "leak"]) == 0
    assert main(["run", MODULE + "leak", "--fail-on-task-leak"]) == 1


def test_save_and_render_trace(tmp_path, capsys):
    path = tmp_path / "trace.jsonl"
    assert main(["run", RACE, "--seed", "2", "--save-trace", str(path)]) == 1
    capsys.readouterr()
    assert main(["trace", str(path), "--deviations-only", "--json", "--limit", "0"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["trace"] and all(step["chosen"] != 0 for step in data["trace"])
    assert main(["trace", str(path), "--format", "jsonl"]) == 0
    assert c.Trace.from_jsonl(capsys.readouterr().out).decisions == read_schedule(path).decisions
    assert main(["trace", str(path), "--limit", "1"]) == 0
    assert main(["run", RACE, "--save-trace", str(tmp_path)]) == 3


@pytest.mark.parametrize("body", ["garbage", "[]", '{"type":"step"}'])
def test_invalid_trace_is_load_error(tmp_path, body):
    path = tmp_path / "trace.jsonl"
    path.write_text(body)
    assert main(["trace", str(path)]) == 3


def test_saved_cli_result_replays_with_budget(tmp_path, capsys):
    assert main(["run", RACE, "--seed", "2", "--max-steps", "100", "--json"]) == 1
    saved = json.loads(capsys.readouterr().out)
    path = tmp_path / "failure.json"
    path.write_text(json.dumps(saved))
    assert main(["replay", RACE, "--decisions", str(path), "--strict", "--json"]) == 1
    replay = json.loads(capsys.readouterr().out)
    assert replay["result"]["digest"] == saved["result"]["digest"]
    assert replay["result"]["max_steps"] == 100
    assert main(["replay", MODULE + "clean", "--decisions", str(path)]) == 3


def test_seed_replay_and_strict_unused_decisions(tmp_path, capsys):
    assert main(["replay", RACE, "--seed", "2"]) == 1
    assert main(["replay", MODULE + "clean", "--seed", "2"]) == 0
    assert "NO LONGER REPRODUCES" in capsys.readouterr().out
    run = c.trial(load_scenario(MODULE + "clean").factory)
    path = tmp_path / "choices.json"
    path.write_text(json.dumps([*run.decisions, 0]))
    assert main(["replay", MODULE + "clean", "--decisions", str(path), "--strict"]) == 3
    path.write_text("[999]")
    assert main(["replay", MODULE + "clean", "--decisions", str(path), "--strict"]) == 3
    assert main(["replay", MODULE + "clean", "--decisions", str(path)]) == 0


def test_corpus_selection_changed_failure_and_forgetting(tmp_path, capsys):
    store = c.Corpus(tmp_path)
    ref = load_scenario(MODULE + "broken")
    c.fuzz(ref.factory, trials=1, corpus=store)
    entries = store.load(ref.key)
    assert len(entries) == 1
    assert main(["replay", ref.spec, "--corpus-all", "--corpus", str(tmp_path), "--forget"]) == 1
    assert store.load(ref.key)  # A failing replay is never erased by --forget.
    assert main(["replay", ref.spec, "--corpus-entry", "not-found", "--corpus", str(tmp_path)]) == 3
    signature = entries[0].signature
    changed = replace(entries[0], signature="a different bug")
    store.forget(ref.key, signature)
    store.record(changed)
    assert (
        main(["replay", ref.spec, "--corpus-entry", "", "--corpus", str(tmp_path), "--forget"]) == 1
    )
    assert "CHANGED FAILURE" in capsys.readouterr().out
    clean_ref = load_scenario(MODULE + "clean")
    store.record(replace(changed, scenario=clean_ref.key))
    assert (
        main(["replay", clean_ref.spec, "--corpus-all", "--corpus", str(tmp_path), "--forget"]) == 0
    )
    assert not store.load(clean_ref.key)
    assert main(["replay", clean_ref.spec, "--corpus-all", "--corpus", str(tmp_path)]) == 3


def test_json_plain_values_cycles_and_mappings():
    loop = []
    loop.append(loop)
    assert json_value(loop) == [{"$unserializable": "cycle"}]
    assert json_value({1: (2, 3)}) == {"$mapping": [[1, [2, 3]]]}
    assert json_value(float("inf")) == {"$unserializable": "builtins.float"}
    assert json_value(3.5) == 3.5


@pytest.mark.parametrize(
    "body",
    [
        "true",
        "[-1]",
        "[false]",
        "{}",
        '{"version":2}',
        '{"chaosloop":"0.4.0","schema":99}',
        '{"decisions":[]}',
    ],
)
def test_invalid_saved_schedule(tmp_path, body):
    path = tmp_path / "invalid.json"
    path.write_text(body)
    with pytest.raises(ScenarioLoadError):
        read_schedule(path)
