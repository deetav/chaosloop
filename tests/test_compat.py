import asyncio
import re

import pytest

import chaosloop
from chaosloop import compat


@pytest.mark.parametrize("task_type", [asyncio.Task, asyncio.tasks._PyTask], ids=["c", "python"])
def test_task_of_recognizes_both_task_implementations(task_type):
    loop = asyncio.new_event_loop()
    async def main():
        await asyncio.sleep(0)
    task = task_type(main(), loop=loop)
    try:
        assert compat.task_of(loop._ready[0]) is task
        loop.run_until_complete(task)
    finally:
        loop.close()

def test_task_of_recognises_future_wakeup_callback():
    loop = asyncio.new_event_loop()
    future = loop.create_future()

    async def main():
        await future

    task = loop.create_task(main())
    try:
        loop.run_until_complete(asyncio.sleep(0))
        future.set_result(None)
        assert compat.task_of(loop._ready[0]) is task
        loop.run_until_complete(task)
    finally:
        loop.close()


def test_task_of_returns_none_for_plain_callback():
    loop = asyncio.new_event_loop()
    try:
        handle = loop.call_soon(lambda: None)
        assert compat.task_of(handle) is None
    finally:
        loop.close()


@pytest.mark.parametrize("value", [None, 42, "not a handle", object()])
def test_task_of_tolerates_nonsense(value):
    assert compat.task_of(value) is None


def test_task_of_tolerates_attribute_access_raising():
    class Broken:
        @property
        def _callback(self):
            raise RuntimeError("broken attribute")

    assert compat.task_of(Broken()) is None


def test_coro_location_is_a_basename_with_line_number():
    loop = asyncio.new_event_loop()

    async def main():
        await asyncio.sleep(0)

    task = loop.create_task(main())
    try:
        location = compat.coro_location(task)
        assert location is not None
        assert re.fullmatch(r"test_compat\.py:\d+", location)
        assert "/" not in location and "\\" not in location
        loop.run_until_complete(task)
        assert compat.coro_location(task) is None
    finally:
        loop.close()


def test_coro_location_tolerates_unknown_objects():
    assert compat.coro_location(object()) is None


def test_coro_location_walks_to_innermost_suspended_coroutine():
    loop = asyncio.new_event_loop()
    blocker = loop.create_future()

    async def inner():
        await blocker

    async def outer():
        await inner()

    task = loop.create_task(outer())
    try:
        loop.run_until_complete(asyncio.sleep(0))
        assert compat.coro_location(task) == f"test_compat.py:{inner.__code__.co_firstlineno + 1}"
        blocker.set_result(None)
        loop.run_until_complete(task)
    finally:
        loop.close()


def test_supported_current_interpreter_passes_probe():
    compat.check_supported()


def test_unsupported_version_is_rejected(monkeypatch):
    monkeypatch.delenv("CHAOSLOOP_ALLOW_UNSUPPORTED", raising=False)
    monkeypatch.setattr(compat.sys, "version_info", (3, 99, 0))
    with pytest.raises(chaosloop.UnsupportedPython):
        compat.check_supported()


def test_explicit_override_allows_probing_future_python(monkeypatch):
    monkeypatch.setattr(compat.sys, "version_info", (3, 99, 0))
    compat.check_supported(allow_unsupported=True)


def test_environment_override_allows_probing_future_python(monkeypatch):
    monkeypatch.setenv("CHAOSLOOP_ALLOW_UNSUPPORTED", "1")
    monkeypatch.setattr(compat.sys, "version_info", (3, 99, 0))
    compat.check_supported()


def test_override_does_not_skip_private_layout_probe(monkeypatch):
    monkeypatch.setattr(compat, "REQUIRED_LOOP_ATTRS", ("_missing_private_attribute",))
    with pytest.raises(chaosloop.UnsupportedPython, match="_missing_private_attribute"):
        compat.check_supported(allow_unsupported=True)
