"""Versioned, defensive persistence for known failing schedules"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import warnings
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(".chaosloop")
FORMAT_VERSION = 1

class LegacyCorpusWarning(RuntimeWarning):
    """v1 entry usable byt cannot validate recorded task identity"""


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    scenario: str
    signature: str
    seed: int | None
    decisions: list[int]
    message: str
    site: str | None
    deviations: int
    recorded_at: str
    task_ids: list[str | None] | None = None
    format_version: int = FORMAT_VERSION
    original_deviations: int | None = None
    max_steps: int = 1_000_000
    max_time: float | None = None
    fail_on_task_leak: bool = False

    def __post_init__(self) -> None:
        for value in (self.scenario, self.signature, self.message, self.recorded_at):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    "scenario, signature, message, and recorded_at must be nonempty strings"
                )
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("seed must be an integer or null")
        if not isinstance(self.decisions, list) or any(
            type(d) is not int or d < 0 for d in self.decisions
        ):
            raise ValueError("decisions must be a list of nonnegative integers")
        if self.site is not None and not isinstance(self.site, str):
            raise ValueError("site must be a string or null")
        if type(self.deviations) is not int or self.deviations != sum(
            d != 0 for d in self.decisions
        ):
            raise ValueError("deviations must match the recorded decisions")
        timestamp = datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        offset = timestamp.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("recorded_at must be an ISO 8601 UTC timestamp")
        # The public shape remains a list for easy JSON/replay. Copy the caller's
        # list so later mutation of that input does not rewrite this entry.
        object.__setattr__(self, "decisions", list(self.decisions))
        if self.task_ids is not None:
            if not isinstance(self.task_ids, list) or len(self.task_ids) != len(self.decisions):
                raise ValueError("task_ids must be a list parallel to decisions")
            if any(t is not None and (not isinstance(t, str) or not t) for t in self.task_ids):
                raise ValueError("task_ids must contain nonempty strings or null")
            object.__setattr__(self, "task_ids", self.task_ids.copy())
        if type(self.format_version) is not int or self.format_version not in (1, 2):
            raise ValueError("unsupported corpus format version")
        if self.original_deviations is not None and (
            type(self.original_deviations) is not int or self.original_deviations < self.deviations
        ):
            raise ValueError("original_deviations must be >= current deviations")
        if type(self.max_steps) is not int or self.max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        if self.max_time is not None and (
            type(self.max_time) not in (int, float)
            or not math.isfinite(self.max_time)
            or self.max_time < 0
        ):
            raise ValueError("max_time must be finite and nonnegative")
        if type(self.fail_on_task_leak) is not bool:
            raise ValueError("fail_on_task_leak must be boolean")


def _safe_dirname(scenario: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", scenario)[:80].strip(".") or "scenario"
    return f"{slug}-{hashlib.sha256(scenario.encode()).hexdigest()[:12]}"


def _signature_name(signature: str) -> str:
    return hashlib.sha256(signature.encode()).hexdigest()[:32] + ".json"


def _rank(entry: CorpusEntry) -> tuple[int, int, int, tuple[int, ...], bool, bool, int]:
    return (
        entry.deviations,
        sum(entry.decisions),
        len(entry.decisions),
        tuple(entry.decisions),
        entry.task_ids is None,
        entry.original_deviations is None,
        entry.seed if entry.seed is not None else 2**63,
    )


def _read(path: Path, scenario: str) -> CorpusEntry:
    entry = entry_from_data(json.loads(path.read_text(encoding="utf-8")))
    if entry.scenario != scenario or path.name != _signature_name(entry.signature):
        raise ValueError("entry identity does not match its directory/filename")
    return entry


def entry_from_data(raw: Any) -> CorpusEntry:
    """One defensive decoder shared by the store and CLI file reader."""
    if not isinstance(raw, dict):
        raise ValueError("corpus document must be an object")
    data = dict(raw)
    version = data.pop("version", None)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported corpus format version")
    if data.get("format_version", version) != version:
        raise ValueError("conflicting corpus format versions")
    data["format_version"] = version
    if version == 1:
        if data.get("task_ids") is not None:
            raise ValueError("v1 corpus entries cannot contain task identities")
        data["task_ids"] = None
    entry = CorpusEntry(**data)
    if version == 1:
        warnings.warn(
            "v1 corpus entry: task identity unavailable; replay fidelity is reduced",
            LegacyCorpusWarning,
            stacklevel=2,
        )
    return entry


def _warn(message: str, error: Exception) -> None:
    warnings.warn(f"{message}: {error}", RuntimeWarning, stacklevel=3)


class Corpus:
    def __init__(self, root: Path = DEFAULT_DIR) -> None:
        self.root = Path(root)  # Construction alone never creates directories.

    def _directory(self, scenario: str) -> Path:
        return self.root / "failures" / _safe_dirname(scenario)

    def load(self, scenario: str) -> list[CorpusEntry]:
        """Skip corrupt/unreadable entries with warnings; sort independently of disk order."""
        entries = []
        try:
            paths = sorted(self._directory(scenario).glob("*.json"))
        except OSError as error:
            _warn("cannot list corpus", error)
            return []
        for path in paths:
            try:
                entries.append(_read(path, scenario))
            except (OSError, ValueError, TypeError) as error:
                _warn(f"skipping corrupt corpus entry {path.name}", error)
        return sorted(entries, key=lambda entry: (entry.deviations, entry.signature))

    def record(self, entry: CorpusEntry) -> bool:
        """Keep the better exemplar, then atomically replace its JSON file"""
        # Revalidate because the list inside a frozen dataclass is still mutable.
        entry = replace(CorpusEntry(**asdict(entry)), format_version=FORMAT_VERSION)
        directory = self._directory(entry.scenario)
        path = directory / _signature_name(entry.signature)
        temp: Path | None = None
        try:
            if path.exists():
                try:
                    if _rank(_read(path, entry.scenario)) <= _rank(entry):
                        return False
                except (OSError, ValueError, TypeError):
                    pass  # A valid new entry can repair a corrupt old one.
            directory.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {"version": FORMAT_VERSION, **asdict(entry)}
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False
            ) as stream:
                temp = Path(stream.name)
                json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
            return True
        except OSError as error:
            _warn(f"cannot record corpus entry {path.name}", error)
            return False
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError as error:
                    _warn("cannot remove temporary corpus file", error)

    def forget(self, scenario: str, signature: str) -> bool:
        path = self._directory(scenario) / _signature_name(signature)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as error:
            _warn(f"cannot forget corpus entry {path.name}", error)
            return False

    def prune(self, scenario: str, keep: int = 50) -> int:
        if type(keep) is not int or keep < 0:
            raise ValueError("keep must be a nonnegative integer")
        return sum(self.forget(scenario, entry.signature) for entry in self.load(scenario)[keep:])
