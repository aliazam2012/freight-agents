"""Claude through the Anthropic Messages API.

Request rules for the current models (Claude API reference, cached
2026-11-03): effort is set explicitly in ``output_config``; ``thinking`` is
left out (it is always on for Opus 5.5); no sampling parameters, no prefill,
no forced ``tool_choice``; tools are strict. The assistant's returned blocks
go back unchanged, thinking blocks included. Opus 5.5 and Sonnet 5.5 requests
opt in to server-side refusal fallbacks, so a declined request is retried on
a fallback model inside the same call.
"""

from __future__ import annotations

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

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})
_STOPS: dict[str, Stop] = {
    "end_turn": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class UnsupportedStop(RuntimeError):
    """The API stopped for a reason this adapter does not handle."""


class AnthropicModel:
    def __init__(
        self,
        client: Any = None,
        model: str = DEFAULT_MODEL,
        effort: str = "low",
        max_tokens: int = 16000,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return self._model

    def _api(self) -> Any:
        if self._client is None:
            import anthropic  # deferred so offline use never needs credentials

            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [_to_wire(m) for m in messages],
            "output_config": {"effort": self._effort},
        }
        if tools:
            request["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "strict": True,
                }
                for t in tools
            ]
        if self._model in FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        response = self._api().beta.messages.create(**request)
        return _from_wire(response)


def _to_wire(message: Message) -> dict[str, Any]:
    if message.role == "assistant" and message.native is not None:
        return {"role": "assistant", "content": message.native}
    blocks: list[dict[str, Any]] = []
    for part in message.parts:
        match part:
            case TextPart(text=text):
                blocks.append({"type": "text", "text": text})
            case ImagePart(media_type=media_type, data_b64=data):
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data},
                    }
                )
            case ToolCall(id=call_id, name=name, args=args):
                blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
            case ToolResult(call_id=call_id, content=content, is_error=is_error):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": content,
                        "is_error": is_error,
                    }
                )
    return {"role": message.role, "content": blocks}


def _from_wire(response: Any) -> ModelTurn:
    stop = _STOPS.get(response.stop_reason)
    if stop is None:
        raise UnsupportedStop(f"stop_reason {response.stop_reason!r} is not handled")
    text = "".join(b.text for b in response.content if b.type == "text")
    calls = [
        ToolCall(id=b.id, name=b.name, args=dict(b.input))
        for b in response.content
        if b.type == "tool_use"
    ]
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
    )
    return ModelTurn(
        text=text,
        tool_calls=calls,
        stop=stop,
        usage=usage,
        model=response.model,
        native=[b.to_dict() for b in response.content],
    )
