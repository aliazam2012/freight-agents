"""Write the made-up load tenders and their gold orders to data/tenders/.

Run: uv run --all-packages python data/generate_tenders.py
"""

from __future__ import annotations

from pathlib import Path

from freight_agents.tms_orders.fixtures import write_fixtures

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    cases = write_fixtures(ROOT / "data" / "tenders")
    print(f"{len(cases)} tenders written to data/tenders/")
