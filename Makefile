# Every target runs through uv, so the lockfile decides every version.
UV ?= uv
SRC_DIRS := $(wildcard packages/*/src apps/*/src)
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
MYPYPATH := $(subst $(SPACE),:,$(SRC_DIRS))

.PHONY: setup check lint types test data eval

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

eval:
	$(UV) run --all-packages python -c "import sys; from freight_agents.claims_intake.evaluation import main; sys.exit(main(sys.argv[1:]))" $(ARGS)
