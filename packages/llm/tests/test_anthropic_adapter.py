from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage
from freight_agents.llm import Message, TextPart, ToolCall, ToolResult, ToolSpec, Usage
from freight_agents.llm.anthropic_adapter import AnthropicModel, UnsupportedStop

TOOLS = [ToolSpec(name="lookup", description="Look up.", input_schema={"type": "object"})]


class FakeMessages:
    def __init__(self, response: BetaMessage) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> BetaMessage:
        self.kwargs = kwargs
        return self.response


def _response(
    content: list[dict[str, Any]], stop: str = "end_turn", usage: dict[str, Any] | None = None
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5},
        }
    )


def _model(response: BetaMessage, **kw: Any) -> tuple[AnthropicModel, FakeMessages]:
    messages = FakeMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicModel(client=client, **kw), messages


USER = [Message(role="user", parts=[TextPart(text="Is PRO 1 delivered?")])]


def test_request_follows_the_current_api_rules() -> None:
    model, fake = _model(_response([{"type": "text", "text": "yes"}]))
    model.complete("You check shipments.", USER, TOOLS)
    sent = fake.kwargs
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"] == {"effort": "low"}
    assert sent["system"] == "You check shipments."
    for banned in ("thinking", "temperature", "top_p", "top_k", "tool_choice"):
        assert banned not in sent
    assert sent["tools"] == [
        {
            "name": "lookup",
            "description": "Look up.",
            "input_schema": {"type": "object"},
            "strict": True,
        }
    ]


def test_opus_and_sonnet_get_refusal_fallbacks_haiku_does_not() -> None:
    for name in ("claude-opus-5-5", "claude-sonnet-5-5"):
        model, fake = _model(_response([{"type": "text", "text": "ok"}]), model=name)
        model.complete("s", USER, [])
        assert fake.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
        assert fake.kwargs["fallbacks"] == "default"
    model, fake = _model(_response([{"type": "text", "text": "ok"}]), model="claude-haiku-5-5")
    model.complete("s", USER, [])
    assert "fallbacks" not in fake.kwargs
    assert "betas" not in fake.kwargs


def test_tool_results_go_in_one_user_message() -> None:
    model, fake = _model(_response([{"type": "text", "text": "ok"}]))
    history = [
        *USER,
        Message(
            role="assistant",
            parts=[
                ToolCall(id="a", name="lookup", args={}),
                ToolCall(id="b", name="lookup", args={}),
            ],
        ),
        Message(
            role="user",
            parts=[
                ToolResult(call_id="a", content='{"found": true}'),
                ToolResult(call_id="b", content='{"error": "x"}', is_error=True),
            ],
        ),
    ]
    model.complete("s", history, TOOLS)
    last = fake.kwargs["messages"][-1]
    assert last["role"] == "user"
    assert last["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "a",
            "content": '{"found": true}',
            "is_error": False,
        },
        {"type": "tool_result", "tool_use_id": "b", "content": '{"error": "x"}', "is_error": True},
    ]


def test_native_assistant_blocks_round_trip_unchanged() -> None:
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "sig-1"},
        {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {"pro": "1"}},
    ]
    model, _ = _model(_response(blocks, stop="tool_use"))
    turn = model.complete("s", USER, TOOLS)
    assert turn.tool_calls == [ToolCall(id="tu_1", name="lookup", args={"pro": "1"})]
    assert turn.native == blocks

    second, fake = _model(_response([{"type": "text", "text": "done"}]))
    history = [*USER, Message(role="assistant", parts=list(turn.tool_calls), native=turn.native)]
    second.complete("s", history, TOOLS)
    assert fake.kwargs["messages"][1] == {"role": "assistant", "content": blocks}


@pytest.mark.parametrize(
    ("wire", "ours"),
    [
        ("end_turn", "end"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("refusal", "refusal"),
    ],
)
def test_stop_reasons_map(wire: str, ours: str) -> None:
    model, _ = _model(_response([{"type": "text", "text": "x"}], stop=wire))
    assert model.complete("s", USER, []).stop == ours


def test_an_unexpected_stop_reason_raises() -> None:
    model, _ = _model(_response([{"type": "text", "text": "x"}], stop="pause_turn"))
    with pytest.raises(UnsupportedStop):
        model.complete("s", USER, [])


def test_usage_maps_cache_reads_and_defaults_them_to_zero() -> None:
    usage = {"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 100}
    model, _ = _model(_response([{"type": "text", "text": "x"}], usage=usage))
    assert model.complete("s", USER, []).usage == Usage(
        input_tokens=7, output_tokens=3, cache_read_tokens=100
    )
    model, _ = _model(_response([{"type": "text", "text": "x"}]))
    assert model.complete("s", USER, []).usage.cache_read_tokens == 0
