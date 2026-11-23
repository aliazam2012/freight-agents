"""Provider-neutral conversation types.

Adapters translate these to and from each provider's wire format. A message
may also carry ``native``: the provider's own content blocks for an assistant
turn, which the same adapter sends back unchanged on the next request (some
providers require their reasoning blocks to come back exactly as returned).
``native`` never affects how a request is identified for recording.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextPart(_Frozen):
    kind: Literal["text"] = "text"
    text: str


class ImagePart(_Frozen):
    kind: Literal["image"] = "image"
    media_type: str
    data_b64: str


class ToolCall(_Frozen):
    kind: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    args: dict[str, Any]


class ToolResult(_Frozen):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    content: str
    is_error: bool = False


Part = Annotated[TextPart | ImagePart | ToolCall | ToolResult, Field(discriminator="kind")]


class Message(_Frozen):
    role: Literal["user", "assistant"]
    parts: list[Part]
    native: Any = None


class ToolSpec(_Frozen):
    name: str
    description: str
    input_schema: dict[str, Any]


class Usage(_Frozen):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


Stop = Literal["end", "tool_use", "max_tokens", "refusal"]


class ModelTurn(_Frozen):
    text: str
    tool_calls: list[ToolCall]
    stop: Stop
    usage: Usage
    model: str
    native: Any = None


class Model(Protocol):
    """Anything that can take one turn of a conversation."""

    @property
    def name(self) -> str: ...

    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelTurn: ...
