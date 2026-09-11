import json
import re
from dataclasses import asdict, replace
from typing import cast

import pytest

from chaosloop.trace import Step, Trace, Tracer


def step(*, chosen: int = 0, n: int = 1, vtime: float = 0.125) -> Step:
    return Step(n, vtime, chosen, 3, "task-1", "task_step", "resume<task-1>", "demo.py:10")

def encode_row_change(**changes: object) -> str:
    header = {"type": "metadata", "version": 1, "seed": 42, "scheduler": "Random"}
    row = {"type": "step", **asdict(step()), **changes}
    return json.dumps(header) + "\n" + json.dumps(row) + "\n"

def test_trace_implements_recording_protocol() -> None:
    assert isinstance(Trace(), Tracer)

def test_record_preserves_execution_order() -> None:
    trace = Trace()
    first, second = step(), step(n=2, chosen=2)
    trace.record(first)
    trace.record(second)
    assert trace.steps == [first, second]
    assert trace.decisions == [0, 2]


def test_trace_instances_have_independent_step_lists() -> None:
    a, b = Trace(), Trace()
    a.record(step())
    assert b.steps == []


def test_decisions_cannot_mutate_recorded_schedule() -> None:
    trace = Trace([step(chosen=2)])
    external = trace.decisions
    external[0] = 0
    external.append(1)
    assert trace.decisions == [2]


def test_snapshot_is_unchanged_by_future_appends() -> None:
    trace = Trace([step()])
    snapshot = trace.snapshot()
    trace.record(step(n=2))
    assert snapshot == (step(),)
    assert len(trace.steps) == 2


def test_digest_is_16_lowercase_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", Trace([step()]).digest())


def test_equal_schedules_have_equal_digest() -> None:
    assert Trace([step(), step(n=2)]).digest() == Trace([step(), step(n=2)]).digest()


@pytest.mark.parametrize(
    "changed",
    [
        replace(step(), n=2),
        replace(step(), task_id="task-2"),
        replace(step(), chosen=1),
        replace(step(), vtime=0.5),
        replace(step(), kind="task_wakeup"),
        replace(step(), n_candidates=4),
    ],
    ids=["number", "identity", "choice", "time", "kind", "candidate-count"],
)
def test_digest_detects_structural_change(changed: Step) -> None:
    assert Trace([step()]).digest() != Trace([changed]).digest()


@pytest.mark.parametrize(
    "changed",
    [
        replace(step(), label="callback at 0xABCDEF"),
        replace(step(), location="/different/computer/demo.py:999"),
        replace(step(), location=None),
    ],
    ids=["label", "source-location", "missing-location"],
)
def test_digest_ignores_display_fields(changed: Step) -> None:
    assert Trace([step()]).digest() == Trace([changed]).digest()


def test_digest_ignores_seed_and_scheduler_metadata() -> None:
    original = Trace([step()], seed=42, scheduler="Random")
    replay = Trace([step()], seed=None, scheduler="Replay")
    assert original.digest() == replay.digest()


def test_digest_rounds_insignificant_float_difference() -> None:
    a = Trace([step(vtime=0.1 + 0.2)])
    b = Trace([step(vtime=0.3)])
    assert a.digest() == b.digest()


@pytest.mark.parametrize("timestamp", [0, -0.0, 0.0])
def test_equivalent_zero_timestamps_have_the_same_digest(timestamp: float) -> None:
    assert Trace([step(vtime=timestamp)]).digest() == Trace([step(vtime=0.0)]).digest()


def test_json_roundtrip_keeps_digest_when_timestamp_was_an_integer() -> None:
    trace = Trace([step(vtime=1)])
    assert Trace.from_jsonl(trace.to_jsonl()).digest() == trace.digest()


def test_digest_ignores_subnanosecond_difference_away_from_rounding_boundary() -> None:
    assert Trace([step(vtime=0.125)]).digest() == Trace([step(vtime=0.12500000001)]).digest()


def test_digest_depends_on_step_order() -> None:
    a, b = step(), step(n=2, chosen=1)
    assert Trace([a, b]).digest() != Trace([b, a]).digest()


def test_empty_trace_has_stable_digest() -> None:
    assert Trace().digest() == Trace(seed=42, scheduler="Random").digest()


@pytest.mark.parametrize("seed", [None, 0, -1, 2**100])
def test_jsonl_roundtrip_preserves_metadata_and_steps(seed: int | None) -> None:
    original = Trace([step(), step(n=2, chosen=2)], seed=seed, scheduler="Random")
    restored = Trace.from_jsonl(original.to_jsonl())
    assert restored == original
    assert restored.digest() == original.digest()
    assert restored.decisions == original.decisions


def test_jsonl_roundtrip_preserves_empty_trace_metadata() -> None:
    original = Trace(seed=42, scheduler="Random")
    assert Trace.from_jsonl(original.to_jsonl()) == original


def test_jsonl_has_one_complete_json_object_per_line() -> None:
    text = Trace([step(), step(n=2)]).to_jsonl()
    assert text.endswith("\n")
    rows = [json.loads(line) for line in text.splitlines()]
    assert [row["type"] for row in rows] == ["metadata", "step", "step"]


