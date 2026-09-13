"""Versioned, defensive persistence for known failing schedules"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(".chaosloop")
FORMAT_VERSION = 1


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

        object.__setattr__(self, "decisions", list(self.decisions))


def _safe_dirname(scenario: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", scenario)[:80].strip(".") or "scenario"
    return f"{slug}-{hashlib.sha256(scenario.encode()).hexdigest()[:12]}"


def _signature_name(signature: str) -> str:
    return hashlib.sha256(signature.encode()).hexdigest()[:32] + ".json"


def _rank(entry: CorpusEntry) -> tuple[int, int, int, tuple[int, ...]]:
    return (
        entry.deviations,
        entry.seed if entry.seed is not None else 2**63,
        len(entry.decisions),
        tuple(entry.decisions),
    )


def _read(path: Path, scenario: str) -> CorpusEntry:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.pop("version", None) != FORMAT_VERSION:
        raise ValueError("unsupported corpus format version")
    entry = CorpusEntry(**data)
    if entry.scenario != scenario or path.name != _signature_name(entry.signature):
        raise ValueError("entry identity does not match its directory/filename")
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
        entry = CorpusEntry(**asdict(entry))
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
