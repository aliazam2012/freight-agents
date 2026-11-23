from typing import Any

from freight_agents.agentcore.agent import Agent, Budget
from freight_agents.agentcore.hooks import HookContext
from freight_agents.agentcore.tools import Tool, ToolRegistry
from freight_agents.llm import ModelTurn, ScriptedModel, TextPart, ToolCall, ToolResult, Usage

from .conftest import Counter


def _call(i: int, name: str = "echo", **args: Any) -> ToolCall:
    return ToolCall(id=f"c{i}", name=name, args=args or {"text": f"t{i}", "to": None})


def _turn(*calls: ToolCall, text: str = "", model: str = "scripted", **kw: Any) -> ModelTurn:
    return ModelTurn(
        text=text,
        tool_calls=list(calls),
        stop=kw.pop("stop", "tool_use" if calls else "end"),
        usage=kw.pop("usage", Usage(input_tokens=10, output_tokens=5)),
        model=model,
        native=kw.pop("native", None),
    )


def _agent(model: ScriptedModel, echo: Tool, **kw: Any) -> Agent:
    return Agent("test", model, ToolRegistry([echo]), system="Be brief.", **kw)


def test_a_tool_turn_then_an_answer(echo: Tool, ctx: HookContext, counter: Counter) -> None:
    model = ScriptedModel([_turn(_call(1)), _turn(text="done")])
    result = _agent(model, echo).run([TextPart(text="go")], ctx)
    assert (result.stopped, result.text, result.turns) == ("done", "done", 2)
    assert counter.calls == 1
    assert result.usage == Usage(input_tokens=20, output_tokens=10)


def test_all_results_of_one_turn_go_back_in_one_message(echo: Tool, ctx: HookContext) -> None:
    model = ScriptedModel([_turn(_call(1), _call(2)), _turn(text="ok")])
    _agent(model, echo).run([TextPart(text="go")], ctx)
    last = model.calls[1].messages[-1]
    assert last.role == "user"
    assert [p.call_id for p in last.parts if isinstance(p, ToolResult)] == ["c1", "c2"]


def test_bad_calls_become_error_results_and_the_loop_continues(
    echo: Tool, ctx: HookContext
) -> None:
    model = ScriptedModel([_turn(_call(1, name="nope"), _call(2, text=5)), _turn(text="recovered")])
    result = _agent(model, echo).run([TextPart(text="go")], ctx)
    assert result.stopped == "done"
    assert result.errors == 2
    results = [p for p in model.calls[1].messages[-1].parts if isinstance(p, ToolResult)]
    assert all(r.is_error for r in results)


def test_max_turns_stops_the_run(echo: Tool, ctx: HookContext) -> None:
    model = ScriptedModel([_turn(_call(i)) for i in range(5)])
    result = _agent(model, echo, budget=Budget(max_turns=2)).run([TextPart(text="go")], ctx)
    assert (result.stopped, result.turns) == ("max_turns", 2)


def test_tool_call_budget_stops_the_run(echo: Tool, ctx: HookContext, counter: Counter) -> None:
    model = ScriptedModel([_turn(_call(1), _call(2), _call(3)), _turn(text="x")])
    result = _agent(model, echo, budget=Budget(max_tool_calls=2)).run([TextPart(text="go")], ctx)
    assert result.stopped == "budget"
    assert counter.calls == 2
    assert [o.code for o in result.outcomes] == [None, None, "budget"]


def test_cost_budget_stops_the_run(echo: Tool, ctx: HookContext) -> None:
    pricey = Usage(input_tokens=200_000)
    model = ScriptedModel(
        [_turn(_call(i), model="claude-opus-5-5", usage=pricey) for i in range(3)]
    )
    result = _agent(model, echo, budget=Budget(max_cost_usd=1.0)).run([TextPart(text="go")], ctx)
    assert result.stopped == "budget"
    assert result.cost_usd is not None
    assert result.cost_usd >= 1.0


def test_a_refusal_stops_the_run(echo: Tool, ctx: HookContext) -> None:
    model = ScriptedModel([_turn(stop="refusal")])
    assert _agent(model, echo).run([TextPart(text="go")], ctx).stopped == "refusal"


def test_native_blocks_go_back_unchanged(echo: Tool, ctx: HookContext) -> None:
    native = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "tool_use"}]
    model = ScriptedModel([_turn(_call(1), native=native), _turn(text="ok")])
    _agent(model, echo).run([TextPart(text="go")], ctx)
    assistant = model.calls[1].messages[1]
    assert assistant.role == "assistant"
    assert assistant.native == native