def test_jsonl_roundtrip_preserves_unicode_and_embedded_newlines() -> None:
    original = Trace([replace(step(), label="चरण\nnext", location="नमूना.py:3")])
    assert len(original.to_jsonl().splitlines()) == 2
    assert Trace.from_jsonl(original.to_jsonl()) == original


@pytest.mark.parametrize("text", ["", "  \n\t\n"])
def test_empty_jsonl_is_empty_trace(text: str) -> None:
    assert Trace.from_jsonl(text) == Trace()


def test_blank_lines_in_jsonl_are_ignored() -> None:
    original = Trace([step()])
    assert Trace.from_jsonl("\n" + original.to_jsonl().replace("\n", "\n\n")) == original


@pytest.mark.parametrize("invalid", ["{", "[]", "null", '"text"', "42"])
def test_jsonl_rejects_invalid_first_row(invalid: str) -> None:
    with pytest.raises(ValueError, match="line 1"):
        Trace.from_jsonl(invalid)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"version": True},
        {"seed": "42"},
        {"seed": True},
        {"scheduler": 42},
        {"type": "step"},
        {"unexpected": "field"},
    ],
)
def test_jsonl_rejects_invalid_metadata(changes: dict[str, object]) -> None:
    row = {"type": "metadata", "version": 1, "seed": None, "scheduler": "Fifo", **changes}
    with pytest.raises(ValueError, match="line 1"):
        Trace.from_jsonl(json.dumps(row))


def test_jsonl_requires_metadata_before_steps() -> None:
    with pytest.raises(ValueError, match="metadata"):
        Trace.from_jsonl(json.dumps({"type": "step", **asdict(step())}))


def test_jsonl_rejects_duplicate_metadata() -> None:
    text = Trace().to_jsonl()
    with pytest.raises(ValueError, match="line 2"):
        Trace.from_jsonl(text + text)


@pytest.mark.parametrize(
    "changes",
    [
        {"n": -1},
        {"n": True},
        {"n": "1"},
        {"chosen": -1},
        {"chosen": 3},
        {"chosen": 1.5},
        {"chosen": False},
        {"n_candidates": 0},
        {"n_candidates": True},
        {"vtime": -0.1},
        {"vtime": float("nan")},
        {"vtime": float("inf")},
        {"vtime": float("-inf")},
        {"vtime": True},
        {"vtime": "0.1"},
        {"vtime": 10**400},
        {"task_id": 1},
        {"kind": None},
        {"label": []},
        {"location": 10},
        {"unexpected": "field"},
        {"type": "other"},
    ],
)
def test_jsonl_rejects_invalid_step_data(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="line 2"):
        Trace.from_jsonl(encode_row_change(**changes))


def test_jsonl_rejects_missing_step_field() -> None:
    rows = encode_row_change().splitlines()
    row = json.loads(rows[1])
    del row["chosen"]
    with pytest.raises(ValueError, match="missing"):
        Trace.from_jsonl(rows[0] + "\n" + json.dumps(row))


def test_jsonl_accepts_none_for_optional_display_fields() -> None:
    trace = Trace.from_jsonl(encode_row_change(task_id=None, location=None))
    assert trace.steps[0].task_id is None
    assert trace.steps[0].location is None


def test_render_marks_only_nonfifo_choices() -> None:
    trace = Trace([step(), step(n=2, chosen=2)])
    rendered = trace.render()
    assert rendered.count("←") == 1
    assert "chose #2 of 3" in rendered
    assert "1 deviation from default in 2 steps" in rendered


def test_render_includes_useful_diagnostics() -> None:
    rendered = Trace([step()]).render()
    assert all(text in rendered for text in ("task-1", "resume<task-1>", "demo.py:10", "0.125"))


def test_render_handles_missing_task_location_and_label() -> None:
    rendered = Trace([replace(step(), task_id=None, location=None, label="")]).render()
    assert "task_step" in rendered
    assert "None" not in rendered


def test_render_zero_limit_displays_no_step_rows() -> None:
    rendered = Trace([step()]).render(limit=0)
    assert "resume<task-1>" not in rendered
    assert "1 more steps" in rendered


def test_render_limit_keeps_summary_for_entire_trace() -> None:
    trace = Trace([step(), step(n=2, chosen=1), step(n=3, chosen=2)])
    rendered = trace.render(limit=1)
    assert rendered.count("resume<task-1>") == 1
    assert "2 more steps" in rendered
    assert "2 deviations from default in 3 steps" in rendered


def test_render_large_limit_does_not_add_omission_message() -> None:
    assert "more steps" not in Trace([step()]).render(limit=100)


@pytest.mark.parametrize("invalid", [-1, 1.5, True])
def test_render_rejects_invalid_limit(invalid: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        Trace().render(limit=cast("int", invalid))


def test_render_empty_trace_has_header_and_summary() -> None:
    rendered = Trace().render()
    assert "vtime" in rendered
    assert "0 deviations from default in 0 steps" in rendered

