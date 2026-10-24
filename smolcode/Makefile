# smolcode Makefile (Phase 8, decision 0043: OS-aware).
#
# The venv layout differs by platform:
#   Windows -> .venv/Scripts/python.exe
#   POSIX   -> .venv/bin/python
# Every target calls the resolved interpreter, so the same file works on
# Linux/macOS and on Windows (Git Bash / MSYS make). On Windows the PowerShell
# scripts remain the primary interface (scripts/install.ps1, quality.ps1); make
# is optional there.
#
# Do not rely on activation: a target must not require a previous `activate`.

.PHONY: install quality style test run docker-images clean help

PYTHON ?= python
VENV := .venv

ifeq ($(OS),Windows_NT)
  VENV_BIN := $(VENV)/Scripts
  EXE := .exe
else
  VENV_BIN := $(VENV)/bin
  EXE :=
endif

VENV_PYTHON := $(VENV_BIN)/python$(EXE)
VENV_RUFF := $(VENV_BIN)/ruff$(EXE)
VENV_PYTEST := $(VENV_BIN)/pytest$(EXE)

check_dirs := src

help:
	@echo "install       create .venv and install -e .[dev]"
	@echo "quality       ruff check + ruff format --check"
	@echo "style         ruff check --fix + ruff format"
	@echo "test          pytest with coverage (fail under 80%)"
	@echo "run           run the CLI: make run ARGS='--tier restricted "task"'"
	@echo "docker-images build/refresh the three tier sandbox images"
	@echo "clean         remove build/cache artefacts"

# Create venv + install package + dev extras. The final check is a portable
# Python import instead of the Windows-only `>nul && echo OK` idiom.
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"
	$(VENV_PYTHON) -c "import smolagents; print('OK smolagents ' + smolagents.__version__)"

# Run linter + format check (matches CI / scripts/quality.ps1)
quality:
	$(VENV_RUFF) check $(check_dirs)
	$(VENV_RUFF) format --check $(check_dirs)

# Auto-fix lint + format
style:
	$(VENV_RUFF) check $(check_dirs) --fix
	$(VENV_RUFF) format $(check_dirs)

# Run the test suite
test:
	$(VENV_PYTEST) src/smolcode/tests/ --cov=smolcode --cov-report=term --cov-fail-under=80

# Pass-through to the venv python so the user doesn't need to remember the path
run:
	$(VENV_PYTHON) -m smolcode $(ARGS)

# Build/refresh the three tier sandbox images (Phase 1, C2).
# Same code path the CLI/web boot uses (smolcode.images.ensure_tier_images).
docker-images:
	$(VENV_PYTHON) -m smolcode.images ensure

# Remove build / cache artefacts. Portable one-liner (no rm -rf, no cmd `nul`):
# the historical target mixed POSIX and Windows constructs and failed on both.
clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('build', 'dist', '.pytest_cache', '.ruff_cache')]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
