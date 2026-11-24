from pathlib import Path

import pytest
from freight_agents.volume_forecast.runs import Run, RunStore, build_run


@pytest.fixture(scope="session")
def default_store(tmp_path_factory: pytest.TempPathFactory) -> RunStore:
    """The default eight-origin run, built once per test session."""
    store = RunStore(Path(tmp_path_factory.mktemp("runs")))
    store.save(build_run(day="2026-11-23"))
    return store


@pytest.fixture(scope="session")
def default_run(default_store: RunStore) -> Run:
    return default_store.load("latest")
