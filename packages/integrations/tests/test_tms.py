import json
from datetime import date
from pathlib import Path

from freight_agents.integrations.tms import FixtureTms

ROW = {
    "pro_number": "7741-2209",
    "bol_number": "BOL-55102",
    "carrier": "Example Freight Lines",
    "shipper": "Larkspur Home Goods",
    "consignee": "Harbor Street Furniture",
    "ship_date": "2026-11-02",
    "delivery_date": "2026-11-09",
    "commodity": "dining chairs",
    "declared_value_usd": 2400.0,
    "pieces": 12,
    "weight_lb": 640.0,
}


def test_fixture_tms_finds_by_pro_and_bol(tmp_path: Path) -> None:
    path = tmp_path / "tms.json"
    path.write_text(json.dumps([ROW]))
    tms = FixtureTms(path)
    shipment = tms.get_shipment("7741-2209")
    assert shipment is not None
    assert shipment.delivery_date == date(2026, 11, 9)
    assert tms.find_by_bol("bol-55102") == shipment
    assert tms.get_shipment("0000") is None
    assert tms.find_by_bol("nope") is None
