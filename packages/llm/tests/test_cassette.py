from pathlib import Path

import pytest
from freight_agents.llm import (
    CassetteMiss,
    Message,
    ModelTurn,
    RecordingModel,
    ReplayModel,
    ScriptedModel,
    TextPart,
    ToolCall,
    ToolSpec,
    Usage,
    request_key,
)

TOOLS = [ToolSpec(name="lookup", description="Look up", input_schema={"type": "object"})]


def _msgs(text: str, native: object = None) -> list[Message]:
    return [
        Message(role="user", parts=[TextPart(text=text)]),
        Message(role="assistant", parts=[TextPart(text="ok")], native=native),
    ]


def test_key_is_stable_for_equal_requests() -> None:
    assert request_key("m", "s", _msgs("a"), TOOLS) == request_key("m", "s", _msgs("a"), TOOLS)


def test_key_changes_when_a_message_changes() -> None:
    assert request_key("m", "s", _msgs("a"), TOOLS) != request_key("m", "s", _msgs("b"), TOOLS)


def test_key_ignores_provider_native_payload() -> None:
    with_native = _msgs("a", native=[{"type": "thinking", "thinking": "x"}])
    assert request_key("m", "s", _msgs("a"), TOOLS) == request_key("m", "s", with_native, TOOLS)


def test_a_recorded_run_replays_offline(tmp_path: Path) -> None:
    turn = ModelTurn(
        text="",
        tool_calls=[ToolCall(id="c1", name="lookup", args={"pro": "1"})],
        stop="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5),
        model="m",
        native=[{"type": "tool_use", "id": "c1"}],
    )
    cassette = tmp_path / "run.jsonl"
    recorder = RecordingModel(ScriptedModel([turn], name="m"), cassette)
    assert recorder.complete("s", _msgs("a"), TOOLS) == turn
    replay = ReplayModel(cassette, name="m")
    assert replay.complete("s", _msgs("a"), TOOLS) == turn


def test_an_unrecorded_request_is_a_miss(tmp_path: Path) -> None:
    cassette = tmp_path / "empty.jsonl"
    cassette.write_text("")
    with pytest.raises(CassetteMiss):
        ReplayModel(cassette, name="m").complete("s", _msgs("a"), TOOLS)
