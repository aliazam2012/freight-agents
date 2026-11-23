"""Send spans somewhere a person can read them: a JSON Lines file.

Off by default. ``configure_tracing(path)`` turns it on for the whole process;
any OpenTelemetry collector can be wired the same way through the SDK instead.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


class JsonLinesSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.path.open("a", encoding="utf-8") as fh:
            for s in spans:
                context, parent = s.get_span_context(), s.parent
                start, end = s.start_time or 0, s.end_time or 0
                row = {
                    "name": s.name,
                    "trace_id": f"{context.trace_id:032x}" if context else None,
                    "span_id": f"{context.span_id:016x}" if context else None,
                    "parent_id": f"{parent.span_id:016x}" if parent else None,
                    "duration_ms": round((end - start) / 1_000_000, 3),
                    "attributes": dict(s.attributes or {}),
                }
                fh.write(json.dumps(row, default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def configure_tracing(path: Path) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(JsonLinesSpanExporter(path)))
    trace.set_tracer_provider(provider)
    return provider
