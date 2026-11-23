"""Built-in hooks. Each one is small, does one thing, and is tested alone."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .hooks import ALLOW, Decision, Deny, HookContext, PostHook, PreHook
from .tools import Tool


def state_allowlist(policy: Mapping[str, set[str]]) -> PreHook:
    """Allow each tool only in the case states listed for it; unlisted tools are denied."""

    def hook(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        allowed = policy.get(tool.name)
        if allowed is None:
            return Deny("state", f"{tool.name} has no state policy, so it is not allowed")
        if ctx.state not in allowed:
            return Deny("state", f"{tool.name} is not allowed in state {ctx.state}")
        return ALLOW

    return hook


def budget_guard(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
    if ctx.tool_calls_left is not None and ctx.tool_calls_left <= 0:
        return Deny("budget", "the tool-call budget for this run is spent")
    return ALLOW


def cap_size(max_chars: int = 8000) -> PostHook:
    """Truncate long strings in an output, saying how much was cut."""

    def cut(value: Any) -> Any:
        if isinstance(value, str) and len(value) > max_chars:
            return f"{value[:max_chars]} [truncated {len(value) - max_chars} characters]"
        if isinstance(value, dict):
            return {k: cut(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cut(v) for v in value]
        return value

    def hook(tool: Tool, output: BaseModel, ctx: HookContext) -> BaseModel:
        return type(output).model_validate(cut(output.model_dump(mode="json")))

    return hook
