"""Built-in hooks. Each one is small, does one thing, and is tested alone."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from .approvals import ApprovalQueue, IdempotencyStore, args_hash
from .hooks import ALLOW, Decision, Deny, HookContext, Pending, PostHook, PreHook, Replay
from .tools import Risk, Tool

Validator = Callable[[Any], bool]


def state_allowlist(policy: Mapping[str, set[str]]) -> PreHook:
    """Allow each tool only in the case states listed for it; unlisted tools are denied."""

    def hook(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        allowed = policy.get(tool.name)
        if allowed is None:
            return Deny("state", f"{tool.name} has no state policy, so it is not allowed")
        if ctx.state not in allowed:
            return Deny("state", f"{tool.name} is not allowed in state {ctx.state}")
        return ALLOW

    return hook


def budget_guard(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
    if ctx.tool_calls_left is not None and ctx.tool_calls_left <= 0:
        return Deny("budget", "the tool-call budget for this run is spent")
    return ALLOW


def taint_guard(controls: Mapping[str, Mapping[str, Validator | None]]) -> PreHook:
    """Stop untrusted text from steering a write or a send.

    ``controls`` names, per tool, the arguments that decide where an action
    goes or what it commits to (a recipient, an amount), each with a validator
    that may accept a tainted value (None accepts none). Every SEND tool must
    be declared, so a new outbound tool cannot ship unguarded by accident.
    """

    def hook(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        declared = controls.get(tool.name)
        if declared is None:
            if tool.risk is Risk.SEND:
                return Deny("unguarded_send", f"{tool.name} sends outside and declares no controls")
            return ALLOW
        for arg, validator in declared.items():
            for value in _strings(args.get(arg)):
                sources = ctx.taint.sources(value)
                if sources and not (validator is not None and validator(value)):
                    return Deny(
                        "tainted",
                        f"{arg} came from untrusted input ({', '.join(sorted(sources))}) "
                        "and was not accepted",
                    )
        return ALLOW

    return hook


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def idempotency(store: IdempotencyStore) -> tuple[PreHook, PostHook]:
    """A repeated WRITE with the same tool, case and arguments returns the first result."""

    def pre(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        if tool.risk is not Risk.WRITE:
            return ALLOW
        seen = store.get(args_hash(tool.name, ctx.case_id, args))
        return ALLOW if seen is None else Replay(seen)

    def post(tool: Tool, args: dict[str, Any], output: BaseModel, ctx: HookContext) -> BaseModel:
        if tool.risk is Risk.WRITE:
            store.put(args_hash(tool.name, ctx.case_id, args), output.model_dump(mode="json"))
        return output

    return pre, post


def approval_gate(
    queue: ApprovalQueue, needs_approval: Callable[[Tool, dict[str, Any]], bool] | None = None
) -> PreHook:
    """SEND calls, and any call ``needs_approval`` picks, wait for a person.

    An approval covers one exact call: the same tool, case and arguments, once.
    """

    def hook(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        wanted = tool.risk is Risk.SEND or (
            needs_approval is not None and needs_approval(tool, args)
        )
        if not wanted:
            return ALLOW
        if queue.use(tool.name, args, ctx.case_id):
            return ALLOW
        return Pending(queue.request(tool.name, args, ctx.case_id))

    return hook


def cap_size(max_chars: int = 8000) -> PostHook:
    """Truncate long strings in an output, saying how much was cut."""

    def cut(value: Any) -> Any:
        if isinstance(value, str) and len(value) > max_chars:
            return f"{value[:max_chars]} [truncated {len(value) - max_chars} characters]"
        if isinstance(value, dict):
            return {k: cut(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cut(v) for v in value]
        return value

    def hook(tool: Tool, args: dict[str, Any], output: BaseModel, ctx: HookContext) -> BaseModel:
        return type(output).model_validate(cut(output.model_dump(mode="json")))

    return hook


def redact_pii(tool: Tool, args: dict[str, Any], output: BaseModel, ctx: HookContext) -> BaseModel:
    """Mask phone numbers and payment card numbers before the model or a log sees them."""

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return type(output).model_validate(walk(output.model_dump(mode="json")))


# A number run is digits joined by single separators, so "415-555-0134" and
# "(415) 555 0199" are one run while "PRO 7741-2209" stays an 8-digit run.
# A linear scan, not a regex: the text is untrusted email (see REGEX_POLICY).
_SEPARATORS = frozenset(" -.()+")


def redact_text(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if not (text[i].isdigit() or (text[i] in "(+" and i + 1 < n and text[i + 1].isdigit())):
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n:
            if text[j].isdigit():
                j += 1
                continue
            # Up to two separators may sit between digit groups, as in "(415) 555".
            k = j
            while k < n and k - j < 2 and text[k] in _SEPARATORS:
                k += 1
            if k > j and k < n and text[k].isdigit():
                j = k
                continue
            break
        run = text[i:j]
        out.append(_mask(run))
        i = j
    return "".join(out)


def _mask(run: str) -> str:
    digits = "".join(ch for ch in run if ch.isdigit())
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return f"[card ending {digits[-4:]}]"
    if len(digits) == 10 or (len(digits) == 11 and digits.startswith("1")):
        return "[phone]"
    return run


def _luhn(digits: str) -> bool:
    total = 0
    for index, ch in enumerate(reversed(digits)):
        d = int(ch)
        if index % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0
