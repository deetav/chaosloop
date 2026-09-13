"""Defensive JSON persistence, atomic replacement, replay-first and forgetting."""

import asyncio
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import chaosloop as c
from chaosloop.corpus import _safe_dirname
from chaosloop.fuzz import _scenario_key

STAMP = "2026-09-12T00:00:00+00:00"


def entry(signature="bug", decisions=None, scenario="user.scenario", seed=7):
    choices = [0, 1] if decisions is None else decisions
    return c.CorpusEntry(
        scenario, signature, seed, choices, "bad", "user.py:4", sum(d != 0 for d in choices), STAMP
    )


def test_roundtrip_and_better_replacement(tmp_path):
    corpus = c.Corpus(tmp_path)
    assert corpus.record(entry())
    assert corpus.load("user.scenario") == [entry()]
    assert not corpus.record(entry(seed=9))
    assert corpus.record(entry(decisions=[0]))
    assert corpus.load("user.scenario")[0].deviations == 0


def test_different_signatures_sort_and_prune(tmp_path):
    corpus = c.Corpus(tmp_path)
    for i in reversed(range(6)):
        corpus.record(entry(str(i), decisions=[1] * i))
    assert [e.deviations for e in corpus.load("user.scenario")] == list(range(6))
    assert corpus.prune("user.scenario", keep=3) == 3
    assert [e.deviations for e in corpus.load("user.scenario")] == [0, 1, 2]
    assert corpus.prune("user.scenario", keep=0) == 3


def test_forget_missing_and_present(tmp_path):
    corpus = c.Corpus(tmp_path)
    assert not corpus.forget("user.scenario", "absent")
    corpus.record(entry())
    assert corpus.forget("user.scenario", "bug")
    assert corpus.load("user.scenario") == []


@pytest.mark.parametrize("keep", [-1, True, 1.5])
def test_invalid_prune_keep(tmp_path, keep):
    with pytest.raises(ValueError):
        c.Corpus(tmp_path).prune("x", keep)


@pytest.mark.parametrize(
    "text", ["not json", "[]", "{}", '{"version":999}', '{"version":1,"unknown":true}']
)
def test_corrupt_entries_warn_without_crashing(tmp_path, text):
    corpus = c.Corpus(tmp_path)
    corpus.record(entry())
    path = next(tmp_path.rglob("*.json"))
    path.write_text(text)
    with pytest.warns(RuntimeWarning, match="skipping corrupt"):
        assert corpus.load("user.scenario") == []
    assert corpus.record(entry())  # Valid new evidence repairs the corrupt entry.


def test_wrong_scenario_and_filename_rejected(tmp_path):
    corpus = c.Corpus(tmp_path)
    corpus.record(entry())
    path = next(tmp_path.rglob("*.json"))
    data = json.loads(path.read_text())
    data["scenario"] = "different"
    path.write_text(json.dumps(data))
    with pytest.warns(RuntimeWarning):
        assert corpus.load("user.scenario") == []
    corpus.record(entry())
    path.rename(path.with_name("wrong.json"))
    with pytest.warns(RuntimeWarning):
        assert corpus.load("user.scenario") == []


@pytest.mark.parametrize(
    "scenario",
    ["module.<lambda>", "module.fn.<locals>.scenario", "../../outside", "..", "a/b", "a?b"],
)
def test_safe_scenario_paths(tmp_path, scenario):
    corpus = c.Corpus(tmp_path)
    assert corpus.record(entry(scenario=scenario))
    assert corpus.load(scenario)[0].scenario == scenario
    assert all(path.resolve().is_relative_to(tmp_path) for path in tmp_path.rglob("*.json"))
    assert _safe_dirname("a/b") != _safe_dirname("a?b")


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": True},
        {"decisions": [-1]},
        {"decisions": [True]},
        {"decisions": "bad"},
        {"deviations": 99},
        {"site": 42},
        {"recorded_at": "bad"},
        {"recorded_at": "2026-09-12T00:00:00"},
        {"recorded_at": "2026-09-12T00:00:00+01:00"},
        {"scenario": ""},
    ],
)
def test_entry_schema_validation(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(entry(), **changes)


def test_entry_defensively_copies_input_decisions():
    choices = [0, 1]
    item = entry(decisions=choices)
    choices.append(1)
    assert item.decisions == [0, 1]


def test_atomic_replace_failure_warns_and_preserves_old_entry(tmp_path, monkeypatch):
    corpus = c.Corpus(tmp_path)
    corpus.record(entry())

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.warns(RuntimeWarning, match="cannot record"):
        assert not corpus.record(entry(decisions=[0]))
    assert corpus.load("user.scenario") == [entry()]
    assert not list(tmp_path.rglob("*.tmp"))


def test_unwritable_root_and_forget_errors_warn(tmp_path, monkeypatch):
    root = tmp_path / "file"
    root.write_text("not a directory")
    with pytest.warns(RuntimeWarning):
        assert not c.Corpus(root).record(entry())
    corpus = c.Corpus(tmp_path / "store")
    corpus.record(entry())

    def fail(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.warns(RuntimeWarning):
        assert not corpus.forget("user.scenario", "bug")


def test_corpus_replay_happens_before_fresh_seeds(tmp_path):
    events = []

    async def scenario():
        events.append("run")
        raise AssertionError("bad")

    corpus = c.Corpus(tmp_path)
    first = c.fuzz(scenario, trials=1, corpus=corpus)
    assert first.failures
    events.clear()

    def factory(seed):
        events.append("fresh")
        return c.Random(seed)

    result = c.fuzz(scenario, trials=2, scheduler_factory=factory, corpus=corpus)
    assert events == ["run"] and result.corpus_replayed == 1
    assert result.corpus_still_failing == 1 and result.fresh_trials_run == 0
    assert result.failures[0].trace.scheduler == "Replay"


def test_fixed_entry_forgotten_and_reported_conservatively(tmp_path):
    broken = True

    async def scenario():
        if broken:
            raise AssertionError("bug")

    corpus = c.Corpus(tmp_path)
    c.fuzz(scenario, trials=1, corpus=corpus)
    broken = False
    result = c.fuzz(scenario, trials=2, corpus=corpus)
    assert result.corpus_forgotten == 1 and result.corpus_replayed == 1
    assert result.fresh_trials_run == 2 and result.trials_run == 3
    assert corpus.load(_scenario_key(scenario)) == []
    assert "no longer reproduce" in result.report()


def test_different_failure_does_not_erase_masked_original(tmp_path):
    kind = 0

    async def scenario():
        if kind == 0:
            raise ValueError("original")
        raise LookupError("different")

    corpus = c.Corpus(tmp_path)
    c.fuzz(scenario, trials=1, corpus=corpus)
    kind = 1
    result = c.fuzz(scenario, trials=1, corpus=corpus)
    assert result.corpus_changed == 1 and result.corpus_forgotten == 0
    assert len(corpus.load(_scenario_key(scenario))) == 2


def test_corpus_none_never_constructs_store(monkeypatch):
    module = importlib.import_module("chaosloop.fuzz")

    class Forbidden:
        def __init__(self, *args):
            raise AssertionError("filesystem touched")

    monkeypatch.setattr(module, "Corpus", Forbidden)

    async def scenario():
        await asyncio.sleep(0)

    assert c.fuzz(scenario, trials=3, corpus=None).ok


def test_disabling_corpus_keeps_default_directory_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        raise ValueError("bug")

    c.fuzz(scenario, corpus=None)
    assert list(tmp_path.iterdir()) == []
