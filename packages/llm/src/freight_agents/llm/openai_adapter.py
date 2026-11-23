"""OpenAI models through the Responses API.

Requests are stateless (``store=False``): OpenAI keeps no conversation, and
the encrypted reasoning items it returns are sent back unchanged on the next
turn so reasoning carries across tool calls. The model id has no default; it
comes from configuration, because model names change faster than this file.
"""

from __future__ import annotations

import json
from typing import Any

from .types import (
    ImagePart,
    Message,
    ModelTurn,
    Stop,
    TextPart,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)


class OpenAIModel:
    def __init__(
        self,
        model: str,
        client: Any = None,
        reasoning_effort: str = "low",
        max_output_tokens: int = 16000,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = reasoning_effort
        self._max_output_tokens = max_output_tokens

    @property
    def name(self) -> str:
        return self._model

    def _api(self) -> Any:
        if self._client is None:
            import openai  # deferred so offline use never needs credentials

            self._client = openai.OpenAI()
        return self._client

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        request: dict[str, Any] = {
            "model": self._model,
            "instructions": system,
            "input": [item for m in messages for item in _to_items(m)],
            "reasoning": {"effort": self._effort},
            "max_output_tokens": self._max_output_tokens,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                    "strict": True,
                }
                for t in tools
            ]
        return _from_response(self._api().responses.create(**request))


def _to_items(message: Message) -> list[dict[str, Any]]:
    if message.role == "assistant":
        if message.native is not None:
            return list(message.native)
        items: list[dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                items.append({"role": "assistant", "content": part.text})
            elif isinstance(part, ToolCall):
                items.append(
                    {
                        "type": "function_call",
                        "call_id": part.id,
                        "name": part.name,
                        "arguments": json.dumps(part.args),
                    }
                )
        return items

    items = []
    content: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            content.append({"type": "input_text", "text": part.text})
        elif isinstance(part, ImagePart):
            url = f"data:{part.media_type};base64,{part.data_b64}"
            content.append({"type": "input_image", "image_url": url})
        elif isinstance(part, ToolResult):
            items.append(
                {"type": "function_call_output", "call_id": part.call_id, "output": part.content}
            )
    if content:
        items.insert(0, {"role": "user", "content": content})
    return items


def _from_response(response: Any) -> ModelTurn:
    calls: list[ToolCall] = []
    refused = False
    for item in response.output:
        if item.type == "function_call":
            calls.append(ToolCall(id=item.call_id, name=item.name, args=_args(item.arguments)))
        elif item.type == "message":
            refused = refused or any(part.type == "refusal" for part in item.content)

    stop: Stop
    details = response.incomplete_details
    if calls:
        stop = "tool_use"
    elif refused:
        stop = "refusal"
    elif response.status == "incomplete" and details and details.reason == "max_output_tokens":
        stop = "max_tokens"
    else:
        stop = "end"

    cached = response.usage.input_tokens_details.cached_tokens or 0
    usage = Usage(
        input_tokens=response.usage.input_tokens - cached,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=cached,
    )
    return ModelTurn(
        text=response.output_text,
        tool_calls=calls,
        stop=stop,
        usage=usage,
        model=response.model,
        native=[item.to_dict() for item in response.output],
    )


def _args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_unparsed_arguments": raw}
    return parsed if isinstance(parsed, dict) else {"_unparsed_arguments": raw}
