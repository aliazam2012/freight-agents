import datetime as dt
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI
from freight_agents.mock_carrier.app import create_app


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 12, 1, 15, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


class Served:
    def __init__(self, app: FastAPI, url: str) -> None:
        self.app, self.url = app, url


def serve(app: FastAPI) -> Iterator[Served]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the mock carrier did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield Served(app, f"http://127.0.0.1:{port}")
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def portal(clock: Clock) -> Iterator[Served]:
    yield from serve(create_app(scac="EXME", clock=clock))


@pytest.fixture
def redesigned_portal(clock: Clock) -> Iterator[Served]:
    yield from serve(create_app(scac="EXME", clock=clock, portal_without=("amount_usd",)))
