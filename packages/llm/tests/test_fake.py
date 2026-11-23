import pytest
from freight_agents.llm import Message, ModelTurn, ScriptedModel, ScriptExhausted, TextPart, Usage


def _turn(text: str) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=[], stop="end", usage=Usage(), model="scripted")


def test_turns_come_back_in_order_and_calls_are_recorded() -> None:
    model = ScriptedModel([_turn("one"), _turn("two")])
    msgs = [Message(role="user", parts=[TextPart(text="hi")])]
    assert model.complete("sys", msgs, []).text == "one"
    assert model.complete("sys", msgs, []).text == "two"
    assert len(model.calls) == 2
    assert model.calls[0].system == "sys"


def test_running_out_of_script_raises() -> None:
    model = ScriptedModel([_turn("only")])
    model.complete("s", [], [])
    with pytest.raises(ScriptExhausted):
        model.complete("s", [], [])
