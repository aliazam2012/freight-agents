"""Serve tools over MCP without a second policy path.

Every ``tools/call`` is routed to a toolkit (registry, hooks, context) and run
through ``run_tool``, exactly as an agent's call would be: validation, state
rules, taint, idempotency, approvals, redaction and audit all apply. An MCP
client gains no power an agent does not have.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from freight_agents.agentcore.approvals import AuditLog
from freight_agents.agentcore.hooks import HookContext, PostHook, PreHook, run_tool
from freight_agents.agentcore.tools import ToolRegistry
from freight_agents.llm import ToolCall, ToolSpec

import mcp.types as types
from mcp.server.lowlevel import Server


class RouteError(Exception):
    """The call cannot be routed; ``code`` goes back to the client."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Route:
    registry: ToolRegistry
    pre: Sequence[PreHook]
    post: Sequence[PostHook]
    ctx: HookContext
    tool: str
    args: dict[str, Any]


Router = Callable[[str, dict[str, Any]], Route]


def _error(code: str, reason: str) -> types.CallToolResult:
    body = json.dumps({"error": code, "reason": reason})
    return types.CallToolResult(content=[types.TextContent(text=body)], is_error=True)


def build_server(
    name: str,
    specs: Sequence[ToolSpec],
    route: Router,
    audit: AuditLog | None = None,
    instructions: str | None = None,
) -> Server[Any]:
    exposed = {s.name for s in specs}

    async def on_list_tools(
        ctx: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=s.name, description=s.description, input_schema=s.input_schema)
                for s in specs
            ]
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in exposed:
            return _error("unknown_tool", f"no tool named {params.name}")
        try:
            target = route(params.name, dict(params.arguments or {}))
        except RouteError as exc:
            return _error(exc.code, exc.reason)
        call = ToolCall(id=f"mcp-{uuid.uuid4().hex[:12]}", name=target.tool, args=target.args)
        result = run_tool(call, target.registry, target.pre, target.post, target.ctx, audit)
        message = result.as_result()
        return types.CallToolResult(
            content=[types.TextContent(text=message.content)], is_error=message.is_error
        )

    return Server(
        name, instructions=instructions, on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )
