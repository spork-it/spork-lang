"""Discover Spork files containing declared tests."""

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
    """A Spork file containing at least one top-level test declaration."""

    path: Path


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
    """Discover declared tests below source and test roots in path order."""
    discovered: set[Path] = set()
    inspected: dict[Path, bool] = {}

    for root in [*test_roots, *source_roots]:
        if not root.is_dir():
            continue
        for path in discover_spork_files(root):
            resolved = path.resolve()
            declared = inspected.get(resolved)
            if declared is None:
                declared = has_deftest(resolved)
                inspected[resolved] = declared
            if declared:
                discovered.add(resolved)

    return [DiscoveredTestFile(path) for path in sorted(discovered, key=str)]


__all__ = [
    "DiscoveredTestFile",
    "TestDiscoveryError",
    "discover_test_files",
    "has_deftest",
]
