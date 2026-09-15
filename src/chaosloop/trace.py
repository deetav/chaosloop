"""Record scheduling decisions, compare their structure, and explain a run."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Protocol, cast, runtime_checkable


@dataclass(frozen=True, slots=True)
class Step:
    """One callback execution; ``chosen`` is a candidate tuple position"""
    n: int
    vtime: float
    chosen: int
    n_candidates: int
    task_id: str | None
    kind: str
    label: str
    location: str | None


@runtime_checkable
class Tracer(Protocol):
    """The recording operation a loop requires from a trace sink."""

    def record(self, step: Step) -> None:
        """Record one scheduling decision and its selected callback."""
        ...


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _parse_step(row: dict[str, object]) -> Step:
    """Validate persisted data before letting it become a typed Step."""
    expected = {
        "type",
        "n",
        "vtime",
        "chosen",
        "n_candidates",
        "task_id",
        "kind",
        "label",
        "location",
    }
    if row.keys() != expected:
        raise ValueError("a step row has missing or unknown fields")
    n = _integer(row["n"], "n")
    chosen = _integer(row["chosen"], "chosen")
    count = _integer(row["n_candidates"], "n_candidates")
    if n < 0 or count < 1 or not 0 <= chosen < count:
        raise ValueError("invalid step number, candidate count, or chosen position")
    timestamp = row["vtime"]
    if type(timestamp) not in (int, float):
        raise ValueError("vtime must be a finite nonnegative number")
    try:
        vtime = float(cast("int | float", timestamp))
    except OverflowError as error:
        raise ValueError("vtime must be finite") from error
    if not math.isfinite(vtime) or vtime < 0:
        raise ValueError("vtime must be a finite nonnegative number")
    return Step(
        n=n,
        vtime=vtime,
        chosen=chosen,
        n_candidates=count,
        task_id=_optional_string(row["task_id"], "task_id"),
        kind=_string(row["kind"], "kind"),
        label=_string(row["label"], "label"),
        location=_optional_string(row["location"], "location"),
    )


@dataclass
class Trace:
    """A mutable recorder containing immutable Step values"""

    steps: list[Step] = field(default_factory=list)
    seed: int | None = None
    scheduler: str = ""

    def record(self, step: Step) -> None:
        """Append the immutable description of a selected callback."""
        self.steps.append(step)

    def snapshot(self) -> tuple[Step, ...]:
        """Detach the current sequence from future appends to this recorder."""
        return tuple(self.steps)

    @property
    def decisions(self) -> list[int]:
        """Return the schedule in the scheduler-independent replay format."""
        return [step.chosen for step in self.steps]

    @property
    def task_ids(self) -> list[str | None]:
        """Return the task identity recorded at each step, parallel to decisions."""
        return [step.task_id for step in self.steps]

    def digest(self) -> str:
        """Return a stable 16-character structural fingerprint of the schedule."""
        canonical = json.dumps(
            [
                [
                    step.n,
                    step.task_id,
                    step.chosen,
                    round(float(step.vtime), 9) or 0.0,
                    step.kind,
                    step.n_candidates,
                ]
                for step in self.steps
            ],
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        """Serialize a versioned metadata row followed by one row per step.

        Newline-delimited JSON keeps traces streamable and preserves seed and
        scheduler metadata, including for an empty trace.
        """
        rows: list[dict[str, object]] = [
            {"type": "metadata", "version": 1, "seed": self.seed, "scheduler": self.scheduler}
        ]
        rows.extend({"type": "step", **asdict(step)} for step in self.steps)
        return "".join(
            json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in rows
        )

    @classmethod
    def from_jsonl(cls, text: str) -> "Trace":
        """Load our JSONL format, rejecting malformed and unsupported records"""
        trace = cls()
        metadata_seen = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw: object = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("each row must be a JSON object")
                row = cast("dict[str, object]", raw)
                if not metadata_seen:
                    if row.keys() != {"type", "version", "seed", "scheduler"}:
                        raise ValueError("first row must contain complete trace metadata")
                    if row["type"] != "metadata" or _integer(row["version"], "version") != 1:
                        raise ValueError("unsupported trace format or version")
                    trace.seed = None if row["seed"] is None else _integer(row["seed"], "seed")
                    trace.scheduler = _string(row["scheduler"], "scheduler")
                    metadata_seen = True
                elif row.get("type") == "step":
                    trace.record(_parse_step(row))
                else:
                    raise ValueError("expected a step row after metadata")
            except ValueError as error:
                raise ValueError(f"invalid trace at line {line_number}: {error}") from error
        return trace

    def render(self, limit: int | None = None) -> str:
        """Render choices with a marker beside every deviation from FIFO"""
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("limit must be a nonnegative integer or None")
        shown = self.steps if limit is None else self.steps[:limit]
        lines = [f"{'step':>5}  {'vtime':>9}  {'task':<12}  {'action':<40}  at"]
        for step in shown:
            marker = "" if step.chosen == 0 else f"  ← chose #{step.chosen} of {step.n_candidates}"
            action = f"{step.label or step.kind}{marker}"
            lines.append(
                f"{step.n:>5}  {step.vtime:>9.3f}  {step.task_id or '-':<12}  "
                f"{action:<40}  {step.location or ''}"
            )
        omitted = len(self.steps) - len(shown)
        if omitted:
            lines.append(f"... {omitted} more steps")
        deviations = sum(step.chosen != 0 for step in self.steps)
        word = "deviation" if deviations == 1 else "deviations"
        lines.append(f"{deviations} {word} from default in {len(self.steps)} steps")
        return "\n".join(lines)
