import json
from pathlib import Path

from freight_agents.telemetry.export import JsonLinesSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


def test_spans_are_written_as_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(JsonLinesSpanExporter(path)))
    tracer = provider.get_tracer("test")
    with (
        tracer.start_as_current_span("outer"),
        tracer.start_as_current_span("inner", attributes={"gen_ai.operation.name": "chat"}),
    ):
        pass
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["name"] for r in rows] == ["inner", "outer"]
    inner, outer = rows
    assert inner["trace_id"] == outer["trace_id"]
    assert inner["parent_id"] == outer["span_id"]
    assert inner["attributes"] == {"gen_ai.operation.name": "chat"}
    assert inner["duration_ms"] >= 0
