import json
from pathlib import Path

import pytest
from freight_agents.tms_orders.evaluation import FLOORS, run_reference, write_report
from freight_agents.tms_orders.fixtures import write_fixtures
from freight_agents.tms_orders.redteam import ATTACKER_STREET
from freight_agents.tms_orders.workflow import load_locations, reference_models, scripted_draft


@pytest.fixture(scope="module")
def inbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tenders")
    write_fixtures(root)
    return root


def test_the_reference_run_passes_the_gate(inbox: Path, tmp_path: Path) -> None:
    result = run_reference(inbox)
    assert result.failures(FLOORS) == []
    assert result.metrics["cases"] == 36
    assert result.metrics["redteam_cases"] == 6
    assert result.metrics["duplicate_orders"] == 0
    path = write_report(result, tmp_path, "2026-11-24")
    text = path.read_text()
    assert "reference mode" in text
    assert json.loads((tmp_path / "latest.json").read_text())["metrics"] == result.metrics


def test_a_wrong_field_lowers_that_input_types_accuracy(inbox: Path) -> None:
    from freight_agents.tms_orders.domain import Tender
    from freight_agents.tms_orders.extract import draft_of

    gold = {json.loads(line)["file"]: json.loads(line)
            for line in (inbox / "gold.jsonl").read_text().splitlines()}  # fmt: skip
    normal = reference_models(inbox / "gold.jsonl")
    target = next(f for f in gold if f.startswith("email/") and gold[f]["kind"] == "valid")
    wrong = draft_of(Tender.model_validate(gold[target]["tender"]))
    wrong["pieces"] += 1

    def models(path: Path):  # type: ignore[no-untyped-def]
        return scripted_draft(wrong) if path.name == Path(target).name else normal(path)

    result = run_reference(inbox, models=models)
    assert result.metrics["field_accuracy_email"] < 1.0
    assert result.metrics["field_accuracy_edi"] == 1.0
    assert result.failures(FLOORS)


def test_a_missing_guard_shows_up_as_a_failed_injection(inbox: Path) -> None:
    known = load_locations(inbox / "locations.json")
    redteam = [json.loads(line) for line in (inbox / "redteam.jsonl").read_text().splitlines()]
    for row in redteam:
        if row["attack"] == "redirect":
            stop = row["tender"]["order"]["stops"][-1]["party"]
            known.add((" ".join(stop["name"].lower().split()), ATTACKER_STREET.lower(),
                       stop["zip"][:5]))  # fmt: skip
    result = run_reference(inbox, locations=known)
    assert result.metrics["injection_resisted"] < 1.0
