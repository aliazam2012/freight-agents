from typing import Any

from freight_agents.agentcore.hooks import (
    ALLOW,
    Decision,
    Deny,
    HookContext,
    Rewrite,
    run_tool,
)
from freight_agents.agentcore.tools import Risk, Tool, ToolRegistry, tool
from freight_agents.llm import ToolCall
from pydantic import BaseModel

from .conftest import Counter, EchoIn, EchoOut


def _call(**args: Any) -> ToolCall:
    return ToolCall(id="t1", name="echo", args={"text": "hi", "to": None, **args})


def test_pre_hooks_run_in_order(echo: Tool, ctx: HookContext) -> None:
    seen: list[str] = []

    def first(t: Tool, a: dict[str, Any], c: HookContext) -> Decision:
        seen.append("first")
        return ALLOW

    def second(t: Tool, a: dict[str, Any], c: HookContext) -> Decision:
        seen.append("second")
        return ALLOW

    out = run_tool(_call(), ToolRegistry([echo]), [first, second], [], ctx)
    assert out.status == "ok"
    assert out.output == {"text": "hi"}
    assert seen == ["first", "second"]


def test_a_deny_stops_the_call_before_the_tool_runs(
    echo: Tool, ctx: HookContext, counter: Counter
) -> None:
    def no(t: Tool, a: dict[str, Any], c: HookContext) -> Decision:
        return Deny("policy", "not today")

    out = run_tool(_call(), ToolRegistry([echo]), [no], [], ctx)
    assert (out.status, out.code, out.reason) == ("denied", "policy", "not today")
    assert counter.calls == 0
    assert out.as_result().is_error


def test_rewrite_changes_what_the_tool_sees(echo: Tool, ctx: HookContext) -> None:
    def shout(t: Tool, a: dict[str, Any], c: HookContext) -> Decision:
        return Rewrite({**a, "text": a["text"].upper()})

    assert run_tool(_call(), ToolRegistry([echo]), [shout], [], ctx).output == {"text": "HI"}


def test_invalid_input_is_denied(echo: Tool, ctx: HookContext, counter: Counter) -> None:
    bad = ToolCall(id="t1", name="echo", args={"text": 5})
    out = run_tool(bad, ToolRegistry([echo]), [], [], ctx)
    assert (out.status, out.code) == ("denied", "invalid_input")
    assert counter.calls == 0


def test_unknown_tool_is_an_error(echo: Tool, ctx: HookContext) -> None:
    out = run_tool(ToolCall(id="t1", name="nope", args={}), ToolRegistry([echo]), [], [], ctx)
    assert (out.status, out.code) == ("error", "unknown_tool")


def test_tool_exception_is_an_error(ctx: HookContext) -> None:
    @tool(name="boom", description="Fails.", risk=Risk.READ)
    def boom(args: EchoIn) -> EchoOut:
        raise RuntimeError("carrier API down")

    out = run_tool(
        ToolCall(id="t1", name="boom", args={"text": "x", "to": None}),
        ToolRegistry([boom]),
        [],
        [],
        ctx,
    )
    assert (out.status, out.code) == ("error", "tool_failed")
    assert "carrier API down" in (out.reason or "")


def test_wrong_output_type_is_an_error(ctx: HookContext) -> None:
    class Other(BaseModel):
        n: int

    @tool(name="liar", description="Returns the wrong model.", risk=Risk.READ)
    def liar(args: EchoIn) -> EchoOut:
        return Other(n=1)  # type: ignore[return-value]

    call = ToolCall(id="t1", name="liar", args={"text": "x", "to": None})
    out = run_tool(call, ToolRegistry([liar]), [], [], ctx)
    assert (out.status, out.code) == ("error", "invalid_output")
