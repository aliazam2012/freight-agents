from freight_agents.llm import Usage
from freight_agents.telemetry.spans import model_attrs, span, tool_attrs
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_a_span_carries_genai_attributes(spans: InMemorySpanExporter) -> None:
    usage = Usage(input_tokens=120, output_tokens=30)
    with span("chat claude-opus-5-5", model_attrs("claude-opus-5-5", usage)):
        pass
    (only,) = spans.get_finished_spans()
    assert only.name == "chat claude-opus-5-5"
    assert only.attributes is not None
    assert only.attributes["gen_ai.operation.name"] == "chat"
    assert only.attributes["gen_ai.request.model"] == "claude-opus-5-5"
    assert only.attributes["gen_ai.usage.input_tokens"] == 120
    assert only.attributes["gen_ai.usage.output_tokens"] == 30


def test_nested_spans_share_a_trace(spans: InMemorySpanExporter) -> None:
    with span("invoke_agent claims"), span("execute_tool lookup", tool_attrs("lookup", "ok")):
        pass
    inner, outer = spans.get_finished_spans()
    assert inner.context is not None
    assert outer.context is not None
    assert inner.context.trace_id == outer.context.trace_id
    assert inner.parent is not None
    assert inner.parent.span_id == outer.context.span_id
    assert inner.attributes is not None
    assert inner.attributes["gen_ai.tool.name"] == "lookup"
    assert inner.attributes["freight_agents.tool.status"] == "ok"
