.PHONY: help
help:  ## Show this help menu
	@echo "Usage: make [TARGET ...]"
	@echo ""
	@grep --no-filename -E '^[a-zA-Z_%-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "%-25s %s\n", $$1, $$2}'

VENV           = .venv
VENV_PYTHON    = $(VENV)/bin/python
SYSTEM_PYTHON  = $(shell which python3.13)
PYTHON         = $(wildcard $(VENV_PYTHON))

$(VENV_PYTHON):
	rm -rf $(VENV)
	$(SYSTEM_PYTHON) -m venv $(VENV)

.PHONY: venv
venv: $(VENV_PYTHON)  ## Create a Python virtual environment

.PHONY: deps
deps:  ## Install requirements in virtual environment
	$(PYTHON) -m pip install -r requirements.dev.txt

.PHONY: tests
tests:  ## Run unit tests
	$(PYTHON) -m pytest tests
