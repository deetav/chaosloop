"""Turning a command line string into a scenario factory"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from ..runner import Scenario


class ScenarioLoadError(Exception):
    """The spec couldn't be resolved. Exit code 3"""


@dataclass(frozen=True, slots=True)
class ScenarioRef:
    spec: str
    factory: Scenario
    key: str
    source_file: Path | None


@contextmanager
def import_root(root: Path) -> Iterator[None]:
    """Make a local project importable for this operation, then restore sys.path."""
    previous = sys.path[:]
    sys.path.insert(0, str(root))
    try:
        yield
    finally:
        sys.path[:] = previous


def _file_name(path: Path) -> tuple[str, Path]:
    names = [path.stem]
    parent = path.parent
    while (parent / "__init__.py").is_file():
        names.insert(0, parent.name)
        parent = parent.parent
    if len(names) > 1 and all(name.isidentifier() for name in names):
        if names[-1] == "__init__":
            names.pop()
        return ".".join(names), parent
    for root in [Path.cwd(), *(Path(p or ".") for p in sys.path)]:
        try:
            parts = path.relative_to(root.resolve()).with_suffix("").parts
        except ValueError:
            continue
        if parts and all(part.isidentifier() for part in parts):
            return ".".join(parts), root.resolve()
    identity = hashlib.sha256(str(path).encode()).hexdigest()[:20]
    return f"_chaosloop_file_{identity}", path.parent


def _load_file(path: Path) -> ModuleType:
    path = path.resolve()
    if not path.is_file():
        raise ScenarioLoadError(f"scenario file does not exist: {path}")
    name, root = _file_name(path)
    cached = sys.modules.get(name)
    if cached is not None:
        origin = getattr(cached, "__file__", None)
        if origin and Path(origin).resolve() == path:
            return cached
        raise ScenarioLoadError(f"module name {name!r} is already used by another file")
    with import_root(root):
        parent = name.rpartition(".")[0]
        if parent:
            importlib.import_module(parent)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ScenarioLoadError(f"cannot import Python source: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


def load_scenario(spec: str) -> ScenarioRef:
    """Accept file.py::factory, package.module:factory, or file.py (scenario)"""
    spec = spec.strip()
    if not spec:
        raise ScenarioLoadError("provide file.py::scenario or package.module:scenario")
    if "::" in spec:
        target, attr = spec.split("::", 1)
        file_mode = True
    elif spec.endswith(".py") or "/" in spec or "\\" in spec:
        target, attr, file_mode = spec, "scenario", True
    else:
        target, separator, attr = spec.partition(":")
        attr, file_mode = attr if separator else "scenario", False
    attr = attr or "scenario"
    try:
        with import_root(Path.cwd()):
            module = _load_file(Path(target)) if file_mode else importlib.import_module(target)
    except ScenarioLoadError:
        raise
    except (Exception, SystemExit) as error:
        raise ScenarioLoadError(
            f"cannot import {target!r}: {type(error).__name__}: {error}. "
            "Check the file path, imports, and module-level code."
        ) from error
    try:
        value: Any = module
        for part in attr.split("."):
            value = getattr(value, part)
        if not callable(value):
            raise ScenarioLoadError(f"{attr!r} in {target!r} is not callable")
        inspect.signature(value).bind()
    except ScenarioLoadError:
        raise
    except AttributeError as error:
        choices = sorted(
            name
            for name, value in vars(module).items()
            if callable(value) and getattr(value, "__module__", None) == module.__name__
        )[:8]
        hint = ", ".join(choices) or "define async def scenario() in the module"
        raise ScenarioLoadError(f"cannot find {attr!r} in {target!r}; available: {hint}") from error
    except (Exception, SystemExit) as error:
        raise ScenarioLoadError(
            f"cannot load {spec!r}: {type(error).__name__}: {error}. "
            "Use an importable module and a callable with no required arguments."
        ) from error

    def factory() -> Any:
        return value()

    factory.__module__ = module.__name__
    factory.__qualname__ = attr
    source = getattr(module, "__file__", None)
    return ScenarioRef(
        spec,
        cast(Scenario, factory),
        f"{module.__name__}.{attr}",
        Path(source).resolve() if source else None,
    )
