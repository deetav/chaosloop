"""Trace alignment, callback identity, bounded context and honest labels"""

from dataclasses import replace

import pytest

from chaosloop import Step, Trace
from chaosloop.diff import diff_traces, render_diff, step_signature


def step(task="a", n=1):
    return Step(n, 0.0, 0, 2, task, "task_step", "resume", "demo.py:10")


def test_signature_ignores_number_time_and_position():
    original = step()
    assert step_signature(original) == step_signature(replace(original, n=99, vtime=4.0, chosen=1))


@pytest.mark.parametrize("field,value", [("task_id", "b"), ("location", "demo.py:11")])
def test_signature_notices_identity_or_location(field, value):
    assert step_signature(step()) != step_signature(replace(step(), **{field: value}))


def test_non_task_callbacks_are_not_all_identical():
    left = replace(step(None), label="set_result", location=None)
    assert step_signature(left) != step_signature(replace(left, label="stop"))


@pytest.mark.parametrize("length", [0, 1, 300])
def test_identical_traces_have_no_fork(length):
    trace = Trace([step(n=n) for n in range(length)])
    rows = diff_traces(trace, trace)
    assert all(row.kind == "same" and not row.is_fork for row in rows)
    assert "No observable fork" in render_diff(rows)


@pytest.mark.parametrize(
    "left,right,kind",
    [(["a"], ["b"], "changed"), ([], ["b"], "only_failing"), (["a"], [], "only_baseline")],
)
def test_one_fork_and_correct_kind(left, right, kind):
    rows = diff_traces(Trace([step(t) for t in left]), Trace([step(t) for t in right]))
    assert len(rows) == 1 and rows[0].is_fork and rows[0].kind == kind
    assert "near step 1" in render_diff(rows)


def test_long_run_keeps_repeated_task_with_auto_junk_disabled():
    left = [step(n=n) for n in range(300)]
    right = left.copy()
    right[150] = step("b", 150)
    rows = diff_traces(Trace(left), Trace(right))
    assert sum(r.kind == "same" for r in rows) >= 299
    assert sum(r.is_fork for r in rows) == 1
    text = render_diff(rows)
    assert "identical steps" in text and len(text.splitlines()) < 17


def test_context_zero_and_tail_cap_are_truthful():
    rows = diff_traces(
        Trace([step("a", n) for n in range(10)]), Trace([step("b", n) for n in range(10)])
    )
    text = render_diff(rows, context=0, max_rows=1)
    assert "9 aligned rows omitted, including 9 differences" in text
    assert text.count("← fork") == 1 and "instead of a" in text


@pytest.mark.parametrize(
    "kwargs", [{"context": -1}, {"max_rows": -1}, {"context": True}, {"max_rows": 0}]
)
def test_limit_validation_and_zero(kwargs):
    rows = diff_traces(Trace([step("a")]), Trace([step("b")]))
    if kwargs.get("max_rows") == 0:
        assert "1 aligned rows omitted" in render_diff(rows, **kwargs)
    else:
        with pytest.raises(ValueError):
            render_diff(rows, **kwargs)


def test_compact_trace_cannot_pretend_to_have_a_diff():
    with pytest.raises(ValueError, match="full traces"):
        diff_traces(Trace(recording=False), Trace())
