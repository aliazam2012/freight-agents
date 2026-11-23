"""The tool pipeline: validate, pre-hooks, run, validate, post-hooks.

Pre-hooks decide whether a call runs. The first decision other than Allow
wins, except Rewrite, which replaces the arguments and lets the next hook
see them. Post-hooks may change a valid output (redaction, size caps) and
record it (audit, tracing). Input and output validation are not hooks: no
tool runs on unvalidated input or returns an unchecked output.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from freight_agents.llm import ToolCall, ToolResult
from pydantic import BaseModel, ValidationError

from .taint import TaintSet
from .tools import Tool, ToolRegistry, UnknownTool


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Deny:
    code: str
    reason: str


@dataclass(frozen=True)
class Rewrite:
    args: dict[str, Any]


@dataclass(frozen=True)
class Pending:
    approval_id: str


@dataclass(frozen=True)
class Replay:
    output: dict[str, Any]


Decision = Allow | Deny | Rewrite | Pending | Replay
ALLOW = Allow()


@dataclass
class HookContext:
    run_id: str
    agent: str
    now: datetime
    case_id: str | None = None
    state: str | None = None
    tool_calls_left: int | None = None
    taint: TaintSet = field(default_factory=TaintSet)


PreHook = Callable[[Tool, dict[str, Any], HookContext], Decision]
PostHook = Callable[[Tool, BaseModel, HookContext], BaseModel]

Status = Literal["ok", "denied", "pending", "error", "replayed"]


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    tool: str
    status: Status
    output: dict[str, Any] | None = None
    code: str | None = None
    reason: str | None = None

    def as_result(self) -> ToolResult:
        """What the model is told about this call."""
        if self.status in ("ok", "replayed"):
            body: dict[str, Any] = self.output or {}
        elif self.status == "pending":
            body = {"status": "waiting_for_human_approval", **(self.output or {})}
        else:
            body = {"error": self.code, "reason": self.reason}
        return ToolResult(
            call_id=self.call_id,
            content=json.dumps(body, ensure_ascii=False, default=str),
            is_error=self.status in ("denied", "error"),
        )


def run_tool(
    call: ToolCall,
    registry: ToolRegistry,
    pre: Sequence[PreHook],
    post: Sequence[PostHook],
    ctx: HookContext,
) -> ToolOutcome:
    def outcome(status: Status, **kw: Any) -> ToolOutcome:
        return ToolOutcome(call_id=call.id, tool=call.name, status=status, **kw)

    try:
        tool = registry.get(call.name)
    except UnknownTool:
        return outcome("error", code="unknown_tool", reason=f"no tool named {call.name}")

    parsed, args, problem = _validate(tool, call.args)
    if problem:
        return outcome("denied", code="invalid_input", reason=problem)

    for hook in pre:
        decision = hook(tool, args, ctx)
        match decision:
            case Allow():
                continue
            case Rewrite(args=new_args):
                parsed, args, problem = _validate(tool, new_args)
                if problem:
                    return outcome("denied", code="invalid_input", reason=problem)
            case Deny(code=code, reason=reason):
                return outcome("denied", code=code, reason=reason)
            case Pending(approval_id=approval_id):
                return outcome("pending", code="approval", output={"approval_id": approval_id})
            case Replay(output=output):
                return outcome("replayed", output=output)

    try:
        result = tool.fn(parsed)
    except Exception as exc:  # a tool failure is reported to the model, never raised
        return outcome("error", code="tool_failed", reason=f"{type(exc).__name__}: {exc}")
    if not isinstance(result, tool.output_model):
        return outcome(
            "error",
            code="invalid_output",
            reason=f"{tool.name} returned {type(result).__name__}, "
            f"not {tool.output_model.__name__}",
        )

    for post_hook in post:
        try:
            result = post_hook(tool, result, ctx)
        except Exception as exc:
            return outcome("error", code="post_hook", reason=f"{type(exc).__name__}: {exc}")
    return outcome("ok", output=result.model_dump(mode="json"))


def _validate(tool: Tool, raw: dict[str, Any]) -> tuple[Any, dict[str, Any], str | None]:
    try:
        parsed = tool.input_model.model_validate(raw)
    except ValidationError as exc:
        return None, raw, exc.errors(include_url=False).__repr__()
    return parsed, parsed.model_dump(mode="json"), None
