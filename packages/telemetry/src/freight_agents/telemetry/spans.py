"""Spans on the OpenTelemetry API, named with the GenAI semantic conventions.

The GenAI conventions are still in Development status, so every attribute
name lives here: a rename upstream is a one-line change. Without an SDK
configured these spans cost nothing; the application decides where they go.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from freight_agents.llm import Usage
from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.util.types import AttributeValue

TRACER_NAME = "freight_agents"

OPERATION = "gen_ai.operation.name"
REQUEST_MODEL = "gen_ai.request.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
TOOL_NAME = "gen_ai.tool.name"
AGENT_NAME = "gen_ai.agent.name"
# Not in the conventions: how the hook pipeline settled the call.
TOOL_STATUS = "freight_agents.tool.status"


@contextmanager
def span(name: str, attributes: Mapping[str, AttributeValue] | None = None) -> Iterator[Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=dict(attributes or {})) as current:
        yield current


def model_attrs(model: str, usage: Usage) -> dict[str, AttributeValue]:
    return {
        OPERATION: "chat",
        REQUEST_MODEL: model,
        INPUT_TOKENS: usage.input_tokens,
        OUTPUT_TOKENS: usage.output_tokens,
    }


def tool_attrs(tool: str, status: str) -> dict[str, AttributeValue]:
    return {OPERATION: "execute_tool", TOOL_NAME: tool, TOOL_STATUS: status}


def agent_attrs(agent: str) -> dict[str, AttributeValue]:
    return {OPERATION: "invoke_agent", AGENT_NAME: agent}
