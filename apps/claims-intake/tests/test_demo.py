import io
from contextlib import redirect_stdout
from pathlib import Path

from freight_agents.claims_intake.demo import main
from freight_agents.claims_intake.workflow import Stores


def test_demo_processes_the_inbox_without_a_model_key(tmp_path: Path) -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        assert main(["--state", str(tmp_path / "demo")]) == 0
    stores = Stores.at(tmp_path / "demo")
    assert len(stores.engine.store.case_ids()) == 36
    assert len(stores.approvals.pending()) == 8
    text = out.getvalue()
    assert "ready_to_file" in text
    assert "freight-claims --state" in text
