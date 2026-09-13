import sys
from pathlib import Path

import pytest

from chaosloop import trial
from chaosloop.cli.specs import ScenarioLoadError, _file_name, load_scenario


def test_file_and_module_have_one_corpus_identity():
    path = load_scenario("tests/cli_scenarios.py::clean")
    module = load_scenario("tests.cli_scenarios:clean")
    assert path.key == module.key == "tests.cli_scenarios.clean"
    assert trial(path.factory).value == {"answer": 42}
    assert path.source_file == Path("tests/cli_scenarios.py").resolve()


@pytest.mark.parametrize("suffix", ["", "::", "::scenario"])
def test_default_name_dataclass_and_relative_import(tmp_path, monkeypatch, suffix):
    name = "pkg_" + tmp_path.name.replace("-", "_")
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "value.py").write_text("ANSWER = 42\n")
    path = package / "entry.py"
    path.write_text(
        "from dataclasses import dataclass\nfrom .value import ANSWER\n"
        "@dataclass\nclass Record:\n    value: int\n"
        "async def scenario():\n    return Record(ANSWER).value\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    ref = load_scenario(str(path) + suffix)
    assert trial(ref.factory).value == 42
    assert ref.key == load_scenario(f"{name}.entry:scenario").key


@pytest.mark.parametrize(
    "body",
    [
        "raise AttributeError('import failed')",
        "raise SystemExit(1)",
        "raise RuntimeError('oops')",
        "this is invalid Python !",
    ],
)
def test_failed_import_has_no_partially_registered_module(tmp_path, body):
    path = tmp_path / "broken.py"
    path.write_text(body)
    name, _ = _file_name(path.resolve())
    with pytest.raises(ScenarioLoadError, match="cannot import"):
        load_scenario(str(path))
    assert name not in sys.modules


@pytest.mark.parametrize(
    "body",
    [
        "async def scenario(x): pass",
        "async def scenario(*, required): pass",
        "scenario = 42",
    ],
)
def test_required_arguments_and_noncallable_rejected(tmp_path, body):
    path = tmp_path / "bad_signature.py"
    path.write_text(body)
    with pytest.raises(ScenarioLoadError):
        load_scenario(str(path))


@pytest.mark.parametrize(
    "spec", ["", "no_such_module_xyz:scenario", "absent.py", "tests.cli_scenarios:absent"]
)
def test_bad_spec_is_actionable(spec):
    with pytest.raises(ScenarioLoadError):
        load_scenario(spec)


def test_suggestions_exclude_imported_helpers(tmp_path):
    path = tmp_path / "suggest.py"
    path.write_text("from asyncio import sleep\nasync def zebra(): pass\nasync def alpha(): pass\n")
    with pytest.raises(ScenarioLoadError, match="available: alpha, zebra"):
        load_scenario(str(path))


def test_factory_is_not_called_during_validation(tmp_path):
    path = tmp_path / "factory.py"
    path.write_text("def scenario():\n    raise RuntimeError('called')\n")
    ref = load_scenario(str(path))
    assert str(trial(ref.factory).error) == "called"


def test_nonpackage_same_stems_have_distinct_keys(tmp_path):
    paths = [tmp_path / "one" / "entry.py", tmp_path / "two" / "entry.py"]
    for path in paths:
        path.parent.mkdir()
        path.write_text("async def scenario(): pass\n")
    assert load_scenario(str(paths[0])).key != load_scenario(str(paths[1])).key


def test_name_collision_does_not_silently_run_wrong_file(tmp_path, monkeypatch):
    path = tmp_path / "sys.py"
    path.write_text("async def scenario(): pass\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ScenarioLoadError, match="already used"):
        load_scenario("sys.py")