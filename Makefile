# One target per CI step; `make check` runs them all.
RUFF ?= uvx ruff@0.17.2
PYTHON ?= python3

.PHONY: check lint test
check: lint test

lint:
	$(RUFF) check .
	$(RUFF) format --check .

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
