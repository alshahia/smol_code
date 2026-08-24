.PHONY: install quality style test run clean

PYTHON ?= python
VENV := .venv
ACT := . $(VENV)/bin/activate  # POSIX
ACT_WIN := $(VENV)/Scripts/activate  # Windows

check_dirs := src

# Create venv + install package + editable smolagents
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/Scripts/python -m pip install --upgrade pip
	$(VENV)/Scripts/python -m pip install -e ".[dev]"
	$(VENV)/Scripts/python -m pip show smolagents >nul && echo OK smolagents installed

# Run linter + format check (matches smolagents CI)
quality:
	$(VENV)/Scripts/ruff check $(check_dirs)
	$(VENV)/Scripts/ruff format --check $(check_dirs)

# Auto-fix lint + format
style:
	$(VENV)/Scripts/ruff check $(check_dirs) --fix
	$(VENV)/Scripts/ruff format $(check_dirs)

# Run the test suite
test:
	$(VENV)/Scripts/pytest src/smolcode/tests/

# Pass-through to the venv python so the user doesn't need to remember the path
run:
	$(VENV)/Scripts/python -m smolcode $(ARGS)

# Remove build / cache artefacts
clean:
	rm -rf build dist .pytest_cache .ruff_cache **/__pycache__
