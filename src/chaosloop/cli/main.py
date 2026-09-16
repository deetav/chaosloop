"""chaosloop command line"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from contextlib import nullcontext, redirect_stdout
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from .. import __version__
from ..corpus import DEFAULT_DIR, Corpus, CorpusEntry
from ..exceptions import ReplayMismatch
from ..fuzz import default_progress, fuzz
from ..oracles import Oracle, Severity, TaskLeak
from ..runner import DEFAULT_ORACLES, _InvalidScenarioError, trial
from ..schedulers import Fifo, Random, Replay
from ..shrink import ShrinkBudget, ShrinkError, shrink
from ..shrink import failure_findings as _failure_findings
from ..trace import Trace
from .doctor import diagnose_environment, diagnose_scenario
from .render import emit_json, fuzz_data, render_divergences, shrink_data, trial_data
from .replay import SavedSchedule, read_schedule
from .seeds import parse_seeds
from .specs import ScenarioLoadError, load_scenario


class UsageError(Exception):
    """Argument problems are distinct from scenario import/runtime problems."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise UsageError(message)


def _positive(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _nonnegative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return value


def _seconds(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return value


def _bounds(parser: argparse.ArgumentParser, *, replay: bool = False) -> None:
    parser.add_argument("--max-steps", type=_positive, default=None if replay else 1_000_000)
    parser.add_argument("--max-time", type=_seconds, help="virtual seconds per trial")
    parser.add_argument(
        "--fail-on-task-leak",
        action="store_true",
        help="promote the default task-leak warning to failure",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="chaosloop", description="Explore deterministic asyncio schedules.")
    parser.add_argument("--version", action="version", version=f"chaosloop {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands = {
        name: sub.add_parser(name, help=help_text)
        for name, help_text in (
            ("run", "execute one schedule"),
            ("fuzz", "search a bounded set of seeds"),
            ("replay", "retry a saved schedule"),
            ("shrink", "minimize one known failure"),
            ("trace", "read a saved trace"),
            ("doctor", "diagnose reproducibility"),
        )
    }
    for name, command in commands.items():
        command.add_argument("--json", action="store_true", help="complete schema-1 JSON output")
        command.add_argument(
            "--no-color", action="store_true", help="plain output (also the default)"
        )
        if name != "trace":
            command.add_argument(
                "spec",
                nargs="?" if name == "doctor" else None,
                help="file.py::scenario or package.module:scenario",
            )
    run = commands["run"]
    _bounds(run)
    run.add_argument("--seed", type=int)
    run.add_argument("--scheduler", choices=("fifo", "random"))
    run.add_argument("--trace", action="store_true", help="show the trace on a passing run too")
    run.add_argument("--trace-limit", type=_nonnegative, default=40)
    run.add_argument("--save-trace", type=Path, help="write complete Trace JSONL to this file")
    search = commands["fuzz"]
    _bounds(search)
    search.add_argument("--trials", type=_nonnegative, default=1000)
    search.add_argument("--seeds", type=parse_seeds)
    search.add_argument("--scheduler", choices=("fifo", "random"), default="random")
    search.add_argument("--time-budget", type=_seconds, help="wall seconds checked BETWEEN trials")
    search.add_argument(
        "--quiet", action="store_true", help="suppress progress; retain final report"
    )
    stop = search.add_mutually_exclusive_group()
    stop.add_argument("--fail-fast", dest="fail_fast", action="store_true", default=True)
    stop.add_argument("--all", dest="fail_fast", action="store_false")
    corpus = search.add_mutually_exclusive_group()
    corpus.add_argument("--corpus", type=Path, default=DEFAULT_DIR)
    corpus.add_argument("--no-corpus", action="store_true")
    search.add_argument(
        "--shrink",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="default: on for fail-fast, off for --all",
    )
    for command in (search, commands["shrink"]):
        command.add_argument("--shrink-budget", type=_nonnegative, default=5000)
        command.add_argument("--shrink-seconds", type=_seconds, default=60.0)
    minimize = commands["shrink"]
    _bounds(minimize, replay=True)
    origin = minimize.add_mutually_exclusive_group(required=True)
    origin.add_argument("--seed", type=int)
    origin.add_argument("--corpus-entry")
    origin.add_argument("--decisions", type=Path)
    minimize.add_argument("--corpus", type=Path, default=DEFAULT_DIR)
    minimize.add_argument("--no-corpus", action="store_true", help="do not persist the result")
    replay = commands["replay"]
    _bounds(replay, replay=True)
    source = replay.add_mutually_exclusive_group(required=True)
    source.add_argument("--seed", type=int)
    source.add_argument("--decisions", type=Path)
    source.add_argument("--corpus-entry", help="unique prefix of a corpus filename's hash")
    source.add_argument("--corpus-all", action="store_true")
    replay.add_argument("--corpus", type=Path, default=DEFAULT_DIR)
    replay.add_argument(
        "--strict", action="store_true", help="stop before a hard replay divergence"
    )
    replay.add_argument(
        "--forget", action="store_true", help="delete selected entries ONLY on clean replay"
    )
    trace = commands["trace"]
    trace.add_argument("file", type=Path)
    trace.add_argument("--format", choices=("table", "jsonl"), default="table")
    trace.add_argument("--limit", type=_nonnegative)
    trace.add_argument(
        "--deviations-only", action="store_true", help="show only choices other than #0"
    )
    doctor = commands["doctor"]
    doctor.add_argument("--max-steps", type=_positive, default=50_000)
    doctor.add_argument("--max-time", type=_seconds, default=60.0)
    return parser


def _checks(promote_leaks: bool) -> list[Oracle] | None:
    if not promote_leaks:
        return None
    # Retain the other detectors; do not accidentally disable deadlock checking.
    from ..oracles import InvariantOracle

    return [
        *(make() for make in DEFAULT_ORACLES if make is not TaskLeak),
        TaskLeak(Severity.FAILURE),
        InvariantOracle(),
    ]


def _run(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    if args.scheduler == "fifo" and args.seed is not None:
        raise UsageError("--seed selects random scheduling; omit it with --scheduler fifo")
    ref = load_scenario(args.spec)
    scheduler = (
        Random(args.seed if args.seed is not None else 0)
        if (args.seed is not None or args.scheduler == "random")
        else Fifo()
    )
    result = trial(
        ref.factory,
        scheduler=scheduler,
        max_steps=args.max_steps,
        max_time=args.max_time,
        oracles=_checks(args.fail_on_task_leak),
    )
    if args.save_trace:
        try:
            args.save_trace.write_text(result.trace.to_jsonl(), encoding="utf-8")
        except OSError as error:
            raise ScenarioLoadError(f"cannot save trace: {error}") from error
    human = result.report(trace_limit=args.trace_limit, show_trace=args.trace or not result.ok)
    if result.ok and not result.findings:
        human = "No findings in this schedule.\n" + human
    return (
        int(not result.ok),
        {
            "scenario": ref.key,
            "result": trial_data(result),
            "config": {"fail_on_task_leak": args.fail_on_task_leak},
        },
        human,
    )


def _fuzz(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    ref = load_scenario(args.spec)
    result = fuzz(
        ref.factory,
        trials=args.trials,
        seeds=args.seeds,
        scheduler_factory=Random if args.scheduler == "random" else lambda seed: Fifo(),
        max_steps=args.max_steps,
        max_time=args.max_time,
        oracles=_checks(args.fail_on_task_leak),
        fail_fast=args.fail_fast,
        time_budget=args.time_budget,
        corpus=None if args.no_corpus else args.corpus,
        on_progress=None if args.quiet or args.json else default_progress,
        shrink=args.fail_fast if args.shrink is None else args.shrink,
        shrink_budget=ShrinkBudget(args.shrink_budget, args.shrink_seconds),
    )
    return (
        5 if result.corpus_diverged else int(not result.ok),
        fuzz_data(result),
        result.report(include_timing=True, show_warnings=True),
    )


def _replay(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    from_corpus = args.corpus_entry is not None or args.corpus_all
    if args.forget and not from_corpus:
        raise UsageError("--forget requires --corpus-entry or --corpus-all")
    if args.strict and args.seed is not None:
        raise UsageError("--strict validates recorded decisions; it does not apply to --seed")
    ref = load_scenario(args.spec)
    store = Corpus(args.corpus)
    entries = store.load(ref.key) if from_corpus else []
    if args.corpus_entry is not None:
        entries = [
            entry
            for entry in entries
            if hashlib.sha256(entry.signature.encode()).hexdigest().startswith(args.corpus_entry)
        ]
        if len(entries) != 1:
            raise ScenarioLoadError(
                f"corpus prefix must match exactly one entry; found {len(entries)} for {ref.key}"
            )
    if from_corpus and not entries:
        raise ScenarioLoadError(f"no stored entries for {ref.key}")
    schedules: list[tuple[SavedSchedule, CorpusEntry | None]] = [
        (SavedSchedule.from_entry(entry), entry) for entry in entries
    ]
    if args.decisions:
        schedules = [(read_schedule(args.decisions), None)]
    if args.seed is not None:
        schedules = [(SavedSchedule([]), None)]
    rows = []
    output = []
    exit_code = 0
    for saved, entry in schedules:
        if saved.scenario is not None and saved.scenario != ref.key:
            raise ScenarioLoadError(f"schedule belongs to {saved.scenario}, not {ref.key}")
        promote = args.fail_on_task_leak or saved.fail_on_task_leak
        result = trial(
            ref.factory,
            scheduler=Random(args.seed)
            if args.seed is not None
            else Replay(saved.decisions, task_ids=saved.task_ids, strict=args.strict),
            max_steps=args.max_steps
            if args.max_steps is not None
            else saved.max_steps or 1_000_000,
            max_time=args.max_time if args.max_time is not None else saved.max_time,
            oracles=_checks(promote),
        )
        mismatch = (
            result.diverged
            or isinstance(result.error, ReplayMismatch)
            or bool(result.unused_decisions)
        )
        signatures = {finding.signature for finding in _failure_findings(result)}
        if mismatch:
            status, code = "DIVERGED: recorded schedule could not be followed completely", 5
        elif result.ok:
            status, code = "NO LONGER REPRODUCES in this schedule (not proof of a fix)", 0
        elif entry is not None and entry.signature not in signatures:
            status, code = "CHANGED FAILURE: original entry retained", 1
        else:
            status, code = "STILL FAILS", 1
        forgotten = False
        if args.forget and entry is not None and result.ok and not mismatch:
            forgotten = store.forget(ref.key, entry.signature)
        exit_code = max(exit_code, code)
        rows.append(
            {
                "status": status,
                "forgotten": forgotten,
                "result": trial_data(result),
                "config": {"fail_on_task_leak": promote},
            }
        )
        output.append(
            f"{status}\n{render_divergences(result)}\n{result.report(trace_limit=40)}"
            + ("\nCorpus entry forgotten." if forgotten else "")
        )
    data: dict[str, Any] = {"scenario": ref.key, "replays": rows}
    # A single replay can itself be saved and fed back to --decisions.
    if len(rows) == 1:
        data.update(rows[0])
    return exit_code, data, "\n\n".join(output)


def _shrink(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    ref = load_scenario(args.spec)
    store = Corpus(args.corpus)
    entry = None
    saved = SavedSchedule([])
    if args.corpus_entry is not None:
        entries = [
            e
            for e in store.load(ref.key)
            if hashlib.sha256(e.signature.encode()).hexdigest().startswith(args.corpus_entry)
        ]
        if len(entries) != 1:
            raise ScenarioLoadError(
                f"corpus prefix must match exactly one entry; found {len(entries)}"
            )
        entry = entries[0]
        saved = SavedSchedule.from_entry(entry)
    elif args.decisions:
        saved = read_schedule(args.decisions)
    if saved.scenario is not None and saved.scenario != ref.key:
        raise ScenarioLoadError(f"schedule belongs to {saved.scenario}, not {ref.key}")
    promote = args.fail_on_task_leak or saved.fail_on_task_leak
    checks = _checks(promote)
    original = trial(
        ref.factory,
        scheduler=Random(args.seed)
        if args.seed is not None
        else Replay(saved.decisions, task_ids=saved.task_ids, strict=True),
        max_steps=args.max_steps if args.max_steps is not None else saved.max_steps or 1_000_000,
        max_time=args.max_time if args.max_time is not None else saved.max_time,
        oracles=checks,
    )
    if original.diverged or original.unused_decisions:
        return (
            5,
            {"scenario": ref.key, "result": trial_data(original)},
            "DIVERGED\n" + render_divergences(original),
        )
    if original.ok:
        return (
            0,
            {"scenario": ref.key, "result": trial_data(original)},
            "No failure in this schedule; nothing to shrink.",
        )
    target = (
        None
        if entry is None
        else next((f for f in _failure_findings(original) if f.signature == entry.signature), None)
    )
    if entry is not None and target is None:
        raise ShrinkError("recorded target is masked by a changed failure; re-fuzz current code")
    result = shrink(
        ref.factory,
        original,
        finding=target,
        oracles=checks,
        budget=ShrinkBudget(args.shrink_budget, args.shrink_seconds),
    )
    human = result.report(include_timing=True)
    recorded = False
    if not args.no_corpus and result.verified:
        recorded = store.record(
            CorpusEntry(
                ref.key,
                result.finding.signature,
                None,
                result.minimal,
                result.finding.message,
                result.finding.site,
                result.minimal_deviations,
                datetime.now(UTC).isoformat(),
                task_ids=result.minimal_task_ids,
                original_deviations=result.original_deviations,
                max_steps=original.max_steps,
                max_time=original.max_time,
                fail_on_task_leak=promote,
            )
        )
        if recorded:
            import shlex

            prefix = hashlib.sha256(result.finding.signature.encode()).hexdigest()[:12]
            command = shlex.join(
                [
                    "chaosloop",
                    "replay",
                    args.spec,
                    "--corpus",
                    str(args.corpus),
                    "--corpus-entry",
                    prefix,
                    "--strict",
                ]
            )
            human += f"\nSaved corpus replay: {command}"
    data = trial_data(result.final_trial) | {
        "decisions": result.minimal,
        "task_ids": result.minimal_task_ids,
    }
    return (
        1,
        {
            "scenario": ref.key,
            "result": data,
            "shrink": shrink_data(result),
            "recorded": recorded,
            "config": {"fail_on_task_leak": promote},
        },
        human,
    )


def _trace(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    try:
        original = Trace.from_jsonl(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScenarioLoadError(f"cannot read trace {args.file}: {error}") from error
    selected = [step for step in original.steps if not args.deviations_only or step.chosen != 0]
    # --limit is a human table limit. Machine views retain all selected steps.
    view = Trace(selected, seed=original.seed, scheduler=original.scheduler)
    human = view.to_jsonl().rstrip() if args.format == "jsonl" else view.render(limit=args.limit)
    return (
        0,
        {
            "seed": view.seed,
            "scheduler": view.scheduler,
            "trace": [asdict(step) for step in selected],
            "decisions": view.decisions,
        },
        human,
    )

def _doctor(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    checks = diagnose_environment()
    if args.spec:
        checks += diagnose_scenario(
            load_scenario(args.spec), max_steps=args.max_steps, max_time=args.max_time
        )
    code = int(any(not check.ok and not check.warning for check in checks))
    lines = ["chaosloop doctor"]
    for check in checks:
        symbol = "!" if check.warning else "PASS" if check.ok else "FAIL"
        lines.append(f"  {symbol} {check.check}: {check.message}")
        if check.fix:
            lines.append(f"    -> {check.fix}")
    lines.append("Selected checks only: a clean diagnosis is not a determinism proof.")
    return code, {"checks": [asdict(check) for check in checks]}, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Return 0 clean, 1 findings, 2 usage, 3 load/replay I/O, 4 internal, 130 interrupt.

    Only the entry point turns this integer into a process exit. Redirect user
    prints during machine-mode execution so stdout remains one JSON document.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    machine = "--json" in raw
    command = next(
        (arg for arg in raw if arg in {"run", "fuzz", "replay", "shrink", "trace", "doctor"}), "cli"
    )
    try:
        try:
            args = build_parser().parse_args(raw)
        except SystemExit as error:
            return int(error.code or 0)  # Only argparse help/version may exit directly.
        with redirect_stdout(sys.stderr) if machine else nullcontext():
            code, data, human = {
                "run": _run,
                "fuzz": _fuzz,
                "replay": _replay,
                "shrink": _shrink,
                "trace": _trace,
                "doctor": _doctor,
            }[args.command](args)
        if machine:
            emit_json(command, exit_code=code, **data)
        else:
            print(human)
        return code
    except SystemExit as error:
        code, message = 3, f"scenario requested process exit: {error}"
    except KeyboardInterrupt:
        code, message = 130, "interrupted"
    except ShrinkError as error:
        code, message = 5, str(error)
    except UsageError as error:
        code, message = 2, str(error)
    except (ScenarioLoadError, _InvalidScenarioError) as error:
        code, message = 3, str(error)
    except Exception as error:
        code, message = 4, f"internal error: {type(error).__name__}: {error}"
    if machine:
        emit_json(command, exit_code=code, error={"message": message})
    else:
        print(f"chaosloop: {message}", file=sys.stderr)
    return code
