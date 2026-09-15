"""Identity is followed before position; only absent/range are hard."""

from dataclasses import asdict

import pytest

import chaosloop as c
from chaosloop.corpus import LegacyCorpusWarning, entry_from_data
from chaosloop.schedulers import Candidate


def queue(*names):
    return tuple(Candidate(i, name, "task_step", "resume", None) for i, name in enumerate(names))


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_drift_follows_identity(strict, position):
    tasks = ["other-a", "other-b"]
    tasks.insert(position, "wanted")
    replay = c.Replay([2], task_ids=["wanted"], strict=strict)
    assert replay.choose(queue(*tasks)) == position
    assert not replay.diverged
    assert [d.kind for d in replay.divergences] == ([] if position == 2 else ["drift"])


@pytest.mark.parametrize(
    "kind, choices, names",
    [
        ("absent", [0], ["missing"]),
        ("range", [9], [None]),
        ("range", [-1], [None]),
    ],
)
@pytest.mark.parametrize("strict", [False, True])
def test_hard_mismatch(kind, choices, names, strict):
    replay = c.Replay(choices, task_ids=names, strict=strict)
    if strict:
        with pytest.raises(c.ReplayMismatch):
            replay.choose(queue("different"))
        assert replay.decisions == []
    else:
        assert replay.choose(queue("different")) == 0
        assert replay.decisions == [0]
    assert replay.diverged and replay.divergences[0].kind == kind


@pytest.mark.parametrize("strict", [False, True])
def test_exhaustion_is_explicit_soft_fifo(strict):
    replay = c.Replay([], strict=strict)
    assert replay.choose(queue("a", "b")) == 0
    assert replay.divergences[0].kind == "exhausted"
    assert not replay.diverged


def test_duplicate_identity_chooses_first_handle():
    replay = c.Replay([2], task_ids=["a"])
    assert replay.choose(queue("a", "b", "a")) == 0


def test_none_identity_uses_position_and_copies():
    names = [None]
    replay = c.Replay([1], task_ids=names)
    names[0] = "a"
    assert replay.choose(queue("a", "b")) == 1
    replay.decisions.clear()
    replay.divergences.clear()
    assert replay.decisions == [1]


@pytest.mark.parametrize("names", [[], [None, None], [""], [2], [False]])
def test_bad_parallel_identity_vector(names):
    with pytest.raises((ValueError, TypeError)):
        c.Replay([0], task_ids=names)


def test_legacy_migration_warns_and_keeps_positional_replay():
    raw = dict(
        version=1,
        scenario="demo",
        signature="bug",
        seed=2,
        decisions=[0],
        message="failed",
        site=None,
        deviations=0,
        recorded_at="2026-09-14T00:00:00Z",
    )
    with pytest.warns(LegacyCorpusWarning, match="fidelity"):
        entry = entry_from_data(raw)
    assert entry.task_ids is None and entry.format_version == 1
    assert c.Replay(entry.decisions).choose(queue("a")) == 0
    modern = {"version": 2, **asdict(entry), "format_version": 2, "task_ids": ["a"]}
    assert entry_from_data(modern).task_ids == ["a"]


@pytest.mark.parametrize(
    "change", [{"version": 3}, {"format_version": 1}, {"task_ids": []}, {"original_deviations": -1}]
)
def test_modern_corruption_is_rejected(change):
    raw = dict(
        version=2,
        format_version=2,
        scenario="demo",
        signature="bug",
        seed=2,
        decisions=[0],
        task_ids=["a"],
        message="failed",
        site=None,
        deviations=0,
        recorded_at="2026-09-14T00:00:00Z",
    )
    with pytest.raises(ValueError):
        entry_from_data(raw | change)
