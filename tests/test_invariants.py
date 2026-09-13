"""Fail-fast per-step invariants, runtime registration, and fresh state"""

import asyncio

import pytest

import chaosloop as c
from benchmarks.bugs.b03_transfer import scenario as transfer
from tests.oracle_helpers import Context, step


async def answer():
    await asyncio.sleep(0)
    return 42


def test_held_invariant():
    assert c.trial(answer, invariants=[c.Invariant("holds", lambda: True)]).ok


def test_violation_stops_at_exact_final_trace_step_and_user_site():
    result = c.trial(transfer)
    finding = result.findings[0]
    assert not result.ok and result.error is None
    assert finding.step == result.steps == result.trace.steps[-1].n
    assert finding.site.startswith("b03_transfer.py:")
    assert "900" in finding.detail


def test_end_assert_passes_but_fifo_invariant_fails():
    asyncio.run(transfer(check=False))
    assert not c.trial(transfer, scheduler=c.Fifo()).ok


def test_invariant_outside_trial_raises():
    with pytest.raises(RuntimeError):
        c.invariant("bad", lambda: True)


def test_runtime_registration_does_not_accumulate():
    counts = []

    async def scenario():
        count = 0

        def predicate():
            nonlocal count
            count += 1
            return True

        c.invariant("count", predicate)
        await asyncio.sleep(0)
        counts.append(count)

    for _ in range(3):
        assert c.trial(scenario).ok
    assert counts == [1, 1, 1]


def test_runtime_registration_without_detector_is_loud():
    async def scenario():
        c.invariant("x", lambda: True)

    assert isinstance(c.trial(scenario, oracles=()).error, RuntimeError)
    assert c.trial(answer).ok
    with pytest.raises(RuntimeError):
        c.invariant("x", lambda: True)


def test_predicate_error_is_finding():
    def broken():
        raise LookupError("predicate bad")

    result = c.trial(answer, invariants=[c.Invariant("broken", broken)])
    assert result.error is None and not result.ok
    assert "LookupError" in result.findings[0].message


@pytest.mark.parametrize("value", [None, 1, "yes", [], object()])
def test_predicate_requires_actual_bool(value):
    result = c.trial(answer, invariants=[c.Invariant("bad", lambda: value)])
    assert not result.ok and "must return bool" in result.findings[0].message


def test_detail_is_lazy_and_errors_are_visible():
    calls = []

    def detail():
        calls.append(1)
        raise ValueError("details broke")

    assert c.trial(answer, invariants=[c.Invariant("yes", lambda: True, detail=detail)]).ok
    assert not calls
    result = c.trial(answer, invariants=[c.Invariant("no", lambda: False, detail=detail)])
    assert calls == [1] and "detail callback failed" in result.findings[0].detail


def test_warning_does_not_abort_or_hide_later_failure():
    warnings = c.Invariant("warning", lambda: False, c.Severity.WARNING)
    result = c.trial(answer, invariants=[warnings])
    assert result.ok and result.value == 42 and len(result.warnings) == 1
    result = c.trial(answer, invariants=[warnings, c.Invariant("failure", lambda: False)])
    assert not result.ok and "failure" in result.findings[0].message


def test_first_failure_wins_deterministically():
    result = c.trial(
        answer,
        invariants=[c.Invariant("first", lambda: False), c.Invariant("second", lambda: False)],
    )
    assert len(result.findings) == 1 and "first" in result.findings[0].message


def test_on_start_clears_runtime_but_preserves_configured():
    oracle = c.InvariantOracle([c.Invariant("configured", lambda: True)])
    oracle.on_start(Context())
    oracle.add(c.Invariant("runtime", lambda: False))
    assert oracle.on_step(Context(), step()) is not None
    oracle.on_start(Context())
    assert oracle.on_step(Context(), step()) is None
    with pytest.raises(TypeError):
        oracle.add(object())


def test_extra_invariants_merge_with_explicit_invariant_oracle():
    checks = [c.InvariantOracle([c.Invariant("original", lambda: True)])]
    for _ in range(2):
        result = c.trial(answer, oracles=checks, invariants=[c.Invariant("extra", lambda: False)])
        assert "extra" in result.findings[0].message
    assert len(checks[0].configured) == 1


def test_final_callback_is_checked():
    async def scenario():
        state = []
        c.invariant("empty", lambda: not state)
        state.append(1)  # No await: the callback completes immediately after the change.

    result = c.trial(scenario)
    assert not result.ok and result.steps == 1


def test_process_control_in_predicate_is_not_swallowed():
    def stop():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        c.trial(answer, invariants=[c.Invariant("stop", stop)])
