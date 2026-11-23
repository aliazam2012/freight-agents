"""Typed tools: a plain function, a Pydantic input, a Pydantic output, a risk class.

Tools hold no policy. Validation, allowlists, approvals and the rest live in
hooks, so every tool gets the same treatment and a tool stays easy to test.
"""

from __future__ import annotations

import copy
import inspect
import typing
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from freight_agents.llm import ToolSpec
from pydantic import BaseModel

In = TypeVar("In", bound=BaseModel)
Out = TypeVar("Out", bound=BaseModel)


class Risk(StrEnum):
    READ = "read"  # no side effects
    WRITE = "write"  # changes state we own
    SEND = "send"  # leaves the system: email, a carrier filing, a chat post


class UnknownTool(KeyError):
    """The model asked for a tool that is not registered."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: Risk
    fn: Callable[[Any], BaseModel]

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=strict_schema(self.input_model),
        )


def tool(*, name: str, description: str, risk: Risk) -> Callable[[Callable[[In], Out]], Tool]:
    """Turn ``def f(args: InModel) -> OutModel`` into a Tool."""

    def wrap(fn: Callable[[In], Out]) -> Tool:
        params = list(inspect.signature(fn).parameters)
        if len(params) != 1:
            raise TypeError(f"tool {name} must take exactly one argument, its input model")
        hints = typing.get_type_hints(fn)
        input_model = _model_hint(name, "input", hints.get(params[0]))
        output_model = _model_hint(name, "output", hints.get("return"))
        optional = [f for f, info in input_model.model_fields.items() if not info.is_required()]
        if optional:
            raise ValueError(
                f"tool {name}: input fields {', '.join(optional)} have defaults; strict tool "
                "schemas need every field required (use `X | None` without a default)"
            )
        return Tool(name, description, input_model, output_model, risk, fn)

    return wrap


def _model_hint(tool_name: str, label: str, hint: object) -> type[BaseModel]:
    if isinstance(hint, type) and issubclass(hint, BaseModel):
        return hint
    raise TypeError(f"tool {tool_name} needs a Pydantic {label} model in its type hints")


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A self-contained JSON schema every provider's strict mode accepts.

    References are inlined, every object is closed with additionalProperties
    false, every property is required, and titles and defaults are dropped.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs[node["$ref"].rsplit("/", 1)[-1]]
                return resolve(copy.deepcopy(target))
            out = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    result: dict[str, Any] = resolve(raw)
    return result


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.register(t)

    def register(self, t: Tool) -> None:
        if t.name in self._tools:
            raise ValueError(f"tool {t.name} is already registered")
        self._tools[t.name] = t

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownTool(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]
