from dataclasses import replace

from freight_agents.agentcore.guards import budget_guard, cap_size, state_allowlist
from freight_agents.agentcore.hooks import HookContext, run_tool
from freight_agents.agentcore.tools import Tool, ToolRegistry
from freight_agents.llm import ToolCall


def _call(text: str = "hi") -> ToolCall:
    return ToolCall(id="t1", name="echo", args={"text": text, "to": None})


def test_tool_allowed_in_its_state(echo: Tool, ctx: HookContext) -> None:
    guard = state_allowlist({"echo": {"open"}})
    assert run_tool(_call(), ToolRegistry([echo]), [guard], [], ctx).status == "ok"


def test_tool_denied_outside_its_states(echo: Tool, ctx: HookContext) -> None:
    guard = state_allowlist({"echo": {"closed"}})
    out = run_tool(_call(), ToolRegistry([echo]), [guard], [], ctx)
    assert (out.status, out.code) == ("denied", "state")
    assert "open" in (out.reason or "")


def test_tool_without_a_policy_is_denied(echo: Tool, ctx: HookContext) -> None:
    out = run_tool(_call(), ToolRegistry([echo]), [state_allowlist({})], [], ctx)
    assert (out.status, out.code) == ("denied", "state")


def test_exhausted_budget_is_denied(echo: Tool, ctx: HookContext) -> None:
    spent = replace(ctx, tool_calls_left=0)
    out = run_tool(_call(), ToolRegistry([echo]), [budget_guard], [], spent)
    assert (out.status, out.code) == ("denied", "budget")
    assert run_tool(_call(), ToolRegistry([echo]), [budget_guard], [], ctx).status == "ok"


def test_cap_size_truncates_and_says_so(echo: Tool, ctx: HookContext) -> None:
    out = run_tool(_call("x" * 50), ToolRegistry([echo]), [], [cap_size(10)], ctx)
    assert out.output is not None
    text = out.output["text"]
    assert text.startswith("x" * 10)
    assert "truncated 40 characters" in text
