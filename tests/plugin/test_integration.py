import json
import shlex

import pytest

PASSING = """
import asyncio, pytest
@pytest.mark.chaos(trials=4)
async def test_clean():
    state = {"count": 0}
    async def bump():
        await asyncio.sleep(0)
        state["count"] += 1
    await asyncio.gather(bump(), bump())
    assert state["count"] == 2
"""

RACE = """
import asyncio, pytest
@pytest.mark.chaos(trials=20)
async def test_race():
    state = {"count": 0}
    async def bump(delayed):
        if delayed:
            await asyncio.sleep(0)
        old = state["count"]
        await asyncio.sleep(0)
        state["count"] = old + 1
    await asyncio.gather(bump(False), bump(True))
    assert state["count"] == 2
"""


def test_clean_and_unmarked_tests(pytester, run_plugin):
    pytester.makepyfile(PASSING + "\ndef test_normal(): assert True\n")
    result = run_plugin("--chaos-no-corpus")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*1 chaos tests; 4 trials;*"])


def test_failing_report_has_exact_working_reproduction(pytester, run_plugin):
    pytester.makepyfile(RACE)
    result = run_plugin("--chaos-no-corpus")
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "deviations" in output and "Reproduce this pytest case:" in output
    command = output.split("Reproduce this pytest case:\n", 1)[1].splitlines()[0].strip()
    replay = run_plugin(*shlex.split(command)[1:])
    replay.assert_outcomes(failed=1)
    replay.stdout.fnmatch_lines(["*1 chaos tests; 1 trials;*"])


@pytest.mark.parametrize(
    "options,trials",
    [
        (["--chaos-trials", "10"], 10),
        (["--chaos-seed", "847"], 1),
        (["--chaos-scheduler", "fifo"], 4),
    ],
)
def test_command_line_overrides_marker(pytester, run_plugin, options, trials):
    pytester.makepyfile(PASSING)
    result = run_plugin("--chaos-no-corpus", *options)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*1 chaos tests; {trials} trials;*"])


@pytest.mark.parametrize(
    "mark,flag,trials",
    [
        ("", [], 7),
        ("trials=3", [], 3),
        ("trials=3", ["--chaos-trials", "2"], 2),
    ],
)
def test_ini_marker_cli_precedence(pytester, run_plugin, mark, flag, trials):
    pytester.makeini("[pytest]\nchaos_trials = 7\nchaos_scheduler = fifo\n")
    pytester.makepyfile(PASSING.replace("trials=4", mark))
    result = run_plugin("--chaos-no-corpus", *flag)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*1 chaos tests; {trials} trials;*"])


def test_fifo_override_passes_race(pytester, run_plugin):
    pytester.makepyfile(RACE)
    run_plugin("--chaos-scheduler", "fifo", "--chaos-no-corpus").assert_outcomes(passed=1)


def test_alias_bare_and_called(pytester, run_plugin):
    pytester.makepyfile("""
from chaosloop import chaos_test
@chaos_test
async def test_bare(): pass
@chaos_test(trials=3)
async def test_called(): pass
""")
    result = run_plugin("--chaos-no-corpus")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*2 chaos tests; 103 trials;*"])


@pytest.mark.parametrize(
    "declaration",
    [
        "@pytest.mark.chaos(trials=0)\nasync def test_bad(): pass",
        "@pytest.mark.chaos(3)\nasync def test_bad(): pass",
        "@pytest.mark.chaos(unknown=True)\nasync def test_bad(): pass",
        "@pytest.mark.chaos(max_time=float('nan'))\nasync def test_bad(): pass",
        "@pytest.mark.chaos(corpus=1)\nasync def test_bad(): pass",
        "@pytest.mark.chaos(seed=True)\nasync def test_bad(): pass",
        "@pytest.mark.chaos(scheduler='other')\nasync def test_bad(): pass",
        "@pytest.mark.chaos\ndef test_bad(): pass",
    ],
)
def test_bad_configuration_is_usage_error(pytester, run_plugin, declaration):
    pytester.makepyfile("import pytest\n" + declaration)
    assert run_plugin().ret == pytest.ExitCode.USAGE_ERROR


