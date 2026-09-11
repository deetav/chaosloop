"""Small, explicit boundary around the CPython private attributes we use.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import deque
from collections.abc import AsyncGenerator, Callable
from types import FrameType
from typing import Any, Protocol, cast

from .exceptions import UnsupportedPython

SUPPORTED_VERSIONS = ((3, 12), (3, 13))
REQUIRED_LOOP_ATTRS = (
    "_ready",
    "_scheduled",
    "_stopping",
    "_run_once",
    "_timer_cancelled_count",
    "_asyncgens",
    "_current_handle",
)
REQUIRED_HANDLE_ATTRS = ("_callback", "_args", "_cancelled", "_run")
REQUIRED_TIMER_ATTRS = ("_when", "_scheduled")


class HandleState(Protocol):
    """Private Handle layout, including the extra TimerHandle fields."""

    _callback: Any
    _args: tuple[Any, ...]
    _cancelled: bool
    _when: float
    _scheduled: bool

    def _run(self) -> None: ...


class LoopState(Protocol):
    """Private loop layout used by the replacement scheduling hook."""

    _ready: deque[asyncio.Handle]
    _scheduled: list[asyncio.TimerHandle]
    _stopping: bool
    _timer_cancelled_count: int
    _current_handle: asyncio.Handle | None


def loop_state(loop: asyncio.AbstractEventLoop) -> LoopState:
    """Keep the private-layout cast in this one compatibility module."""
    return cast(LoopState, loop)


def handle_state(handle: asyncio.Handle) -> HandleState:
    """Timer-specific fields are read only after a TimerHandle check."""
    return cast(HandleState, handle)


def task_types() -> tuple[type[Any], ...]:
    """_PyTask is a different class, not a subclass of the C Task."""
    python_task = getattr(asyncio.tasks, "_PyTask", asyncio.Task)
    return (asyncio.Task, python_task)


def check_supported(allow_unsupported: bool = False) -> None:
    """Check CPython version AND private layouts, opt-in skips version only"""
    opt_in = allow_unsupported or os.environ.get("CHAOSLOOP_ALLOW_UNSUPPORTED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if not opt_in and (
        sys.implementation.name != "cpython" or sys.version_info[:2] not in SUPPORTED_VERSIONS
    ):
        raise UnsupportedPython(
            "chaosloop supports CPython 3.12 and 3.13. "
            "Set CHAOSLOOP_ALLOW_UNSUPPORTED=1 only to probe another interpreter."
        )

    # A separate stock loop avoids recursion through ChaosEventLoop.__init__.
    probe = asyncio.SelectorEventLoop()
    try:
        handle = probe.call_soon(lambda: None)
        timer = probe.call_later(1, lambda: None)
        for obj, attrs in (
            (probe, REQUIRED_LOOP_ATTRS),
            (handle, REQUIRED_HANDLE_ATTRS),
            (timer, REQUIRED_TIMER_ATTRS),
        ):
            missing = [name for name in attrs if not hasattr(obj, name)]
            if missing:
                raise UnsupportedPython(f"{type(obj).__name__} is missing: {', '.join(missing)}")
        handle.cancel()
        timer.cancel()
    finally:
        probe.close()


def task_of(handle: Any) -> asyncio.Task[Any] | None:
    """Find both C and Python task owners, diagnostic inspection never raises."""
    try:
        callback = getattr(handle, "_callback", None)
        owner = getattr(callback, "__self__", None)
        return cast(asyncio.Task[Any], owner) if isinstance(owner, task_types()) else None
    except Exception:
        # Even getattr can raise on an object with a custom descriptor.
        return None


def coro_location(task: asyncio.Task[Any]) -> str | None:
    """Walk native/generator await chains, retain the deepest available frame."""
    try:
        current: Any = task.get_coro()
        seen: set[int] = set()
        frame: FrameType | None = None
        while current is not None and id(current) not in seen:
            seen.add(id(current))  # Membership only: set iteration never affects a trace.
            candidate = (
                getattr(current, "cr_frame", None)
                or getattr(current, "gi_frame", None)
                or getattr(current, "ag_frame", None)
            )
            if isinstance(candidate, FrameType):
                frame = candidate
            current = (
                getattr(current, "cr_await", None)
                or getattr(current, "gi_yieldfrom", None)
                or getattr(current, "ag_await", None)
            )
        if frame is None:
            return None
        filename = frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        return f"{filename}:{frame.f_lineno}"
    except Exception:
        return None


def callback_label(handle: asyncio.Handle) -> str:
    """Never use repr(callback): its default form can contain an address."""
    callback = handle_state(handle)._callback
    return str(getattr(callback, "__qualname__", type(callback).__qualname__))


def unobserved_exception(task: asyncio.Task[Any]) -> BaseException | None:
    """Retrieve only failures the scenario did not already await or inspect."""
    if task.done() and not task.cancelled() and getattr(task, "_log_traceback", False):
        return task.exception()
    return None


def register_asyncgen(loop: asyncio.AbstractEventLoop, agen: AsyncGenerator[Any, Any]) -> None:
    """Delegate to the stock hook through the explicit private-API boundary."""
    hook = cast(Callable[..., None], cast(Any, asyncio.BaseEventLoop)._asyncgen_firstiter_hook)
    hook(loop, agen)
