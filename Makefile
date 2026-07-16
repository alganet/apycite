# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

.PHONY: check test live coverage lint format dist publish clean help

# =============================================================================
# VERIFICATION
# =============================================================================

check: lint coverage  ## Run all verification — exit 1 on any failure
	@echo ""

# =============================================================================
# DEVELOPMENT
# =============================================================================

test:  ## Run unit tests (no network)
	python -m pytest tests/ -v -m "not live"

live:  ## Run the tests that read real documents over the network
	python -m pytest tests/ -v -m live

coverage:  ## Run tests with coverage report (library code only)
	python -m slipcover --source apycite -m pytest tests/ -q -m "not live"

lint:  ## Run ruff (lint) and mypy (type checking)
	python -m ruff check apycite/ tests/
	python -m mypy apycite/

format:  ## Auto-format and fix lint issues with ruff
	python -m ruff format apycite/ tests/
	python -m ruff check --fix apycite/ tests/

dist:  ## Build source and wheel distributions
	python -m build

publish: dist  ## Build and upload to PyPI
	twine upload dist/*

clean:  ## Remove generated files
	rm -rf .pytest_cache __pycache__ apycite/__pycache__ .mypy_cache dist build *.egg-info

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
