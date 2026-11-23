from types import SimpleNamespace
from typing import Any

from freight_agents.llm import Message, TextPart, ToolCall, ToolResult, ToolSpec, Usage
from freight_agents.llm.openai_adapter import OpenAIModel
from openai.types.responses import Response

TOOLS = [ToolSpec(name="lookup", description="Look up.", input_schema={"type": "object"})]
USER = [Message(role="user", parts=[TextPart(text="Is PRO 1 delivered?")])]
USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "input_tokens_details": {"cached_tokens": 4, "cache_write_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 1},
}


class FakeResponses:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Response:
        self.kwargs = kwargs
        return self.response


def _message(*content: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": list(content),
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "output_text", "text": text, "annotations": []}


def _response(output: list[dict[str, Any]], **extra: Any) -> Response:
    body = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "test-model",
        "status": "completed",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": output,
        "usage": USAGE,
        "incomplete_details": None,
    }
    return Response.model_validate({**body, **extra})


def _model(response: Response) -> tuple[OpenAIModel, FakeResponses]:
    fake = FakeResponses(response)
    return OpenAIModel(client=SimpleNamespace(responses=fake), model="test-model"), fake


def test_request_shape() -> None:
    model, fake = _model(_response([_message(_text("yes"))]))
    model.complete("You check shipments.", USER, TOOLS)
    sent = fake.kwargs
    assert sent["model"] == "test-model"
    assert sent["instructions"] == "You check shipments."
    assert sent["store"] is False
    assert sent["include"] == ["reasoning.encrypted_content"]
    assert sent["reasoning"] == {"effort": "low"}
    assert sent["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Look up.",
            "parameters": {"type": "object"},
            "strict": True,
        }
    ]
    assert sent["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Is PRO 1 delivered?"}]}
    ]


def test_function_calls_become_tool_calls_and_native_round_trips() -> None:
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": []}
    call = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "lookup",
        "arguments": '{"pro": "1"}',
        "status": "completed",
    }
    model, _ = _model(_response([reasoning, call]))
    turn = model.complete("s", USER, TOOLS)
    assert turn.stop == "tool_use"
    assert turn.tool_calls == [ToolCall(id="call_1", name="lookup", args={"pro": "1"})]

    second, fake = _model(_response([_message(_text("delivered"))]))
    history = [
        *USER,
        Message(role="assistant", parts=list(turn.tool_calls), native=turn.native),
        Message(role="user", parts=[ToolResult(call_id="call_1", content='{"found": true}')]),
    ]
    assert second.complete("s", history, TOOLS).text == "delivered"
    sent = fake.kwargs["input"]
    assert sent[1:3] == turn.native
    assert sent[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"found": true}',
    }


def test_malformed_arguments_are_kept_for_validation_to_deny() -> None:
    call = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "c",
        "name": "lookup",
        "arguments": "{not json",
        "status": "completed",
    }
    model, _ = _model(_response([call]))
    assert model.complete("s", USER, TOOLS).tool_calls[0].args == {
        "_unparsed_arguments": "{not json"
    }


def test_refusal_and_incomplete_map() -> None:
    model, _ = _model(_response([_message({"type": "refusal", "refusal": "no"})]))
    assert model.complete("s", USER, []).stop == "refusal"
    model, _ = _model(
        _response(
            [_message(_text("cut"))],
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
        )
    )
    assert model.complete("s", USER, []).stop == "max_tokens"


def test_usage_separates_cached_input() -> None:
    model, _ = _model(_response([_message(_text("x"))]))
    assert model.complete("s", USER, []).usage == Usage(
        input_tokens=6, output_tokens=5, cache_read_tokens=4
    )
