.PHONY: help venv install-dev clean test test-one verify-docs repl lsp \
        dist sdist wheel upload-test upload check-dist \
        clean-build clean-pyc clean-venv clean-all \
        pipx-install pipx-uninstall

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
BUILD := $(VENV)/bin/python -m build
TWINE := $(VENV)/bin/twine

help:
	@echo "Spork - Makefile targets"
	@echo ""
	@echo "Setup:"
	@echo "  venv           - Create the development environment"
	@echo "  install-dev    - Install Spork and development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  test           - Run all .spork test files"
	@echo "  test-one       - Run a single test (usage: make test-one TEST=tests/test_pds.spork)"
	@echo "  verify-docs    - Execute documentation examples"
	@echo "  repl           - Start the Spork REPL"
	@echo "  lsp            - Start the Language Server Protocol server"
	@echo ""
	@echo "Packaging:"
	@echo "  dist           - Build source and wheel distributions"
	@echo "  sdist          - Build source distribution only"
	@echo "  wheel          - Build wheel distribution only"
	@echo "  check-dist     - Verify distribution with twine"
	@echo "  upload-test    - Upload to TestPyPI"
	@echo "  upload         - Upload to PyPI"
	@echo ""
	@echo "pipx:"
	@echo "  pipx-install   - Install spork globally via pipx (from local build)"
	@echo "  pipx-uninstall - Uninstall spork from pipx"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean          - Remove build artifacts and caches"
	@echo "  clean-venv     - Remove virtual environment"
	@echo "  clean-all      - Remove everything (venv, build, caches)"

# ============================================================================
# Setup
# ============================================================================

$(VENV):
	@echo "Creating virtual environment..."
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo "✓ Virtual environment ready"

venv: $(VENV)

install-dev: $(VENV)
	$(PIP) install -e ".[dev]"
	@echo "✓ Installed in development mode"

# ============================================================================
# Testing
# ============================================================================

test: $(VENV)
	@$(PYTHON) tools/run_spork_tests.py

verify-docs: $(VENV)
	@$(PYTHON) tools/verify_docs.py

test-one: $(VENV)
	@if [ -z "$(TEST)" ]; then \
		echo "Usage: make test-one TEST=tests/test_pds.spork"; \
		exit 1; \
	fi
	@$(PYTHON) tools/run_spork_tests.py "$(TEST)"

repl: $(VENV)
	$(PYTHON) -m spork

lsp: $(VENV)
	$(PYTHON) -m spork lsp

# ============================================================================
# Packaging
# ============================================================================

dist: $(VENV) clean-build
	@echo "Building distributions..."
	$(BUILD)
	@echo ""
	@echo "✓ Distributions created:"
	@ls -lh dist/

sdist: $(VENV) clean-build
	$(BUILD) --sdist
	@echo ""
	@echo "✓ Source distribution created:"
	@ls -lh dist/*.tar.gz

wheel: $(VENV) clean-build
	$(BUILD) --wheel
	@echo ""
	@echo "✓ Wheel created:"
	@ls -lh dist/*.whl

check-dist: dist
	$(TWINE) check dist/*

upload-test: check-dist
	$(TWINE) upload --repository testpypi dist/*

upload: check-dist
	$(TWINE) upload dist/*

# ============================================================================
# pipx
# ============================================================================

pipx-install: dist
	@echo "Installing spork via pipx..."
	@wheel=$$(ls dist/*.whl | head -1); \
	if [ -z "$$wheel" ]; then \
		echo "Error: No wheel found in dist/"; \
		exit 1; \
	fi; \
	pipx install "$$wheel" --force
	@echo ""
	@echo "✓ Spork installed via pipx"
	@echo "  Run 'spork --help' to get started"

pipx-uninstall:
	pipx uninstall spork-lang || true
	@echo "✓ Spork uninstalled from pipx"

# ============================================================================
# Cleanup
# ============================================================================

clean-build:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf spork_lang.egg-info/
	# Remove artifacts left by pre-spork-pds versions of the repository.
	rm -rf spork/*.so
	find . -name '*.o' -delete 2>/dev/null || true

clean-pyc:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type f -name '*.pyo' -delete 2>/dev/null || true

clean-venv:
	rm -rf $(VENV)
	@echo "✓ Virtual environment removed"

clean: clean-build clean-pyc

clean-all: clean clean-venv
	rm -rf .eggs/
	@echo "✓ All artifacts removed"
