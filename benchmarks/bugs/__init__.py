"""Intentionally broken in-memory programs; none is a claim about stdlib bugs."""

from . import (
    b01_lost_update,
    b02_cache_stampede,
    b03_transfer,
    b04_lock_order,
    b05_semaphore,
    b06_task_leak,
    b07_lost_signal,
    b08_queue_shutdown,
    b09_cancel_cleanup,
    b10_lock_timeout,
    b11_shared_backoff,
    b12_circular_wait,
    b13_circuit_breaker,
    b14_pool_checkout,
    b15_late_shutdown_task,
)

BUGS = (
    b01_lost_update,
    b02_cache_stampede,
    b03_transfer,
    b04_lock_order,
    b05_semaphore,
    b06_task_leak,
    b07_lost_signal,
    b08_queue_shutdown,
    b09_cancel_cleanup,
    b10_lock_timeout,
    b11_shared_backoff,
    b12_circular_wait,
    b13_circuit_breaker,
    b14_pool_checkout,
    b15_late_shutdown_task,
)

FIFO_DETECTABLE = {
    "b03": "Per-step conservation fails even when the final balance is correct.",
    "b06": "The deliberately orphaned helper leaks under every schedule.",
}


def settings(bug):
    """Every caller must use the same per-bug oracle/budget configuration."""
    import chaosloop as c
    from chaosloop.runner import DEFAULT_ORACLES

    checks = None
    if bug.EXPECTED_ORACLE == "task_leak":
        checks = [make() for make in DEFAULT_ORACLES if make is not c.TaskLeak]
        checks += [c.TaskLeak(c.Severity.FAILURE), c.InvariantOracle()]
    return {"oracles": checks, "max_time": getattr(bug, "MAX_TIME", None)}
