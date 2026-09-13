"""CLI outputs can be reliably consumed by tools + human"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any

from .. import __version__
from ..fuzz import FuzzResult
from ..oracles import Finding
from ..runner import Trial


def finding_data(finding: Finding) -> dict[str, Any]:
    # Finding to json dict
    return {**asdict(finding), "severity": finding.severity.value, "signature": finding.signature}


def envelope(command: str, **data: Any) -> dict[str, Any]:
    return {"chaosloop": __version__, "schema": 1, "command": command, **data}


def json_value(value: Any, seen: set[int] | None = None) -> Any:
    """Serialize plain data without invoking arbitrary repr or JSON encoders"""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    active = set() if seen is None else seen
    if id(value) in active:
        return {"$unserializable": "cycle"}
    if type(value) in (list, tuple, dict):
        active.add(id(value))
        try:
            if type(value) is dict:
                if all(type(key) is str for key in value):
                    return {key: json_value(item, active) for key, item in value.items()}
                return {
                    "$mapping": [
                        [json_value(k, active), json_value(v, active)] for k, v in value.items()
                    ]
                }
            return [json_value(item, active) for item in value]
        finally:
            active.remove(id(value))
    return {"$unserializable": f"{type(value).__module__}.{type(value).__qualname__}"}


def trial_data(result: Trial) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "seed": result.seed,
        "scheduler": result.trace.scheduler,
        "value": json_value(result.value),
        "error": None
        if result.error is None
        else {"type": type(result.error).__name__, "message": str(result.error)},
        "findings": [finding_data(finding) for finding in result.findings],
        "steps": result.steps,
        "vtime": result.vtime,
        "digest": result.digest,
        "decisions": result.decisions,
        "trace": [asdict(step) for step in result.trace.steps],
        "max_steps": result.max_steps,
        "max_time": result.max_time,
    }


def fuzz_data(result: FuzzResult) -> dict[str, Any]:
    # Keep every occurrence and every bucket
    return {
        "ok": result.ok,
        "scenario": result.scenario,
        "trials_run": result.trials_run,
        "fresh_trials_run": result.fresh_trials_run,
        "elapsed": result.elapsed,
        "stopped_early": result.stopped_early,
        "corpus": {
            "replayed": result.corpus_replayed,
            "still_failing": result.corpus_still_failing,
            "forgotten": result.corpus_forgotten,
            "changed": result.corpus_changed,
            "recorded": result.corpus_recorded,
        },
        "failures": [trial_data(run) for run in result.failures],
        "warnings": [trial_data(run) for run in result.warnings],
        "buckets": [
            {
                "signature": b.signature,
                "count": b.count,
                "seeds": b.seeds,
                "finding": finding_data(b.finding),
                "exemplar": trial_data(b.exemplar),
            }
            for b in result.buckets
        ],
    }


def emit_json(command: str, **data: Any) -> None:
    print(json.dumps(envelope(command, **data), ensure_ascii=False, allow_nan=False))
