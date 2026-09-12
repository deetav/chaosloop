"""CPython backed scheduling engine, absent from public api
Real Task/Future/Lock semantics remain with asyncio, only callback selection,
timer progression, recording, and deterministic cleanup change here
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import math
from collections import deque
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextvars import Context
from dataclasses import replace
from typing import Any, NoReturn

from .clock import VirtualClock
from .compat import (
    callback_label,
    check_supported,
    coro_location,
    describe_await,
    handle_state,
    is_completion_callback,
    loop_state,
    register_asyncgen,
    task_of,
    unobserved_exception,
    user_coro_location,
)
from .exceptions import Deadlock, StepBudgetExceeded, UnsupportedOperation
from .runtime import TaskInfo
from .schedulers.base import Candidate, Scheduler, StepEvent
from .trace import Step, Trace


class _OrderedTimer(asyncio.TimerHandle):
    """Break equal deadline ties by registration order"""
    def __init__(
            self,
            *args: Any,
            order: int,
            **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.order = order

    def __lt__(self, other: asyncio.TimerHandle) -> bool:
        left = (self.when(), self.order)
        right = (other.when(), other.order if isinstance(other, _OrderedTimer) else -1)
        return left < right

def _unsupported(operation: str) -> NoReturn:
    raise UnsupportedOperation(
        f"chaosloop cannot make {operation} deterministic. "
        "Replace it with an in-memory async fake, or run this scenario with stock asyncio."
    )


class ChaosEventLoop(asyncio.SelectorEventLoop):
    """One scheduler choice per hook invocation, with logical timer turns."""

    def __init__(
        self,
        scheduler: Scheduler,
        clock: VirtualClock | None = None,
        trace: Trace | None = None,
        max_steps: int = 1_000_000,
        step_hook: Callable[[Step], None] | None = None,
    ) -> None:
        check_supported()
        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        self._clock = clock if clock is not None else VirtualClock()
        self._trace = trace if trace is not None else Trace()
        self._scheduler = scheduler
        self._step_hook = step_hook
        self._max_steps = max_steps
        self._steps = 0
        self._recording = True
        self._cleanup_steps = 0
        self._task_counter = itertools.count(1)
        self._timer_counter = itertools.count(1)
        self._tasks: dict[asyncio.Task[Any], str] = {}
        self._turn_pending: dict[int, asyncio.Handle] = {}
        self._generators: dict[int, AsyncGenerator[Any, Any]] = {}
        self.exceptions: list[dict[str, Any]] = []
        self.leftover_tasks: tuple[str, ...] = ()
        super().__init__()
        self.set_task_factory(self._make_task)

    def __del__(self) -> None:
        # Constructor rejection must not cause a second error in the base finalizer.
        if hasattr(self, "_closed"):
            super().__del__()

    def _make_task(
        self, loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, Any], **kwargs: Any
    ) -> asyncio.Task[Any]:
        identity = f"task-{next(self._task_counter)}"
        if kwargs.get("eager_start"):
            _unsupported("eager task execution outside scheduler decisions")
        if kwargs.get("name") is None:
            kwargs["name"] = identity
        task = asyncio.Task(coro, loop=loop, **kwargs)
        self._tasks[task] = identity
        return task

    def _identity(self, task: asyncio.Task[Any]) -> str:
        # Handles from a directly constructed Task can bypass the factory.
        # Discover those in ready-queue order, without hashing names or iterating a set.
        if task not in self._tasks:
            self._tasks[task] = f"task-{next(self._task_counter)}"
        return self._tasks[task]

    def time(self) -> float:
        return self._clock.now

    def create_task[T](
        self,
        coro: Coroutine[Any, Any, T],
        *,
        name: object = None,
        context: Context | None = None,
        **kwargs: Any,
    ) -> asyncio.Task[T]:
        if kwargs.get("eager_start"):
            _unsupported("eager task execution outside scheduler decisions")
        task = super().create_task(coro, name=name, context=context, **kwargs)
        # Some 3.13 patch releases call task.set_name(None) AFTER the factory,
        # turning the name into the string 'None'. Restore our default here.
        if name is None:
            task.set_name(self._identity(task))
        return task

    def call_at[*Ts](
        self,
        when: float,
        callback: Callable[[*Ts], object],
        *args: *Ts,
        context: Context | None = None,
    ) -> asyncio.TimerHandle:
        if not math.isfinite(when):
            raise ValueError("timer deadline must be finite")
        if self.is_closed():
            raise RuntimeError("event loop is closed")
        handle = _OrderedTimer(
            when, callback, args, self, context=context, order=next(self._timer_counter)
        )
        handle_state(handle)._scheduled = True
        heapq.heappush(loop_state(self)._scheduled, handle)
        return handle

    def _prepare_turn(self) -> None:
        state = loop_state(self)
        # A cancelled long timer must neither move time nor exhaust max_time.
        while state._scheduled and state._scheduled[0].cancelled():
            handle = heapq.heappop(state._scheduled)
            handle_state(handle)._scheduled = False
            state._timer_cancelled_count -= 1
        if not any(not handle.cancelled() for handle in state._ready):
            state._ready.clear()
            if state._scheduled and not state._stopping:
                self._clock.advance_to(state._scheduled[0].when())
        while state._scheduled and state._scheduled[0].when() <= self.time():
            handle = heapq.heappop(state._scheduled)
            handle_state(handle)._scheduled = False
            if handle.cancelled():
                state._timer_cancelled_count -= 1
            else:
                state._ready.append(handle)
        # TimerHandle equality can consider separate registrations equal. Object
        # identities are only lookup keys here; they never enter decisions/traces.
        self._turn_pending = {
            id(handle): handle for handle in state._ready if not handle.cancelled()
        }

    def _run_once(self) -> None:
        state = loop_state(self)
        # Timer promotion happens at asyncio-style batch boundaries. Schedulers
        # may still choose any ready callback, including newly enqueued ones.
        if not any(not handle.cancelled() for handle in self._turn_pending.values()):
            self._prepare_turn()
        candidates = self._candidates()
        if not candidates:
            if state._stopping:
                return
            raise Deadlock("nothing runnable and no live timer can wake a pending task")

        if self._recording:
            if self._steps >= self._max_steps:
                raise StepBudgetExceeded(f"exceeded {self._max_steps} scheduling steps")
            choice = self._scheduler.choose(candidates)
            if type(choice) is not int or not 0 <= choice < len(candidates):
                raise ValueError(f"scheduler returned invalid candidate index {choice!r}")
        else:
            # Teardown must not consume Replay or re-hit the scenario budget.
            # A separate cap prevents a cancellation-suppressing task hanging forever.
            self._cleanup_steps += 1
            if self._cleanup_steps > 10_000:
                raise StepBudgetExceeded("cleanup exceeded 10000 steps; task ignored cancellation")
            choice = 0

        chosen = candidates[choice]
        handle = state._ready[chosen.index]
        task = task_of(handle)
        user_before = user_coro_location(task) if task is not None else None
        del state._ready[chosen.index]
        self._turn_pending.pop(id(handle), None)
        if self._recording:
            self._steps += 1
            self._trace.record(
                Step(
                    n=self._steps,
                    vtime=self.time(),
                    chosen=choice,
                    n_candidates=len(candidates),
                    task_id=chosen.task_id,
                    kind=chosen.kind,
                    label=chosen.label,
                    location=chosen.location,
                )
            )
        state._current_handle = handle
        try:
            handle_state(handle)._run()  # Handle._run preserves its contextvars context.
        finally:
            state._current_handle = None
        if self._recording:
            if self._step_hook is not None:
                # Oracles check the state AFTER this callback. Their location is
                # the new user suspension site, not asyncio's sleep implementation.
                location = (user_coro_location(task) if task is not None else None) or user_before
                self._step_hook(replace(self._trace.steps[-1], location=location))
            self._scheduler.observe(
                StepEvent(
                    step=self._steps,
                    vtime=self.time(),
                    chosen=choice,
                    task_id=chosen.task_id,
                    n_candidates=len(candidates),
                )
            )

    def _candidates(self) -> tuple[Candidate, ...]:
        candidates: list[Candidate] = []
        for raw_index, handle in enumerate(loop_state(self)._ready):
            if handle.cancelled():
                continue
            task = task_of(handle)
            identity = self._identity(task) if task is not None else None
            label = callback_label(handle)
            if task is not None:
                kind = "task_wakeup" if "wakeup" in label.lower() else "task_step"
                label = f"{kind}<{task.get_name()}>"
            else:
                kind = "timer" if isinstance(handle, asyncio.TimerHandle) else "callback"
            candidates.append(
                Candidate(
                    index=raw_index,
                    task_id=identity,
                    kind=kind,
                    label=label,
                    location=coro_location(task) if task is not None else None,
                )
            )
        return tuple(candidates)

    def begin_shutdown(self) -> None:
        """Freeze scenario observations before any cancellation or asyncgen close."""
        self._recording = False
        self._clock.max_time = None
        self._turn_pending.clear()
        # A hook can abort just after the main task finishes, leaving its stop
        # callback already queued. Do not let that stale callback stop the NEXT
        # run_until_complete before its cleanup coroutine has even started.
        state = loop_state(self)
        state._ready = deque(h for h in state._ready if not is_completion_callback(h))
        self._candidates()
        self.leftover_tasks = tuple(
            identity for task, identity in self._tasks.items() if not task.done()
        )

    def pending_tasks(self) -> list[asyncio.Task[Any]]:
        """Creation/discovery order, never asyncio.all_tasks() set iteration."""
        return [task for task in self._tasks if not task.done()]

    @property
    def step(self) -> int:
        return self._steps

    @property
    def vtime(self) -> float:
        return self._clock.now

    @property
    def ready_count(self) -> int:
        return sum(not handle.cancelled() for handle in loop_state(self)._ready)

    @property
    def timers_pending(self) -> int:
        return sum(not handle.cancelled() for handle in loop_state(self)._scheduled)

    def task_snapshots(self) -> tuple[TaskInfo, ...]:
        # Discover never-started tasks without iterating asyncio.all_tasks' set.
        self._candidates()
        snapshots = [
            TaskInfo(
                t.get_name(),
                t.done(),
                t.cancelled(),
                user_coro_location(t),
                describe_await(t),
                identity,
            )
            for t, identity in self._tasks.items()
            if not t.done()
        ]
        return tuple(sorted(snapshots, key=lambda t: (t.name, t.task_id)))

    def _asyncgen_firstiter_hook(self, agen: AsyncGenerator[Any, Any]) -> None:
        # Retain generators so garbage collection cannot schedule finalizers at
        # unpredictable points. Close them in first-iteration order at teardown.
        self._generators[id(agen)] = agen
        register_asyncgen(self, agen)

    async def shutdown_asyncgens(self) -> None:
        for generator in tuple(self._generators.values()):
            try:
                await generator.aclose()
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                self.call_exception_handler(
                    {
                        "message": "error closing asynchronous generator",
                        "exception": error,
                    }
                )
        self._generators.clear()

    def collect_task_errors(self) -> None:
        """Holding task references prevents GC timing from deciding when errors appear."""
        for task in self._tasks:
            error = unobserved_exception(task)
            if error is not None:
                self.call_exception_handler(
                    {"message": "unobserved task exception", "exception": error}
                )

    def call_exception_handler(self, context: dict[str, Any]) -> None:
        self.exceptions.append(context.copy())

    def run_in_executor[*Ts, T](
        self,
        executor: Any,
        func: Callable[[*Ts], T],
        *args: *Ts,
    ) -> asyncio.Future[T]:
        _unsupported("thread/process executor work")

    def call_soon_threadsafe[*Ts](
        self,
        callback: Callable[[*Ts], object],
        *args: *Ts,
        context: Context | None = None,
    ) -> asyncio.Handle:
        _unsupported("callbacks submitted from other threads")

    def add_reader[*Ts](self, fd: Any, callback: Callable[[*Ts], Any], *args: *Ts) -> None:
        _unsupported("file-descriptor reads")

    def add_writer[*Ts](self, fd: Any, callback: Callable[[*Ts], Any], *args: *Ts) -> None:
        _unsupported("file-descriptor writes")

    def add_signal_handler[*Ts](self, sig: int, callback: Callable[[*Ts], Any], *args: *Ts) -> None:
        _unsupported("operating-system signals")

    # Block at entry, before inherited methods can try an immediate socket
    # read/write/connect and bypass add_reader/add_writer entirely.
    async def create_connection(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("network connections")

    async def create_server(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("network servers")

    async def create_unix_connection(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("Unix socket connections")

    async def create_unix_server(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("Unix socket servers")

    async def create_datagram_endpoint(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("datagram sockets")

    async def connect_accepted_socket(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("accepted sockets")

    async def connect_read_pipe(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("pipe reads")

    async def connect_write_pipe(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("pipe writes")

    async def getaddrinfo(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("DNS resolution")

    async def getnameinfo(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("DNS resolution")

    async def sock_recv(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket reads")

    async def sock_recv_into(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket reads")

    async def sock_recvfrom(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("datagram reads")

    async def sock_recvfrom_into(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("datagram reads")

    async def sock_sendall(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket writes")

    async def sock_sendto(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("datagram writes")

    async def sock_connect(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket connections")

    async def sock_accept(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket accepts")

    async def sock_sendfile(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("socket file transfers")

    async def sendfile(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("file transfers")

    async def start_tls(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("TLS connections")

    async def subprocess_exec(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("subprocesses")

    async def subprocess_shell(self, *args: Any, **kwargs: Any) -> Any:
        _unsupported("subprocesses")
