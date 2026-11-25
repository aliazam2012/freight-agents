"""A stub of the Slack Web API, served over HTTP so slack_sdk talks to it as to Slack."""

import itertools
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request


class SlackStub:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.channels: dict[str, str] = {}
        self.calls: list[str] = []
        clock = itertools.count(1)

        async def form(request: Request) -> dict[str, Any]:
            if request.headers.get("content-type", "").startswith("application/json"):
                return dict(json.loads(await request.body() or b"{}"))
            return dict((await request.form()).items())

        @self.app.post("/api/{method}")
        async def call(method: str, request: Request) -> dict[str, Any]:
            body = await form(request)
            self.calls.append(method)
            if method == "auth.test":
                return {"ok": True, "user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"}
            if method == "chat.postMessage":
                ts = f"{next(clock)}.000100"
                message = {
                    "ts": ts,
                    "user": "UBOT",
                    "text": body["text"],
                    "thread_ts": body.get("thread_ts"),
                }
                self.messages.setdefault(str(body["channel"]), []).append(message)
                return {"ok": True, "channel": body["channel"], "ts": ts}
            if method == "conversations.history":
                return {
                    "ok": True,
                    "messages": list(reversed(self.messages.get(str(body["channel"]), []))),
                }
            if method == "conversations.create":
                channel_id = f"C{len(self.channels) + 100}"
                self.channels[channel_id] = str(body["name"])
                return {"ok": True, "channel": {"id": channel_id, "name": body["name"]}}
            return {"ok": False, "error": "unknown_method"}


@pytest.fixture
def slack() -> Iterator[tuple[SlackStub, str]]:
    stub = SlackStub()
    server = uvicorn.Server(uvicorn.Config(stub.app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the Slack stub did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield stub, f"http://127.0.0.1:{port}/api/"
    server.should_exit = True
    thread.join(timeout=5)
