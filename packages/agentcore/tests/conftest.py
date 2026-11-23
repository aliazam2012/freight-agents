from datetime import UTC, datetime

import pytest
from freight_agents.agentcore.hooks import HookContext
from freight_agents.agentcore.tools import Risk, Tool, tool
from pydantic import BaseModel


class EchoIn(BaseModel):
    text: str
    to: str | None


class EchoOut(BaseModel):
    text: str


class Counter:
    def __init__(self) -> None:
        self.calls = 0


@pytest.fixture
def counter() -> Counter:
    return Counter()


@pytest.fixture
def echo(counter: Counter) -> Tool:
    @tool(name="echo", description="Echo text.", risk=Risk.READ)
    def run(args: EchoIn) -> EchoOut:
        counter.calls += 1
        return EchoOut(text=args.text)

    return run


@pytest.fixture
def send(counter: Counter) -> Tool:
    @tool(name="send", description="Send text.", risk=Risk.SEND)
    def run(args: EchoIn) -> EchoOut:
        counter.calls += 1
        return EchoOut(text=f"sent to {args.to}")

    return run


@pytest.fixture
def ctx() -> HookContext:
    return HookContext(
        run_id="r1",
        agent="test",
        case_id="c1",
        state="open",
        now=datetime(2026, 11, 22, tzinfo=UTC),
    )
