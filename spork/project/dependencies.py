"""Edit project dependencies in a ``spork.it`` manifest."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from spork.compiler.reader import read_str, tokenize
from spork.project.config import PROJECT_FILENAME, ProjectConfig
from spork.runtime.types import Keyword, MapLiteral, VectorLiteral

DependencyAction = Literal["added", "updated", "unchanged", "removed", "missing"]


@dataclass(frozen=True)
class DependencyChange:
    """The result of one requested dependency edit."""

    dependency: str
    action: DependencyAction
    previous: Optional[str] = None


@dataclass
class _DependencyEntry:
    value: str
    start: Optional[int]
    end: Optional[int]
    line: int = 0
    col: int = 0
    original_value: Optional[str] = None
    removed: bool = False


@dataclass(frozen=True)
class _ManifestSyntax:
    manifest: MapLiteral
    dependencies: Optional[VectorLiteral]
    dependency_key: Optional[Keyword]


_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_NAME_DELIMITERS = frozenset("[<>=!~@; \t")


def _dependency_key(requirement: str) -> Optional[str]:
    """Return a normalized distribution name when one can be identified."""
    match = _NAME_PATTERN.match(requirement)
    if match is None:
        return None
    if (
        match.end() < len(requirement)
        and requirement[match.end()] not in _NAME_DELIMITERS
    ):
        return None
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _clean_dependencies(dependencies: list[str]) -> list[str]:
    cleaned = []
    for dependency in dependencies:
        dependency = dependency.strip()
        if not dependency:
            raise ValueError("Dependency specifications must not be empty")
        if any(ord(character) < 32 for character in dependency):
            raise ValueError(
                "Dependency specifications must not contain control characters"
            )
        cleaned.append(dependency)
    return cleaned


def _main_manifest_form(content: str) -> MapLiteral:
    parsed = read_str(content)
    forms = parsed if isinstance(parsed, list) else [parsed]
    for form in forms:
        if isinstance(form, MapLiteral):
            return form
    raise ValueError(f"{PROJECT_FILENAME} must contain a map as the main form")


def _manifest_syntax(content: str) -> _ManifestSyntax:
    manifest = _main_manifest_form(content)
    matches = [
        (key, value)
        for key, value in manifest.pairs
        if isinstance(key, Keyword) and key.name == "dependencies"
    ]
    if len(matches) > 1:
        raise ValueError("spork.it contains more than one :dependencies field")
    if not matches:
        return _ManifestSyntax(manifest, None, None)

    key, value = matches[0]
    if not isinstance(value, VectorLiteral) or not all(
        isinstance(item, str) for item in value.items
    ):
        raise ValueError(":dependencies must be a vector of strings")
    return _ManifestSyntax(manifest, value, key)


def _line_offsets(content: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(content):
        if character == "\n":
            offsets.append(index + 1)
    return offsets


def _offset(offsets: list[int], line: int, col: int) -> int:
    if line < 1 or line > len(offsets):
        raise ValueError("Invalid source location while editing spork.it")
    return offsets[line - 1] + col


def _string_end(content: str, start: int) -> int:
    index = start + 1
    while index < len(content):
        if content[index] == "\\":
            index += 2
        elif content[index] == '"':
            return index + 1
        else:
            index += 1
    raise ValueError("Unterminated dependency string in spork.it")


def _dependency_entries(
    content: str, syntax: _ManifestSyntax, offsets: list[int]
) -> list[_DependencyEntry]:
    vector = syntax.dependencies
    if vector is None:
        return []

    vector_start = _offset(offsets, vector.line, vector.col)
    vector_end = _offset(offsets, vector.end_line, vector.end_col)
    string_tokens = []
    for token in tokenize(content):
        if not (isinstance(token.value, tuple) and token.value[0] == "STRING"):
            continue
        start = _offset(offsets, token.line, token.col)
        if vector_start < start < vector_end:
            string_tokens.append((token, start))

    if len(string_tokens) != len(vector.items):
        raise ValueError("Could not locate every dependency string in spork.it")

    entries = []
    for expected, (token, start) in zip(vector.items, string_tokens):
        if token.value[1] != expected:
            raise ValueError("Dependency source does not match parsed spork.it")
        entries.append(
            _DependencyEntry(
                value=expected,
                original_value=expected,
                start=start,
                end=_string_end(content, start),
                line=token.line,
                col=token.col,
            )
        )
    return entries


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _newline(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def _append_to_vector(
    content: str,
    syntax: _ManifestSyntax,
    offsets: list[int],
    entries: list[_DependencyEntry],
    values: list[str],
) -> tuple[int, str]:
    vector = syntax.dependencies
    assert vector is not None
    close = _offset(offsets, vector.end_line, vector.end_col) - 1
    rendered = [_quote(value) for value in values]
    vector_start = _offset(offsets, vector.line, vector.col)
    vector_content = content[vector_start + 1 : close]

    if "\n" not in vector_content:
        has_existing = any(
            not entry.removed for entry in entries if entry.start is not None
        )
        prefix = " " if has_existing else ""
        return close, prefix + " ".join(rendered)

    line_start = content.rfind("\n", 0, close) + 1
    before_close = content[line_start:close]
    original_entries = [entry for entry in entries if entry.start is not None]
    if original_entries:
        item_col = original_entries[-1].col
    elif syntax.dependency_key is not None:
        item_col = syntax.dependency_key.col + 1
    else:
        item_col = vector.col + 1
    indent = " " * item_col
    newline = _newline(content)

    if before_close.strip() == "":
        text = "".join(f"{indent}{item}{newline}" for item in rendered)
        return line_start, text
    return close, "".join(f"{newline}{indent}{item}" for item in rendered)


def _insert_dependencies_field(
    content: str,
    syntax: _ManifestSyntax,
    offsets: list[int],
    values: list[str],
) -> tuple[int, str]:
    manifest = syntax.manifest
    close = _offset(offsets, manifest.end_line, manifest.end_col) - 1
    rendered = " ".join(_quote(value) for value in values)
    field = f":dependencies [{rendered}]"
    manifest_start = _offset(offsets, manifest.line, manifest.col)

    if "\n" not in content[manifest_start:close]:
        return close, f" {field}"

    key_columns = [
        key.col for key, _ in manifest.pairs if isinstance(key, Keyword)
    ]
    indent = " " * (key_columns[0] if key_columns else manifest.col + 1)
    newline = _newline(content)
    line_start = content.rfind("\n", 0, close) + 1
    if content[line_start:close].strip() == "":
        return line_start, f"{indent}{field}{newline}"
    return close, f"{newline}{indent}{field}"


def _apply_patches(content: str, patches: list[tuple[int, int, str]]) -> str:
    for start, end, replacement in sorted(patches, reverse=True):
        content = content[:start] + replacement + content[end:]
    return content


def _write_manifest(path: Path, content: str) -> None:
    """Atomically replace a manifest while retaining its permission bits."""
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _read_editor_state(
    manifest_path: Path,
) -> tuple[str, _ManifestSyntax, list[int], list[_DependencyEntry]]:
    # Validate the whole project config before attempting a source-level edit.
    ProjectConfig.load(str(manifest_path))
    with manifest_path.open(encoding="utf-8", newline="") as manifest_file:
        content = manifest_file.read()
    syntax = _manifest_syntax(content)
    offsets = _line_offsets(content)
    entries = _dependency_entries(content, syntax, offsets)
    return content, syntax, offsets, entries


def add_dependencies(
    manifest_path: str | Path, dependencies: list[str]
) -> list[DependencyChange]:
    """Add or update runtime dependencies in a project manifest."""
    path = Path(manifest_path).resolve()
    requested_dependencies = _clean_dependencies(dependencies)
    content, syntax, offsets, entries = _read_editor_state(path)
    changes: list[DependencyChange] = []

    for dependency in requested_dependencies:
        key = _dependency_key(dependency)
        matches = [
            entry
            for entry in entries
            if not entry.removed
            and (
                _dependency_key(entry.value) == key
                if key is not None
                else entry.value == dependency
            )
        ]
        if not matches:
            entries.append(_DependencyEntry(dependency, None, None))
            changes.append(DependencyChange(dependency, "added"))
            continue

        previous = matches[0].value
        duplicate_matches = matches[1:]
        for duplicate in duplicate_matches:
            duplicate.removed = True
        if previous == dependency and not duplicate_matches:
            changes.append(DependencyChange(dependency, "unchanged", previous))
            continue

        matches[0].value = dependency
        changes.append(DependencyChange(dependency, "updated", previous))

    patches: list[tuple[int, int, str]] = []
    for entry in entries:
        if entry.start is None or entry.end is None:
            continue
        if entry.removed:
            patches.append((entry.start, entry.end, ""))
        elif entry.value != entry.original_value:
            patches.append((entry.start, entry.end, _quote(entry.value)))

    additions = [
        entry.value for entry in entries if entry.start is None and not entry.removed
    ]
    if additions:
        if syntax.dependencies is None:
            start, replacement = _insert_dependencies_field(
                content, syntax, offsets, additions
            )
        else:
            start, replacement = _append_to_vector(
                content, syntax, offsets, entries, additions
            )
        patches.append((start, start, replacement))

    if patches:
        _write_manifest(path, _apply_patches(content, patches))
    return changes


def remove_dependencies(
    manifest_path: str | Path, dependencies: list[str]
) -> list[DependencyChange]:
    """Remove runtime dependencies by distribution name or exact specification."""
    path = Path(manifest_path).resolve()
    requested_dependencies = _clean_dependencies(dependencies)
    content, _syntax, _offsets, entries = _read_editor_state(path)
    changes: list[DependencyChange] = []

    for dependency in requested_dependencies:
        key = _dependency_key(dependency)
        matches = [
            entry
            for entry in entries
            if not entry.removed
            and (
                _dependency_key(entry.value) == key
                if key is not None
                else entry.value == dependency
            )
        ]
        if not matches:
            changes.append(DependencyChange(dependency, "missing"))
            continue
        for entry in matches:
            entry.removed = True
        changes.append(DependencyChange(dependency, "removed", matches[0].value))

    patches = [
        (entry.start, entry.end, "")
        for entry in entries
        if entry.removed and entry.start is not None and entry.end is not None
    ]
    if patches:
        _write_manifest(path, _apply_patches(content, patches))
    return changes
