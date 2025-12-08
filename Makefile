.PHONY: help venv build install install-dev clean test test-one repl lsp verify \
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
	@echo "  venv           - Create virtual environment with build tools"
	@echo "  build          - Build C extension in-place"
	@echo "  install-dev    - Install package in development mode (editable)"
	@echo ""
	@echo "Testing:"
	@echo "  test           - Run all .spork test files"
	@echo "  test-one       - Run a single test (usage: make test-one TEST=tests/test_pds.spork)"
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
	$(PIP) install build twine setuptools wheel numpy
	$(PIP) install -e .
	@echo "✓ Virtual environment ready"

venv: $(VENV)

build: $(VENV)
	@so_file=$$(ls spork/runtime/pds.cpython-*-*.so 2>/dev/null | head -1); \
	if [ -z "$$so_file" ] || [ spork/runtime/pds.c -nt "$$so_file" ]; then \
		echo "Building C extension..."; \
		$(PYTHON) setup.py build_ext --inplace 2>&1 | grep -v "toml section missing"; \
		if [ $$? -ne 0 ]; then \
			echo "✗ C extension build failed"; \
			exit 1; \
		fi; \
		echo "✓ C extension built"; \
	else \
		echo "C extension is up to date."; \
	fi

install-dev: $(VENV) build
	$(PIP) install -e .
	@echo "✓ Installed in development mode"

# ============================================================================
# Testing
# ============================================================================

test: build
	@echo "Running all tests..."
	@failed=0; \
	passed=0; \
	for test in tests/test_*.spork; do \
		echo ""; \
		echo "=== Running $$test ==="; \
		if $(PYTHON) -m spork "$$test"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
			echo "FAILED: $$test"; \
		fi; \
	done; \
	echo ""; \
	echo "=== Test Summary ==="; \
	echo "Passed: $$passed"; \
	echo "Failed: $$failed"; \
	if [ $$failed -gt 0 ]; then \
		echo "Some tests failed!"; \
		exit 1; \
	else \
		echo "All tests passed!"; \
	fi

test-one: build
	@if [ -z "$(TEST)" ]; then \
		echo "Usage: make test-one TEST=tests/test_pds.spork"; \
		exit 1; \
	fi
	@echo "Running $(TEST)..."
	$(PYTHON) -m spork "$(TEST)"

repl: build
	$(PYTHON) -m spork

lsp: build
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
	rm -rf spork/*.so
	rm -rf spork/runtime/*.so
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
