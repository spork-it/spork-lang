"""Discover declared and legacy Spork test files."""

from dataclasses import dataclass
from pathlib import Path

from spork.compiler.reader import read_str
from spork.project.build import discover_spork_files
from spork.runtime.types import Symbol


class TestDiscoveryError(Exception):
    """Raised when a source file cannot be inspected for test declarations."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Could not inspect {path}: {cause}")


@dataclass(frozen=True)
class DiscoveredTestFile:
    """A file selected by declared-test or legacy naming rules."""

    path: Path
    has_declarations: bool
    legacy: bool


def is_legacy_test_name(path: Path) -> bool:
    """Return whether a file follows a supported legacy test convention."""
    return path.name.startswith("test_") or path.stem.endswith("_test")


def has_deftest(path: Path) -> bool:
    """Return whether a file contains a direct top-level ``deftest`` form."""
    try:
        forms = read_str(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise TestDiscoveryError(path, exc) from exc

    return any(
        isinstance(form, list)
        and bool(form)
        and isinstance(form[0], Symbol)
        and form[0].name == "deftest"
        for form in forms
    )


def discover_test_files(
    source_roots: list[Path], test_roots: list[Path]
) -> list[DiscoveredTestFile]:
    """Discover project Spork tests in deterministic path order.

    Convention-named files are selected only from configured test roots.
    Top-level ``deftest`` declarations are selected from both source and test
    roots, which enables tests to live beside regular implementation code.
    """
    discovered: dict[Path, DiscoveredTestFile] = {}
    declaration_cache: dict[Path, bool] = {}

    def declarations(path: Path) -> bool:
        resolved = path.resolve()
        if resolved not in declaration_cache:
            declaration_cache[resolved] = has_deftest(resolved)
        return declaration_cache[resolved]

    for root in test_roots:
        if not root.is_dir():
            continue
        for path in discover_spork_files(root):
            resolved = path.resolve()
            declared = declarations(resolved)
            legacy = is_legacy_test_name(resolved) and not declared
            if declared or legacy:
                discovered[resolved] = DiscoveredTestFile(
                    path=resolved,
                    has_declarations=declared,
                    legacy=legacy,
                )

    for root in source_roots:
        if not root.is_dir():
            continue
        for path in discover_spork_files(root):
            resolved = path.resolve()
            declared = declarations(resolved)
            if not declared:
                continue
            existing = discovered.get(resolved)
            discovered[resolved] = DiscoveredTestFile(
                path=resolved,
                has_declarations=True,
                legacy=existing.legacy if existing is not None else False,
            )

    return [discovered[path] for path in sorted(discovered, key=str)]


__all__ = [
    "DiscoveredTestFile",
    "TestDiscoveryError",
    "discover_test_files",
    "has_deftest",
    "is_legacy_test_name",
]
