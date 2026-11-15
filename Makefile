SRC = sqlitey tests

.PHONY: help
help:  ## Show this help menu
	@echo "Usage: make [TARGET ...]"
	@echo ""
	@grep --no-filename -E '^[a-zA-Z_%-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "%-25s %s\n", $$1, $$2}'

.PHONY: deps
deps:  ## Install requirements in virtual environment
	uv sync

.PHONY: tests
tests:  ## Run unit tests
	uv run pytest --cov=sqlitey --cov-report term-missing tests

.PHONY: mypy
mypy:  ## Run mypy
	uv run mypy sqlitey

.PHONY: ruff
ruff:  ## Run ruff linter
	uv run ruff check $(SRC)

.PHONY: fmt
fmt:  ## Format code with ruff
	uv run ruff format $(SRC)

.PHONY: release
release:  ## Release to PyPI
	rm -rf dist
	uv build
	uv publish
