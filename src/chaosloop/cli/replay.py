"""Read schedules and distinguish a replay mismatch from a reproduced bug"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..clock import VirtualClock
from ..corpus import CorpusEntry, entry_from_data
from ..schedulers import Replay
from ..trace import Trace
from .specs import ScenarioLoadError


@dataclass(frozen=True)
class SavedSchedule:
    decisions: list[int]
    scenario: str | None = None
    max_steps: int | None = None
    max_time: float | None = None
    fail_on_task_leak: bool = False
    task_ids: list[str | None] | None = None

    @classmethod
    def from_trace(cls, trace: Trace) -> SavedSchedule:
        return cls(trace.decisions, task_ids=trace.task_ids)

    @classmethod
    def from_entry(cls, entry: CorpusEntry) -> SavedSchedule:
        return cls(
            entry.decisions,
            entry.scenario,
            entry.max_steps,
            entry.max_time,
            entry.fail_on_task_leak,
            entry.task_ids,
        )


def read_schedule(path: Path) -> SavedSchedule:
    """Accept raw decisions, Trace JSONL, corpus v1, or a CLI run/replay JSON result"""
    try:
        text = path.read_text(encoding="utf-8")
        try:
            data: Any = json.loads(text)
        except ValueError:
            return SavedSchedule.from_trace(Trace.from_jsonl(text))
        if isinstance(data, dict) and data.get("type") == "metadata":
            return SavedSchedule.from_trace(Trace.from_jsonl(text))
        scenario = None
        steps = seconds = ids = None
        leak = False
        if isinstance(data, dict):
            if "version" in data:
                return SavedSchedule.from_entry(entry_from_data(data))
            if "chaosloop" not in data:
                raise ValueError("expected a CLI result, corpus entry, or decisions list")
            if type(data.get("schema")) is not int or data["schema"] != 1:
                raise ValueError("unsupported CLI schema")
            scenario = data.get("scenario")
            leak = data.get("config", {}).get("fail_on_task_leak", False)
            data = data["result"]
            steps, seconds = data["max_steps"], data["max_time"]
            ids = data.get("task_ids")
            if ids is None and data.get("trace"):
                ids = [row["task_id"] for row in data["trace"]]  # v0.3 CLI compatibility.
            data = data["decisions"]
        if not isinstance(data, list) or any(type(d) is not int or d < 0 for d in data):
            raise ValueError("decisions must be a list of nonnegative integers")
        Replay(data, task_ids=ids)  # One validator owns parallel-vector invariants.
        if scenario is not None and not isinstance(scenario, str):
            raise ValueError("scenario identity must be a string")
        if steps is not None and (type(steps) is not int or steps <= 0):
            raise ValueError("saved max_steps must be positive")
        if seconds is not None and type(seconds) not in (int, float):
            raise ValueError("saved max_time must be numeric")
        VirtualClock(max_time=seconds)
        if type(leak) is not bool:
            raise ValueError("saved fail_on_task_leak must be boolean")
        return SavedSchedule(data, scenario, steps, seconds, leak, ids)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ScenarioLoadError(f"cannot read schedule {path}: {error}") from error
