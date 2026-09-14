import pytest


@pytest.fixture(autouse=True)
def isolate_plugin_loading(monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


@pytest.fixture
def run_plugin(pytester):
    def run(*args):
        return pytester.runpytest("-p", "chaosloop.pytest_plugin", *args)

    return run
