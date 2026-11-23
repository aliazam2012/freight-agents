from freight_agents.claims_intake.evaluation import main


def test_the_reference_suite_passes_the_gate() -> None:
    assert main(["--mode", "reference"]) == 0
