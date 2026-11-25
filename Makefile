# Every target runs through uv, so the lockfile decides every version.
UV ?= uv
SRC_DIRS := $(wildcard packages/*/src apps/*/src services/*/src)
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
MYPYPATH := $(subst $(SPACE),:,$(SRC_DIRS))

.PHONY: setup check lint types test data eval demo purity audit record forecast

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

# Backtest every forecasting model and write the dated report (about 20 seconds).
forecast:
	$(UV) run --all-packages freight-forecast backtest

demo: data
	$(UV) run --all-packages python -m freight_agents.claims_intake.demo

purity:
	python3 tools/purity.py .
	python3 tools/check_links.py .

# Audit the locked third-party dependencies (workspace packages excluded).
audit:
	$(UV) export --all-packages --no-emit-workspace --format requirements-txt -q -o .audit-requirements.txt
	$(UV) tool run --python 3.12 pip-audit==2.9.0 -r .audit-requirements.txt --no-deps --disable-pip --progress-spinner off
	rm -f .audit-requirements.txt

# Spends money: records live model turns. Needs ANTHROPIC_API_KEY or an `ant auth login` profile.
# Example: make record ARGS="--limit 3 --max-usd 1"
record:
	$(UV) run --all-packages python -c "import sys; from freight_agents.claims_intake.evaluation import main; sys.exit(main(['--mode', 'record', *sys.argv[1:]]))" $(ARGS)
