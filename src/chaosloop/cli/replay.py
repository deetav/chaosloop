"""Read schedules and distinguish a replay mismatch from a reproduced bug"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..corpus import CorpusEntry
from ..trace import Trace
from .specs import ScenarioLoadError


@dataclass(frozen=True)
class SavedSchedule:
    decisions: list[int]
    scenario: str | None = None
    max_steps: int | None = None
    max_time: float | None = None
    fail_on_task_leak: bool = False


def read_schedule(path: Path) -> SavedSchedule:
    """Accept raw decisions, Trace JSONL, corpus v1, or a CLI run/replay JSON result"""
    try:
        text = path.read_text(encoding="utf-8")
        try:
            data: Any = json.loads(text)
        except ValueError:
            return SavedSchedule(Trace.from_jsonl(text).decisions)
        if isinstance(data, dict) and data.get("type") == "metadata":
            return SavedSchedule(Trace.from_jsonl(text).decisions)
        scenario = None
        steps = None
        seconds = None
        leak = False
        if isinstance(data, dict):
            if "chaosloop" in data:
                if type(data.get("schema")) is not int or data["schema"] != 1:
                    raise ValueError("unsupported CLI schema")
                scenario = data.get("scenario")
                leak = data.get("config", {}).get("fail_on_task_leak", False)
                data = data["result"]
                steps, seconds = data["max_steps"], data["max_time"]
            elif "version" in data:
                if type(data["version"]) is not int or data.pop("version") != 1:
                    raise ValueError("unsupported corpus version")
                entry = CorpusEntry(**data)
                scenario = entry.scenario
            else:
                raise ValueError("expected a CLI result, corpus entry, or decisions list")
            data = data["decisions"]
        if not isinstance(data, list) or any(type(d) is not int or d < 0 for d in data):
            raise ValueError("decisions must be a list of nonnegative integers")
        if scenario is not None and not isinstance(scenario, str):
            raise ValueError("scenario identity must be a string")
        if steps is not None and (type(steps) is not int or steps <= 0):
            raise ValueError("saved max_steps must be positive")
        from ..clock import VirtualClock

        if seconds is not None and type(seconds) not in (int, float):
            raise ValueError("saved max_time must be numeric")
        VirtualClock(max_time=seconds)
        if type(leak) is not bool:
            raise ValueError("saved fail_on_task_leak must be boolean")
        return SavedSchedule(data, scenario, steps, seconds, leak)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ScenarioLoadError(f"cannot read schedule {path}: {error}") from error
