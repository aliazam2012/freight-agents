from typing import Any

import pytest
from freight_agents.agentcore.tools import Risk, ToolRegistry, UnknownTool, strict_schema, tool
from pydantic import BaseModel


class Address(BaseModel):
    city: str
    zip_code: str | None


class LookupIn(BaseModel):
    pro_number: str
    ship_to: Address
    note: str | None


class LookupOut(BaseModel):
    found: bool


@tool(name="lookup_shipment", description="Find a shipment by PRO number.", risk=Risk.READ)
def lookup(args: LookupIn) -> LookupOut:
    return LookupOut(found=args.pro_number == "1")


def _objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    if schema.get("type") == "object":
        found.append(schema)
    for value in schema.values():
        if isinstance(value, dict):
            found.extend(_objects(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found.extend(_objects(item))
    return found


def test_decorator_reads_models_and_risk() -> None:
    assert lookup.input_model is LookupIn
    assert lookup.output_model is LookupOut
    assert lookup.risk is Risk.READ
    assert lookup.fn(LookupIn(pro_number="1", ship_to=Address(city="X", zip_code=None), note=None))


def test_strict_schema_closes_and_requires_every_object() -> None:
    schema = strict_schema(LookupIn)
    objects = _objects(schema)
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])
    assert "$ref" not in str(schema)
    assert "$defs" not in schema


def test_input_model_with_a_default_is_rejected() -> None:
    class WithDefault(BaseModel):
        pro_number: str = "0"

    with pytest.raises(ValueError, match="pro_number"):

        @tool(name="bad", description="Bad.", risk=Risk.READ)
        def bad(args: WithDefault) -> LookupOut:
            return LookupOut(found=False)


def test_registry_keeps_order_and_names_unknown_tools() -> None:
    @tool(name="second", description="Second.", risk=Risk.WRITE)
    def second(args: LookupIn) -> LookupOut:
        return LookupOut(found=True)

    registry = ToolRegistry([lookup, second])
    assert [s.name for s in registry.specs()] == ["lookup_shipment", "second"]
    assert registry.specs()[0].input_schema == strict_schema(LookupIn)
    with pytest.raises(UnknownTool):
        registry.get("nope")


def test_registry_rejects_a_duplicate_name() -> None:
    with pytest.raises(ValueError, match="lookup_shipment"):
        ToolRegistry([lookup, lookup])
