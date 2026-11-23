import json
import subprocess
import sys
from pathlib import Path

from freight_agents.evals.runner import CaseRun, GoldenCase, run_suite, write_report

from .conftest import FIELDS, email, extraction, triage


def test_the_meter_counts_tokens_and_does_not_price_a_scripted_model(make_intake) -> None:  # type: ignore[no-untyped-def]
    intake = make_intake(triage() + extraction(FIELDS))
    intake.process(email("4 chairs broken, claiming $800, PRO 7741-2209."))
    usage = intake.meter.by_model["scripted"]
    assert (usage.input_tokens, usage.output_tokens) == (500, 100)
    assert intake.meter.unpriced == {"scripted"}


def test_the_demo_writes_a_trace_only_when_asked(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    demo = [sys.executable, "-m", "freight_agents.claims_intake.demo", "--state"]
    subprocess.run([*demo, str(tmp_path / "a")], check=True, capture_output=True)
    assert not trace.exists()
    subprocess.run(
        [*demo, str(tmp_path / "b"), "--trace", str(trace)], check=True, capture_output=True
    )
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    operations = {r["attributes"].get("gen_ai.operation.name") for r in rows}
    assert {"invoke_agent", "chat", "execute_tool"} <= operations


def test_the_report_shows_tokens_cost_and_latency(tmp_path: Path) -> None:
    case = GoldenCase(id="c1", email="x.eml", tags=["claim"], expected={"state": "s"}, reference=[])
    run = CaseRun(
        state="s", fields=None, sends_executed=0, outsider_sends=0, tokens=1234, latency_s=0.5
    )
    result = run_suite([case], lambda c: run, mode="reference", model="reference")
    assert result.metrics["latency_p95_s"] == 0.5
    from datetime import date

    text = write_report(result, tmp_path, date(2026, 11, 22), failures=[]).read_text()
    assert (
        "| Case | Expected state | State | Fields | Outsider sends | Tokens | Cost | Seconds |"
        in text
    )
    assert "| c1 | s | s | 0/0 | 0 | 1234 | not priced | 0.50 |" in text
    assert "Tokens: 1234" in text