@pytest.mark.parametrize(
    "options",
    [
        ["--chaos-decisions", "[true]"],
        ["--chaos-decisions", "oops"],
        ["--chaos-seed", "1", "--chaos-decisions", "[]"],
        ["--chaos-max-steps", "0"],
    ],
)
def test_invalid_cli_configuration(pytester, run_plugin, options):
    pytester.makepyfile(PASSING)
    assert run_plugin(*options).ret == pytest.ExitCode.USAGE_ERROR


@pytest.mark.parametrize("silenced", [False, True])
def test_fixture_warning_and_shared_state(pytester, run_plugin, silenced):
    pytester.makepyfile("""
import pytest
@pytest.fixture
def box(): return []
@pytest.mark.chaos(trials=2)
async def test_shared(box):
    box.append(1)
    assert len(box) == 1
""")
    options = ["-W", "ignore::chaosloop.pytest_plugin.ChaosFixtureWarning"] if silenced else []
    result = run_plugin("--chaos-no-corpus", *options)
    result.assert_outcomes(failed=1)
    assert ("created ONCE per test" in result.stdout.str()) is not silenced


def test_parametrized_cases_get_separate_corpus_keys(pytester, run_plugin):
    pytester.makepyfile("""
import pytest
@pytest.mark.parametrize("number", [1, 2], ids=["one", "two"])
@pytest.mark.chaos(trials=1)
async def test_cases(number):
    assert number == 0
""")
    run_plugin().assert_outcomes(failed=2)
    entries = [
        json.loads(path.read_text()) for path in (pytester.path / ".chaosloop").rglob("*.json")
    ]
    assert len(entries) == 2
    assert {entry["scenario"].split("[")[-1] for entry in entries} == {"one]", "two]"}


def test_corpus_repro_uses_decisions_and_single_trial(pytester, run_plugin):
    pytester.makepyfile(RACE)
    run_plugin().assert_outcomes(failed=1)
    second = run_plugin()
    second.assert_outcomes(failed=1)
    text = second.stdout.str()
    assert "--chaos-decisions" in text
    command = text.split("Reproduce this pytest case:\n", 1)[1].splitlines()[0].strip()
    replay = run_plugin(*shlex.split(command)[1:])
    replay.assert_outcomes(failed=1)
    replay.stdout.fnmatch_lines(["*1 chaos tests; 1 trials;*"])


def test_strict_replay_exhaustion_fails(pytester, run_plugin):
    pytester.makepyfile(PASSING)
    result = run_plugin("--chaos-decisions", "[]")
    result.assert_outcomes(failed=1)
    assert "ReplayMismatch" in result.stdout.str()


def test_summary_is_reset_between_sessions(pytester, run_plugin):
    pytester.makepyfile(PASSING)
    for _ in range(2):
        result = run_plugin("--chaos-no-corpus", "-v")
        result.stdout.fnmatch_lines(["*chaosloop 0.3.0:*", "*1 chaos tests; 4 trials;*"])


def test_corpus_lives_under_rootdir_even_from_child(pytester, run_plugin, monkeypatch):
    pytester.makeini("[pytest]\n")
    directory = pytester.path / "child"
    directory.mkdir()
    (directory / "test_case.py").write_text(RACE)
    monkeypatch.chdir(directory)
    run_plugin("--rootdir", str(pytester.path), str(directory)).assert_outcomes(failed=1)
    assert (pytester.path / ".chaosloop").is_dir()
    assert not (directory / ".chaosloop").exists()


@pytest.mark.parametrize("mode", ["strict", "auto"])
def test_coexists_with_pytest_asyncio(pytester, run_plugin, mode):
    pytest.importorskip("pytest_asyncio")
    pytester.makeini(
        f"[pytest]\nasyncio_mode = {mode}\nasyncio_default_fixture_loop_scope = function\n"
    )
    pytester.makepyfile(
        PASSING
        + """
@pytest.mark.asyncio
async def test_normal_asyncio():
    from chaosloop.loop import ChaosEventLoop
    assert not isinstance(asyncio.get_running_loop(), ChaosEventLoop)
    await asyncio.sleep(0)
"""
    )
    result = run_plugin("-p", "pytest_asyncio.plugin", "--chaos-no-corpus")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*1 chaos tests; 4 trials;*"])
