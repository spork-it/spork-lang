"""Discover Spork files containing declared tests."""

from dataclasses import dataclass
from pathlib import Path

from spork.compiler.reader import read_str
from spork.project.build import discover_spork_files
from spork.runtime.types import Decorated, Symbol


class TestDiscoveryError(Exception):
    """Raised when a source file cannot be inspected for test declarations."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Could not inspect {path}: {cause}")


@dataclass(frozen=True)
class DiscoveredTest:
    """A top-level test declaration found without executing its source file."""

    name: str
    namespace: str | None = None

    @property
    def qualified_name(self) -> str:
        """Return the namespace-qualified test name."""
        if self.namespace:
            return f"{self.namespace}/{self.name}"
        return self.name


@dataclass(frozen=True)
class DiscoveredTestFile:
    """A Spork file containing at least one top-level test declaration."""

    path: Path
    tests: tuple[DiscoveredTest, ...] = ()


def _inspect_file(path: Path) -> tuple[bool, tuple[DiscoveredTest, ...]]:
    try:
        forms = read_str(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise TestDiscoveryError(path, exc) from exc

    namespace = None
    declared = False
    tests: list[DiscoveredTest] = []
    for form in forms:
        if not (
            isinstance(form, list)
            and bool(form)
            and isinstance(form[0], Symbol)
        ):
            continue

        if form[0].name == "ns":
            if len(form) > 1 and isinstance(form[1], Symbol):
                namespace = form[1].name
            continue

        if form[0].name != "deftest":
            continue

        declared = True
        index = 1
        while index < len(form) and isinstance(form[index], Decorated):
            index += 1
        if index < len(form) and isinstance(form[index], Symbol):
            tests.append(DiscoveredTest(form[index].name, namespace))

    return declared, tuple(tests)


def has_deftest(path: Path) -> bool:
    """Return whether a file contains a direct top-level ``deftest`` form."""
    declared, _ = _inspect_file(path)
    return declared


def discover_test_files(
    source_roots: list[Path], test_roots: list[Path]
) -> list[DiscoveredTestFile]:
    """Discover declared tests below roots or in explicitly supplied files."""
    discovered: dict[Path, DiscoveredTestFile] = {}
    inspected: dict[Path, tuple[bool, tuple[DiscoveredTest, ...]]] = {}

    for root in [*test_roots, *source_roots]:
        if root.is_file():
            candidates = [root] if root.suffix == ".spork" else []
        elif root.is_dir():
            candidates = discover_spork_files(root)
        else:
            continue

        for path in candidates:
            resolved = path.resolve()
            inspection = inspected.get(resolved)
            if inspection is None:
                inspection = _inspect_file(resolved)
                inspected[resolved] = inspection
            declared, tests = inspection
            if declared:
                discovered[resolved] = DiscoveredTestFile(resolved, tests)

    return [discovered[path] for path in sorted(discovered, key=str)]


__all__ = [
    "DiscoveredTest",
    "DiscoveredTestFile",
    "TestDiscoveryError",
    "discover_test_files",
    "has_deftest",
]
