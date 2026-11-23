"""The agent loop: ask the model, run its tool calls through the hooks, repeat.

The loop owns the limits (turns, tool calls, dollars) and the conversation.
It never changes a case's state; tools and the state engine do that.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from freight_agents.llm import (
    ImagePart,
    Message,
    Model,
    Part,
    Price,
    TextPart,
    ToolResult,
    Usage,
    cost_usd,
)
from freight_agents.telemetry.spans import agent_attrs, model_attrs, span, tool_attrs

from .approvals import AuditLog
from .guards import budget_guard
from .hooks import HookContext, PostHook, PreHook, ToolOutcome, run_tool
from .tools import ToolRegistry

Stopped = Literal["done", "max_turns", "budget", "refusal", "max_tokens"]


@dataclass(frozen=True)
class Budget:
    max_turns: int = 8
    max_tool_calls: int = 20
    max_cost_usd: float | None = 0.50


@dataclass(frozen=True)
class AgentResult:
    text: str
    outcomes: list[ToolOutcome]
    usage: Usage
    cost_usd: float | None  # None when any turn ran on a model with no known price
    turns: int
    stopped: Stopped
    messages: list[Message]

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.status in ("denied", "error"))


class Agent:
    def __init__(
        self,
        name: str,
        model: Model,
        registry: ToolRegistry,
        system: str,
        pre: Sequence[PreHook] = (),
        post: Sequence[PostHook] = (),
        audit: AuditLog | None = None,
        budget: Budget | None = None,
        prices: Mapping[str, Price] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.registry = registry
        self.system = system
        # The budget check always runs first, whatever hooks the caller passes.
        self.pre: list[PreHook] = [budget_guard, *pre]
        self.post = list(post)
        self.audit = audit
        self.budget = budget or Budget()
        self.prices = prices

    def run(
        self,
        user: Sequence[TextPart | ImagePart],
        ctx: HookContext,
        history: Sequence[Message] = (),
    ) -> AgentResult:
        messages: list[Message] = [*history, Message(role="user", parts=list(user))]
        specs = self.registry.specs()
        outcomes: list[ToolOutcome] = []
        usage = Usage()
        cost: float | None = 0.0
        calls_left = self.budget.max_tool_calls
        text = ""

        def finish(stopped: Stopped, turns: int) -> AgentResult:
            return AgentResult(text, outcomes, usage, cost, turns, stopped, messages)

        with span(f"invoke_agent {self.name}", agent_attrs(self.name)):
            for turn_no in range(1, self.budget.max_turns + 1):
                with span(f"chat {self.model.name}") as current:
                    turn = self.model.complete(self.system, messages, specs)
                    current.set_attributes(model_attrs(turn.model, turn.usage))
                usage = usage + turn.usage
                turn_cost = cost_usd(turn.model, turn.usage, self.prices)
                cost = None if cost is None or turn_cost is None else cost + turn_cost
                text = turn.text
                parts: list[Part] = [TextPart(text=turn.text)] if turn.text else []
                parts.extend(turn.tool_calls)
                messages.append(Message(role="assistant", parts=parts, native=turn.native))

                if turn.stop == "refusal":
                    return finish("refusal", turn_no)
                if not turn.tool_calls:
                    return finish("max_tokens" if turn.stop == "max_tokens" else "done", turn_no)

                results: list[Part] = []
                for call in turn.tool_calls:
                    ctx.tool_calls_left = calls_left
                    with span(f"execute_tool {call.name}") as current:
                        outcome = run_tool(
                            call, self.registry, self.pre, self.post, ctx, self.audit
                        )
                        current.set_attributes(tool_attrs(call.name, outcome.status))
                    if outcome.code != "budget":
                        calls_left -= 1
                    outcomes.append(outcome)
                    results.append(outcome.as_result())
                messages.append(Message(role="user", parts=results))

                if any(o.code == "budget" for o in outcomes):
                    return finish("budget", turn_no)
                limit = self.budget.max_cost_usd
                if limit is not None and cost is not None and cost >= limit:
                    return finish("budget", turn_no)
            return finish("max_turns", self.budget.max_turns)


def tool_results(message: Message) -> list[ToolResult]:
    return [p for p in message.parts if isinstance(p, ToolResult)]
