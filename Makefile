# Every target runs through uv, so the lockfile decides every version.
UV ?= uv
SRC_DIRS := $(wildcard packages/*/src apps/*/src)
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
MYPYPATH := $(subst $(SPACE),:,$(SRC_DIRS))

.PHONY: setup check lint types test

setup:
	$(UV) sync --all-packages

check: lint types test

lint:
	$(UV) run --all-packages ruff check .
	$(UV) run --all-packages ruff format --check .

types:
	MYPYPATH=$(MYPYPATH) $(UV) run --all-packages mypy -p freight_agents

test:
	$(UV) run --all-packages pytest
