import json
from email import message_from_bytes
from pathlib import Path

from freight_agents.tms_orders.domain import Source, Tender
from freight_agents.tms_orders.fixtures import write_fixtures
from freight_agents.tms_orders.synth import generate


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_same_seed_writes_the_same_files(tmp_path: Path) -> None:
    write_fixtures(tmp_path / "a", seed=11)
    write_fixtures(tmp_path / "b", seed=11)
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")


def test_gold_lines_hold_every_tender_and_point_at_their_file(tmp_path: Path) -> None:
    write_fixtures(tmp_path, seed=11)
    lines = [json.loads(line) for line in (tmp_path / "gold.jsonl").read_text().splitlines()]
    cases = generate(seed=11)
    assert [g["id"] for g in lines] == [c.id for c in cases]
    for gold, case in zip(lines, cases, strict=True):
        assert Tender.model_validate(gold["tender"]) == case.tender
        assert gold["expected_rules"] == list(case.expected_rules)
        if case.tender.source == Source.EMAIL:
            assert (tmp_path / gold["file"]).exists()


def test_email_tenders_are_real_messages_with_the_tender_reference(tmp_path: Path) -> None:
    write_fixtures(tmp_path, seed=11)
    for case in generate(seed=11):
        if case.tender.source != Source.EMAIL:
            continue
        raw = (tmp_path / "email" / f"{case.id}.eml").read_bytes()
        message = message_from_bytes(raw)
        assert message["Message-ID"] == case.tender.reference
        assert message["From"].endswith(".example.com>")
        assert case.tender.order.tender_id in message["Subject"]


def test_edi_fixtures_parse_to_their_gold_tender(tmp_path: Path) -> None:
    from freight_agents.tms_orders.edi204 import parse_204

    write_fixtures(tmp_path, seed=11)
    for case in generate(seed=11):
        if case.tender.source == Source.EDI:
            text = (tmp_path / "edi" / f"{case.id}.edi").read_text()
            assert parse_204(text) == [case.tender]


def test_every_pdf_layout_states_every_field(tmp_path: Path) -> None:
    from freight_agents.integrations.documents import pdf_text

    write_fixtures(tmp_path, seed=11)
    layouts = set()
    for case in generate(seed=11):
        if case.tender.source != Source.PDF:
            continue
        layouts.add(case.style)
        text = pdf_text(tmp_path / "pdf" / f"{case.id}.pdf")
        order = case.tender.order
        for value in (order.tender_id, order.shipper_reference, f"{order.weight_lb:,}",
                      order.commodity):  # fmt: skip
            assert value in text, (case.id, value)
        for stop in order.stops:
            assert stop.party.zip in text
            assert stop.window_start.strftime("%m/%d/%Y") in text
            assert stop.window_end.strftime("%H:%M") in text
        if order.hazmat and order.hazmat.un_number:
            assert order.hazmat.un_number in text
    assert layouts == {0, 1, 2}


def test_the_location_master_is_written_with_the_fixtures(tmp_path: Path) -> None:
    from freight_agents.tms_orders.synth import locations

    write_fixtures(tmp_path, seed=11)
    rows = json.loads((tmp_path / "locations.json").read_text())
    assert {tuple(r) for r in rows} == locations(seed=11)
