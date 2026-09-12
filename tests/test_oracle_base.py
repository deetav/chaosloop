from dataclasses import FrozenInstanceError, replace

import pytest

import chaosloop as c
from tests.oracle_helpers import Context, step


def finding(**changes):
    return replace(
        c.Finding(
            "invariant",
            c.Severity.FAILURE,
            "balance went negative: -20",
            step = 1,
            site="account.py:42"
        ),
        **changes
    )

@pytest.mark.parametrize(
    "message",
    [
        "balance went negative: -35",
        "balance went negative: 2.25",
        "balance went negative: 1e3"
     ]
)
def test_signature_normalizes_value(message):
    assert finding().signature == finding(message=message, step=100).signature

@pytest.mark.parametrize(
    "changes",
    [
        {"oracle": "other"},
        {"site": "account.py:43"},
        {"severity": c.Severity.WARNING},
        {"message": "different error"},
    ],
)
def test_signature_keeps_bug_identity_fields(changes):
    assert finding().signature != finding(**changes).signature

def test_signature_normalizes_addresses():
    assert (
        finding(message="object 0xabcdef").signature == finding(message="object 0x123456").signature
    )

def test_context_and_trace_are_immutable():
    ctx = Context()
    assert isinstance(ctx, c.RunContext)
    assert ctx.trace().decisions == ()
    assert ctx.trace().digest() == c.Trace().digest()
    with pytest.raises(FrozenInstanceError):
        ctx.trace().steps = (step(),)



