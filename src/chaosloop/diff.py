"""Align FIFO and failing traces to explain their first observable difference"""

import difflib
from dataclasses import dataclass

from .trace import Step, Trace


@dataclass(frozen=True, slots=True)
class DiffRow:
    kind: str  # same | changed | only_baseline | only_failing
    baseline: Step | None
    failing: Step | None
    is_fork: bool = False  # Exactly one on different traces, zero on equal ones.


def step_signature(step: Step) -> tuple[str | None, str | None, str]:
    """Ignore numbering/time. Non-task callbacks need more than (None, None)."""
    diagnostic = f"{step.kind}:{step.label}" if step.task_id is None else ""
    return step.task_id, step.location, diagnostic


def diff_traces(baseline: Trace, failing: Trace) -> list[DiffRow]:
    """Sequence alignment is an explanation aid, not proof of a bug's cause."""
    if not baseline.recording or not failing.recording:
        raise ValueError("trace diff requires full traces; replay with record_trace=True")
    matcher = difflib.SequenceMatcher(
        None,
        [step_signature(s) for s in baseline.steps],
        [step_signature(s) for s in failing.steps],
        autojunk=False,
    )
    rows: list[DiffRow] = []
    fork_marked = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for offset in range(max(i2 - i1, j2 - j1)):
            left = baseline.steps[i1 + offset] if i1 + offset < i2 else None
            right = failing.steps[j1 + offset] if j1 + offset < j2 else None
            kind = (
                "same"
                if tag == "equal"
                else (
                    "only_failing"
                    if left is None
                    else "only_baseline"
                    if right is None
                    else "changed"
                )
            )
            fork = kind != "same" and not fork_marked
            rows.append(DiffRow(kind, left, right, fork))
            fork_marked |= fork
    return rows


def _name(step: Step | None) -> str:
    return "no aligned callback" if step is None else step.task_id or step.label or step.kind


def _cell(step: Step | None) -> str:
    if step is None:
        return ""
    return f"{step.n:>4}  {_name(step)}  {step.location or '?'}"


def _gap(rows: list[DiffRow], start: int, end: int) -> str:
    changed = sum(row.kind != "same" for row in rows[start:end])
    if changed:
        return f"  ⋮  ({end - start} aligned rows omitted, including {changed} differences)"
    return f"  ⋮  ({end - start} identical steps)"


def render_diff(
    rows: list[DiffRow],
    *,
    context: int = 3,
    max_rows: int = 40,
    baseline_label: str = "baseline",
    failing_label: str = "failing schedule",
) -> str:
    """Show nearby rows and truthful omission counts, including a capped tail"""
    if type(context) is not int or context < 0 or type(max_rows) is not int or max_rows < 0:
        raise ValueError("context and max_rows must be nonnegative integers")
    changed = [i for i, row in enumerate(rows) if row.kind != "same"]
    keep: set[int] = set()
    for index in changed:
        keep.update(range(max(0, index - context), min(len(rows), index + context + 1)))
    shown = sorted(keep)[:max_rows]
    # Bound individual cells so a huge callback repr cannot explode the report.
    width = 54
    lines = [
        f"{baseline_label[:width]:<{width}} | {failing_label}",
        "─" * width + "─┼─" + "─" * width,
    ]
    previous = 0
    for index in shown:
        if index > previous:
            lines.append(_gap(rows, previous, index))
        row = rows[index]
        marker = "►" if row.is_fork else "|"
        suffix = "  ← fork" if row.is_fork else ""
        lines.append(
            f"{_cell(row.baseline)[:width]:<{width}} {marker} {_cell(row.failing)[:width]}{suffix}"
        )
        previous = index + 1
    if previous < len(rows):
        lines.append(_gap(rows, previous, len(rows)))
    fork = next((row for row in rows if row.is_fork), None)
    if fork is None:
        lines.append("No observable fork in task/site alignment.")
    else:
        step = (
            fork.failing.n if fork.failing is not None else fork.baseline.n if fork.baseline else 0
        )
        lines.append(
            f"First aligned difference near step {step}: {_name(fork.failing)} "
            f"instead of {_name(fork.baseline)}. This marks a fork, not a cause proof."
        )
    return "\n".join(lines)
