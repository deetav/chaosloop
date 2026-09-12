"""Register predicates against state created inside the current scenario"""

import asyncio
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass

from .oracles import Invariant, InvariantOracle, Severity


@dataclass
class _Registration:
    loop: asyncio.AbstractEventLoop
    oracle: InvariantOracle | None
    active: bool = True


_current: ContextVar[_Registration | None] = ContextVar("chaosloop_invariants", default=None)


def invariant(
    name: str,
    predicate: Callable[[], bool],
    *,
    severity: Severity = Severity.FAILURE,
    detail: Callable[[], str] | None = None,
) -> None:
    """Register only inside an active trial with invariant detection enabled."""
    registration = _current.get()
    if registration is None or not registration.active or registration.oracle is None:
        raise RuntimeError("invariant() requires an active chaosloop trial with InvariantOracle")
    if asyncio.get_running_loop() is not registration.loop:
        raise RuntimeError("invariant registration belongs to a different event loop")
    registration.oracle.add(Invariant(name, predicate, severity, detail))


def _bind(
    loop: asyncio.AbstractEventLoop, oracle: InvariantOracle | None
) -> Token[_Registration | None]:
    return _current.set(_Registration(loop, oracle))


def _reset(token: Token[_Registration | None]) -> None:
    registration = _current.get()
    if registration is not None:
        registration.active = False # Child task contexts share this object during cleanup.
    _current.reset(token)
