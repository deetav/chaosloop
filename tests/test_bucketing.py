from dataclasses import replace

import pytest

import chaosloop as c
from tests.oracle_helpers import step


def trial(seed=7, choices=(0, 1), message="balance negative: -20", site="user.py:4", findings=None):
    trace = c.Trace(steps=[step(i + 1, choice) for i, choice in enumerate(choices)])
    fs = (c.Finding("invariant", c.Severity.FAILURE, message, step=len(choices), site=site),)
    return c.Trial(seed, None, None, trace, len(choices), 0.0, fs if findings is None else findings)


def test_same_bug_numeric_variants_merge():
    buckets = c.bucket_failures([trial(), trial(9, message="balance negative: -35")])
    assert len(buckets) == 1 and buckets[0].count == 2 and buckets[0].seeds == [7, 9]


def test_distinct_sites_and_shapes_stay_separate():
    assert (
        len(c.bucket_failures([trial(), trial(site="user.py:5"), trial(message="cache failed")]))
        == 3
    )


def test_exemplar_prefers_fewer_deviations_then_lowest_seed():
    best = trial(99, (0,))
    bucket = c.bucket_failures([trial(1, (1, 1)), best])[0]
    assert bucket.exemplar is best and bucket.deviations == 0
    shorter = trial(9, (0,))
    lower_seed = trial(2, (0, 0))
    assert c.bucket_failures([shorter, lower_seed])[0].exemplar is lower_seed


def test_none_seed_orders_deterministically():
    assert c.bucket_failures([trial(None, (0,)), trial(7, (0,))])[0].exemplar.seed == 7


def test_one_trial_can_contribute_distinct_findings_once_each():
    a = c.Finding("a", c.Severity.FAILURE, "bad")
    b = c.Finding("b", c.Severity.FAILURE, "bad")
    buckets = c.bucket_failures([trial(findings=(a, a, b))])
    assert len(buckets) == 2 and all(bucket.count == 1 for bucket in buckets)


def test_warnings_do_not_form_bug_buckets():
    warning = c.Finding("x", c.Severity.WARNING, "warn")
    assert c.bucket_failures([trial(findings=(warning,))]) == []


def test_direct_errors_without_oracles_get_fallback_bucket():
    result = replace(trial(findings=()), error=ValueError("bad"))
    assert c.bucket_failures([result])[0].finding.oracle == "execution_error"


def test_order_is_count_then_signature_and_seed_list_sorted_unique():
    a = trial(9, message="a")
    b = trial(7, message="b")
    buckets = c.bucket_failures([b, a, a, trial(2, message="a")])
    assert buckets[0].count == 3 and buckets[0].seeds == [2, 9]
    assert [x.signature for x in c.bucket_failures([b, a])] == [
        x.signature for x in c.bucket_failures([a, b])
    ]


def test_report_has_source_deviation_repro_and_limits():
    result = c.FuzzResult("user.scenario", failures=[trial(), trial(message="other")])
    report = result.report(max_buckets=1, trace_lines=1)
    assert "user.py:4" in report and "deviations" in report and "Reproduce:" in report
    assert "additional buckets omitted" in report and "trace steps omitted" in report


@pytest.mark.parametrize("kwargs", [{"max_buckets": -1}, {"trace_lines": -1}])
def test_negative_report_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        c.FuzzResult("x").report(**kwargs)


def test_zero_report_limits_and_seed_list_truncation():
    result = c.FuzzResult("x", failures=[trial(i) for i in range(12)])
    report = result.report(trace_lines=0)
    assert "more)" in report
    assert "Bug 1" not in result.report(max_buckets=0)


def test_none_seed_reproduction_uses_decisions():
    assert "Replay(" in trial(None).reproduction()
