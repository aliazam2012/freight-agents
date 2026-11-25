# Every target runs through uv, so the lockfile decides every version.
UV ?= uv
SRC_DIRS := $(wildcard packages/*/src apps/*/src services/*/src)
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
MYPYPATH := $(subst $(SPACE),:,$(SRC_DIRS))

.PHONY: setup check lint types test data eval eval-recorded demo purity audit forecast

setup:
	$(UV) sync --all-packages

check: lint types test

lint:
	$(UV) run --all-packages ruff check .
	$(UV) run --all-packages ruff format --check .

types:
	# Every package directory by path: `-p freight_agents` sees only the first
	# directory of a namespace package spread over several source roots.
	MYPYPATH=$(MYPYPATH) $(UV) run --all-packages mypy $(addsuffix /freight_agents,$(SRC_DIRS))

test:
	$(UV) run --all-packages pytest

data:
	$(UV) run --all-packages python data/generate_claims.py
	$(UV) run --all-packages python data/generate_tenders.py

eval:
	$(UV) run --all-packages python -c "import sys; from freight_agents.claims_intake.evaluation import main; sys.exit(main(sys.argv[1:]))" $(ARGS)
	$(UV) run --all-packages freight-forecast eval --reports var/forecast/eval-reports
	$(UV) run --all-packages freight-orders eval --reports var/orders/eval-reports
	$(UV) run --all-packages freight-filing eval --reports var/filing/eval-reports
	$(UV) run --all-packages freight-incidents eval --reports var/incidents/eval-reports
	$(UV) run --all-packages freight-damage eval --reports var/damage/eval-reports

# Grade every app on its recorded cassettes; dated recorded reports go beside the reference ones.
eval-recorded:
	$(UV) run --all-packages python -c "import sys; from freight_agents.claims_intake.evaluation import main; sys.exit(main(['--mode', 'recorded', '--report']))"
	$(UV) run --all-packages freight-forecast eval --mode recorded
	$(UV) run --all-packages freight-orders eval --mode recorded
	$(UV) run --all-packages freight-filing eval --mode recorded
	$(UV) run --all-packages freight-incidents eval --mode recorded
	$(UV) run --all-packages freight-damage eval --mode recorded

# Backtest every forecasting model and write the dated report (about 20 seconds).
forecast:
	$(UV) run --all-packages freight-forecast backtest

demo: data
	$(UV) run --all-packages python -m freight_agents.claims_intake.demo

purity:
	$(UV) run --all-packages freight-purity .
	$(UV) run --all-packages freight-links .

# Audit the locked third-party dependencies (workspace packages excluded).
audit:
	$(UV) export --all-packages --no-emit-workspace --format requirements-txt -q -o .audit-requirements.txt
	$(UV) tool run --python 3.12 pip-audit==2.9.0 -r .audit-requirements.txt --no-deps --disable-pip --progress-spinner off
	rm -f .audit-requirements.txt

# Recording a real model spends money and happens per app: see docs/RUNBOOK-release.md.
