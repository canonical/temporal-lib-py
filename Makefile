# Makefile to help automate tasks

# The name of the python package/project
PY_PACKAGE := temporallib


# Paths to venv executables
POETRY := poetry
PY := python3
PYTEST := pytest
ISORT := isort
BLACK := black

.PHONY: fmt
fmt: ## Reformat code for linter
	$(POETRY) run $(ISORT) $(PY_PACKAGE) tests
	$(POETRY) run $(BLACK) $(PY_PACKAGE) tests


.PHONY: test
test: ## Run tests
	$(POETRY) run $(PY) -m $(PYTEST) tests