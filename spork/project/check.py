"""Project-wide static checks for Spork source files.

The checker builds a reusable index of project namespaces, definitions, and
imports before compiling each source file.  This lets it report project
structure errors at the declaration that caused them instead of relying only
on a later Python compiler exception.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from spork.compiler.reader import read_str
from spork.project.build import discover_spork_files
from spork.project.config import ProjectConfig
from spork.runtime.types import (
    Decorated,
    Keyword,
    MapLiteral,
    Symbol,
    VectorLiteral,
    normalize_name,
)

# Diagnostic codes are part of the machine-readable ``spork check`` interface.
PARSE_ERROR = "SPK001"
MISSING_NAMESPACE = "SPK002"
NAMESPACE_MISMATCH = "SPK003"
DUPLICATE_NAMESPACE = "SPK004"
INVALID_NAMESPACE_CLAUSE = "SPK005"
UNRESOLVED_NAMESPACE = "SPK006"
MISSING_EXPORT = "SPK007"
UNRESOLVED_PYTHON_MODULE = "SPK008"
COMPILE_ERROR = "SPK009"
INVALID_MAIN = "SPK010"
INVALID_API = "SPK011"
MISSING_SOURCE_ROOT = "SPK012"
NO_SOURCE_FILES = "SPK013"


@dataclass(frozen=True)
class SourceRange:
    """A 1-based line and 0-based column source range."""

    line: int = 1
    column: int = 0
    end_line: int = 1
    end_column: int = 1

    @classmethod
    def from_form(cls, form: Any) -> "SourceRange":
        line = max(1, int(getattr(form, "line", 1) or 1))
        column = max(0, int(getattr(form, "col", 0) or 0))
        end_line = max(line, int(getattr(form, "end_line", line) or line))
        default_end = column + max(1, len(getattr(form, "name", "") or ""))
        end_column = max(
            column + 1,
            int(getattr(form, "end_col", default_end) or default_end),
        )
        return cls(line, column, end_line, end_column)


@dataclass(frozen=True)
class CheckDiagnostic:
    """One stable, source-addressable project diagnostic."""

    path: Path
    message: str
    code: str
    severity: str = "error"
    range: SourceRange = field(default_factory=SourceRange)

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        try:
            display_path = self.path.resolve().relative_to(project_root.resolve())
        except ValueError:
            display_path = self.path.resolve()
        return {
            "path": display_path.as_posix(),
            "line": self.range.line,
            "column": self.range.column + 1,
            "endLine": self.range.end_line,
            "endColumn": self.range.end_column + 1,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class Definition:
    """A public top-level binding discovered without executing a module."""

    name: str
    kind: str
    range: SourceRange


@dataclass(frozen=True)
class ReferredName:
    name: str
    range: SourceRange


@dataclass(frozen=True)
class RequireReference:
    namespace: str
    range: SourceRange
    alias: Optional[str] = None
    referred: Optional[tuple[ReferredName, ...] | str] = None


@dataclass(frozen=True)
class PythonImport:
    module: str
    range: SourceRange
    bound_names: tuple[str, ...] = ()


@dataclass
class IndexedDocument:
    """Static information for one project source file."""

    path: Path
    root: Path
    root_kind: str
    source: str
    expected_namespace: str
    namespace: Optional[str] = None
    namespace_range: SourceRange = field(default_factory=SourceRange)
    definitions: dict[str, Definition] = field(default_factory=dict)
    requires: list[RequireReference] = field(default_factory=list)
    python_imports: list[PythonImport] = field(default_factory=list)
    diagnostics: list[CheckDiagnostic] = field(default_factory=list)

    @property
    def available_names(self) -> set[str]:
        names = {normalize_name(name) for name in self.definitions}
        for required in self.requires:
            if required.alias:
                names.add(normalize_name(required.alias))
            if isinstance(required.referred, tuple):
                names.update(normalize_name(item.name) for item in required.referred)
        for imported in self.python_imports:
            names.update(normalize_name(name) for name in imported.bound_names)
        return names

    @property
    def has_parse_error(self) -> bool:
        return any(item.code == PARSE_ERROR for item in self.diagnostics)


@dataclass
class ProjectIndex:
    """Namespace and symbol index shared by project checks and editor tooling."""

    config: ProjectConfig
    documents: list[IndexedDocument]
    diagnostics: list[CheckDiagnostic]
    namespaces: dict[str, IndexedDocument]
    virtual_namespaces: dict[str, set[str]] = field(default_factory=dict)
    _external_documents: dict[Path, IndexedDocument] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        config: ProjectConfig,
        *,
        include_tests: bool = True,
    ) -> "ProjectIndex":
        project_root = Path(config.project_root).resolve()
        root_specs: list[tuple[Path, str]] = [
            (Path(path).resolve(), "source")
            for path in config.get_absolute_source_paths()
        ]
        if include_tests:
            root_specs.extend(
                (Path(path).resolve(), "test")
                for path in config.get_absolute_test_paths()
            )

        diagnostics: list[CheckDiagnostic] = []
        for root, kind in root_specs:
            if kind == "source" and not root.is_dir():
                diagnostics.append(
                    CheckDiagnostic(
                        path=project_root / "spork.it",
                        code=MISSING_SOURCE_ROOT,
                        message=f"Configured source path does not exist: {_relative(root, project_root)}",
                    )
                )

        # A file can be covered by overlapping roots.  The most specific root
        # owns it so its namespace is derived from the shortest relative path.
        discovered: dict[Path, list[tuple[Path, str]]] = {}
        for root, kind in root_specs:
            if not root.is_dir():
                continue
            for path in discover_spork_files(root):
                discovered.setdefault(path.resolve(), []).append((root, kind))

        documents: list[IndexedDocument] = []
        for path, owners in sorted(discovered.items(), key=lambda item: str(item[0])):
            root, kind = max(owners, key=lambda item: len(item[0].parts))
            if any(owner_kind == "source" for _, owner_kind in owners):
                # Source semantics win when source and test roots overlap.
                source_owners = [item for item in owners if item[1] == "source"]
                root, kind = max(source_owners, key=lambda item: len(item[0].parts))
            document = _index_document(path, root, kind)
            documents.append(document)
            diagnostics.extend(document.diagnostics)

        source_documents = [doc for doc in documents if doc.root_kind == "source"]
        if not source_documents:
            diagnostics.append(
                CheckDiagnostic(
                    path=project_root / "spork.it",
                    code=NO_SOURCE_FILES,
                    message="No .spork files were found under the configured source paths",
                )
            )

        namespaces: dict[str, IndexedDocument] = {}
        grouped: dict[str, list[IndexedDocument]] = {}
        for document in documents:
            if document.namespace:
                grouped.setdefault(document.namespace, []).append(document)
        for namespace, namespace_documents in grouped.items():
            namespaces[namespace] = namespace_documents[0]
            if len(namespace_documents) > 1:
                paths = ", ".join(
                    _relative(item.path, project_root) for item in namespace_documents
                )
                for document in namespace_documents:
                    diagnostics.append(
                        CheckDiagnostic(
                            path=document.path,
                            range=document.namespace_range,
                            code=DUPLICATE_NAMESPACE,
                            message=f"Namespace '{namespace}' is declared by multiple files: {paths}",
                        )
                    )

        virtual_namespaces: dict[str, set[str]] = {}
        if config.api and config.api.spork:
            virtual_namespaces[config.api.spork.namespace] = {
                normalize_name(name) for name in config.api.spork.exports
            }

        return cls(
            config=config,
            documents=documents,
            diagnostics=diagnostics,
            namespaces=namespaces,
            virtual_namespaces=virtual_namespaces,
        )

    @property
    def project_root(self) -> Path:
        return Path(self.config.project_root).resolve()

    def resolve_namespace(self, namespace: str) -> Optional[IndexedDocument | set[str]]:
        """Resolve a project, generated, standard-library, or installed namespace."""
        if namespace in self.namespaces:
            return self.namespaces[namespace]
        if namespace in self.virtual_namespaces:
            return self.virtual_namespaces[namespace]

        from spork.runtime.ns import find_spork_file_for_ns

        resolved = find_spork_file_for_ns(namespace)
        if not resolved:
            return None
        path = Path(resolved).resolve()
        for document in self.documents:
            if document.path == path:
                return document
        if path not in self._external_documents:
            # External files are indexed for export validation only.  Their
            # namespace/path convention belongs to the dependency's project.
            self._external_documents[path] = _index_document(
                path, path.parent, "external", validate_namespace=False
            )
        return self._external_documents[path]

    def available_names(self, namespace: str) -> Optional[set[str]]:
        target = self.resolve_namespace(namespace)
        if target is None:
            return None
        if isinstance(target, set):
            return set(target)
        if target.has_parse_error:
            return None
        return target.available_names


@dataclass
class CheckResult:
    """Complete result returned by :func:`check_project`."""

    project_root: Path
    project_name: str
    files_checked: int
    namespaces_checked: int
    diagnostics: list[CheckDiagnostic]
    index: ProjectIndex

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)

    @property
    def success(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "project": self.project_name,
            "projectRoot": str(self.project_root),
            "filesChecked": self.files_checked,
            "namespacesChecked": self.namespaces_checked,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "success": self.success,
            "diagnostics": [
                item.to_dict(self.project_root) for item in self.diagnostics
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)


def expected_namespace_for_path(path: Path, root: Path) -> str:
    """Return the canonical hyphenated namespace implied by a source path."""
    relative = path.resolve().relative_to(root.resolve()).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(part.replace("_", "-") for part in parts)


def check_project(
    config: Optional[ProjectConfig] = None,
    *,
    include_tests: bool = True,
) -> CheckResult:
    """Check every configured project source without producing build artifacts.

    The current process may execute trusted compile-time macros, exactly as
    ``spork build`` does.  Ordinary forms in the files being checked are never
    executed.
    """
    if config is None:
        config = ProjectConfig.load()

    from spork.project.manager import ProjectManager
    from spork.runtime import ns as runtime_ns

    old_sys_path = list(sys.path)
    manager = ProjectManager(config)
    if manager.has_venv():
        manager.inject_venv_paths()

    project_root = Path(config.project_root).resolve()
    source_roots = [Path(path).resolve() for path in config.get_absolute_source_paths()]
    test_roots = (
        [Path(path).resolve() for path in config.get_absolute_test_paths()]
        if include_tests
        else []
    )

    from spork.compiler.macros import MACRO_EXEC_ENV

    old_roots = list(runtime_ns.SOURCE_ROOTS)
    old_registry = dict(runtime_ns.NAMESPACE_REGISTRY)
    old_macro_exec_env = dict(MACRO_EXEC_ENV)
    diagnostics: list[CheckDiagnostic] = []

    with tempfile.TemporaryDirectory(prefix="spork-check-") as temporary:
        generated_root = Path(temporary)
        _write_virtual_spork_api(config, generated_root)
        roots = [generated_root, *source_roots, *test_roots]
        for root in reversed(roots):
            root_string = str(root)
            if root_string not in sys.path:
                sys.path.insert(0, root_string)
        runtime_ns.clear_registry()
        runtime_ns.init_source_roots(
            extra_paths=[str(root) for root in roots], include_cwd=False
        )

        try:
            index = ProjectIndex.build(config, include_tests=include_tests)
            diagnostics.extend(index.diagnostics)
            _validate_namespaces(index, diagnostics)
            _validate_imports(index, diagnostics)
            _validate_manifest(index, diagnostics)
            _compile_documents(index, diagnostics)
        finally:
            runtime_ns.clear_registry()
            runtime_ns.NAMESPACE_REGISTRY.update(old_registry)
            runtime_ns.SOURCE_ROOTS = old_roots
            MACRO_EXEC_ENV.clear()
            MACRO_EXEC_ENV.update(old_macro_exec_env)
            sys.path[:] = old_sys_path

    diagnostics = _deduplicate_and_sort(diagnostics, project_root)
    return CheckResult(
        project_root=project_root,
        project_name=config.name,
        files_checked=len(index.documents),
        namespaces_checked=len(index.namespaces) + len(index.virtual_namespaces),
        diagnostics=diagnostics,
        index=index,
    )


def format_human_result(result: CheckResult) -> str:
    """Render deterministic compiler-style output for a terminal."""
    lines = [f"Checking {result.project_name}..."]
    for diagnostic in result.diagnostics:
        item = diagnostic.to_dict(result.project_root)
        lines.append(
            f"{item['path']}:{item['line']}:{item['column']}: "
            f"{item['severity']} {item['code']}: {item['message']}"
        )
    file_word = "file" if result.files_checked == 1 else "files"
    if not result.diagnostics:
        lines.append(
            f"Checked {result.files_checked} {file_word}; no issues found"
        )
    else:
        error_word = "error" if result.error_count == 1 else "errors"
        warning_word = "warning" if result.warning_count == 1 else "warnings"
        lines.append(
            f"Checked {result.files_checked} {file_word}; "
            f"{result.error_count} {error_word}, "
            f"{result.warning_count} {warning_word}"
        )
    return "\n".join(lines)


def _index_document(
    path: Path,
    root: Path,
    root_kind: str,
    *,
    validate_namespace: bool = True,
) -> IndexedDocument:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        document = IndexedDocument(path, root, root_kind, "", "")
        document.diagnostics.append(
            CheckDiagnostic(
                path=path,
                code=PARSE_ERROR,
                message=f"Could not read source file: {exc}",
            )
        )
        return document

    try:
        expected_namespace = expected_namespace_for_path(path, root)
    except ValueError:
        expected_namespace = ""
    document = IndexedDocument(path, root, root_kind, source, expected_namespace)

    try:
        forms = read_str(source)
    except Exception as exc:
        document.diagnostics.append(
            CheckDiagnostic(
                path=path,
                range=_exception_range(exc),
                code=PARSE_ERROR,
                message=str(exc),
            )
        )
        return document

    namespace_forms = [
        form
        for form in forms
        if isinstance(form, list)
        and form
        and isinstance(form[0], Symbol)
        and form[0].name == "ns"
    ]
    if len(namespace_forms) > 1:
        for form in namespace_forms[1:]:
            document.diagnostics.append(
                CheckDiagnostic(
                    path=path,
                    range=SourceRange.from_form(form),
                    code=INVALID_NAMESPACE_CLAUSE,
                    message="A file may declare only one namespace",
                )
            )

    if namespace_forms:
        _index_namespace_form(document, namespace_forms[0])
    elif validate_namespace and root_kind == "source":
        document.diagnostics.append(
            CheckDiagnostic(
                path=path,
                code=MISSING_NAMESPACE,
                message=(
                    "Source files must declare a namespace"
                    + (
                        f"; expected '(ns {expected_namespace})'"
                        if expected_namespace
                        else ""
                    )
                ),
            )
        )

    namespace_matches_path = document.namespace == expected_namespace
    if root_kind == "test" and document.namespace == f"{expected_namespace}-test":
        # A test tree may mirror a source filename while using the conventional
        # ``-test`` namespace suffix (tests/acme/core.spork -> acme.core-test).
        namespace_matches_path = True
    if (
        validate_namespace
        and document.namespace
        and expected_namespace
        and not namespace_matches_path
    ):
        document.diagnostics.append(
            CheckDiagnostic(
                path=path,
                range=document.namespace_range,
                code=NAMESPACE_MISMATCH,
                message=(
                    f"Namespace '{document.namespace}' does not match its path; "
                    f"expected '{expected_namespace}'"
                ),
            )
        )

    for form in forms:
        _index_definition(document, form)
    return document


def _index_namespace_form(document: IndexedDocument, form: list[Any]) -> None:
    if len(form) < 2 or not isinstance(form[1], Symbol):
        document.diagnostics.append(
            CheckDiagnostic(
                path=document.path,
                range=SourceRange.from_form(form),
                code=INVALID_NAMESPACE_CLAUSE,
                message="ns form requires a namespace symbol",
            )
        )
        return

    namespace_form = form[1]
    document.namespace = namespace_form.name
    document.namespace_range = SourceRange.from_form(namespace_form)

    from spork.runtime.ns import parse_require_spec

    for clause in form[2:]:
        if not isinstance(clause, list) or not clause or not isinstance(clause[0], Keyword):
            document.diagnostics.append(
                CheckDiagnostic(
                    path=document.path,
                    range=SourceRange.from_form(clause),
                    code=INVALID_NAMESPACE_CLAUSE,
                    message=f"Invalid ns clause: {clause}",
                )
            )
            continue
        head = clause[0].name
        if head == "require":
            for spec in clause[1:]:
                try:
                    parsed = parse_require_spec(spec)
                except Exception as exc:
                    document.diagnostics.append(
                        CheckDiagnostic(
                            path=document.path,
                            range=SourceRange.from_form(spec),
                            code=INVALID_NAMESPACE_CLAUSE,
                            message=str(exc),
                        )
                    )
                    continue
                namespace_symbol = _first_symbol(spec)
                referred: Optional[tuple[ReferredName, ...] | str]
                if parsed["refer"] == ":all":
                    referred = ":all"
                elif parsed["refer"]:
                    refer_forms = _require_refer_forms(spec)
                    referred = tuple(
                        ReferredName(name, SourceRange.from_form(source_form))
                        for name, source_form in zip(parsed["refer"], refer_forms)
                    )
                else:
                    referred = None
                document.requires.append(
                    RequireReference(
                        namespace=parsed["ns"],
                        range=SourceRange.from_form(namespace_symbol or spec),
                        alias=parsed["alias"],
                        referred=referred,
                    )
                )
        elif head == "import":
            for spec in clause[1:]:
                imported = _parse_python_import(spec)
                if imported is not None:
                    document.python_imports.append(imported)
        else:
            document.diagnostics.append(
                CheckDiagnostic(
                    path=document.path,
                    range=SourceRange.from_form(clause[0]),
                    code=INVALID_NAMESPACE_CLAUSE,
                    message=f"Unknown ns clause: {clause[0]}",
                )
            )


def _index_definition(document: IndexedDocument, form: Any) -> None:
    if not isinstance(form, list) or len(form) < 2 or not isinstance(form[0], Symbol):
        return
    head = form[0].name
    if head == "def":
        args = list(form[1:])
        while args and isinstance(args[0], Decorated):
            args.pop(0)
        if args:
            for symbol in _binding_symbols(args[0]):
                document.definitions[symbol.name] = Definition(
                    symbol.name, "variable", SourceRange.from_form(symbol)
                )
        return
    if head not in {"defn", "deftest", "defmacro", "defclass", "defprotocol"}:
        return
    args = list(form[1:])
    while args and isinstance(args[0], Decorated):
        args.pop(0)
    if not args or not isinstance(args[0], Symbol):
        return
    name = args[0]
    kind = {
        "defn": "function",
        "deftest": "test",
        "defmacro": "macro",
        "defclass": "class",
        "defprotocol": "protocol",
    }[head]
    document.definitions[name.name] = Definition(
        name.name, kind, SourceRange.from_form(name)
    )
    if head == "defprotocol":
        for method in args[1:]:
            if isinstance(method, list) and method and isinstance(method[0], Symbol):
                method_name = method[0]
                document.definitions[method_name.name] = Definition(
                    method_name.name,
                    "protocol-function",
                    SourceRange.from_form(method_name),
                )


def _binding_symbols(pattern: Any) -> Iterable[Symbol]:
    if isinstance(pattern, Symbol):
        if pattern.name != "&":
            yield pattern
    elif isinstance(pattern, VectorLiteral):
        for item in pattern.items:
            yield from _binding_symbols(item)
    elif isinstance(pattern, MapLiteral):
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys" and isinstance(value, VectorLiteral):
                for item in value.items:
                    if isinstance(item, Symbol):
                        yield item
            elif isinstance(key, (Symbol, VectorLiteral, MapLiteral)):
                yield from _binding_symbols(key)


def _parse_python_import(spec: Any) -> Optional[PythonImport]:
    if not isinstance(spec, VectorLiteral) or not spec.items or not isinstance(spec.items[0], Symbol):
        return None
    module_form = spec.items[0]
    module = module_form.name.replace("/", ".")
    bound: list[str] = []
    alias: Optional[str] = None
    items = spec.items
    index = 1
    while index < len(items):
        item = items[index]
        if isinstance(item, Keyword) and item.name == "as":
            if index + 1 < len(items) and isinstance(items[index + 1], Symbol):
                alias = items[index + 1].name
            index += 2
            continue
        names: Optional[VectorLiteral] = None
        if isinstance(item, Keyword) and item.name == "refer":
            if index + 1 < len(items) and isinstance(items[index + 1], VectorLiteral):
                names = items[index + 1]
            index += 2
        elif isinstance(item, VectorLiteral):
            names = item
            index += 1
        elif isinstance(item, Symbol):
            bound.append(item.name)
            index += 1
        else:
            index += 1
        if names is not None:
            name_index = 0
            while name_index < len(names.items):
                name = names.items[name_index]
                if not isinstance(name, Symbol):
                    name_index += 1
                    continue
                public_name = name.name
                if (
                    name_index + 2 < len(names.items)
                    and isinstance(names.items[name_index + 1], Keyword)
                    and names.items[name_index + 1].name == "as"
                    and isinstance(names.items[name_index + 2], Symbol)
                ):
                    public_name = names.items[name_index + 2].name
                    name_index += 3
                else:
                    name_index += 1
                bound.append(public_name)
    if alias:
        bound.append(alias)
    elif not bound:
        bound.append(module.split(".")[0])
    return PythonImport(module, SourceRange.from_form(module_form), tuple(bound))


def _validate_namespaces(
    index: ProjectIndex, diagnostics: list[CheckDiagnostic]
) -> None:
    for document in index.documents:
        if document.has_parse_error:
            continue
        blocking = any(
            item.code == INVALID_NAMESPACE_CLAUSE for item in document.diagnostics
        )
        if blocking:
            continue
        for required in document.requires:
            target = index.resolve_namespace(required.namespace)
            if target is None:
                diagnostics.append(
                    CheckDiagnostic(
                        path=document.path,
                        range=required.range,
                        code=UNRESOLVED_NAMESPACE,
                        message=(
                            f"Cannot resolve Spork namespace '{required.namespace}': "
                            "no .spork file found; use :import for Python modules"
                        ),
                    )
                )
                continue
            if not isinstance(required.referred, tuple):
                continue
            available = index.available_names(required.namespace)
            if available is None:
                continue
            for referred in required.referred:
                if normalize_name(referred.name) not in available:
                    diagnostics.append(
                        CheckDiagnostic(
                            path=document.path,
                            range=referred.range,
                            code=MISSING_EXPORT,
                            message=(
                                f"Namespace '{required.namespace}' does not export "
                                f"'{referred.name}'"
                            ),
                        )
                    )


def _validate_imports(index: ProjectIndex, diagnostics: list[CheckDiagnostic]) -> None:
    for document in index.documents:
        for imported in document.python_imports:
            if not _python_module_is_resolvable(imported.module):
                diagnostics.append(
                    CheckDiagnostic(
                        path=document.path,
                        range=imported.range,
                        code=UNRESOLVED_PYTHON_MODULE,
                        message=(
                            f"Cannot resolve Python module '{imported.module}'; "
                            "run 'spork sync' if it is a project dependency"
                        ),
                    )
                )


def _validate_manifest(index: ProjectIndex, diagnostics: list[CheckDiagnostic]) -> None:
    config = index.config
    manifest = index.project_root / "spork.it"

    if config.main:
        if ":" in config.main:
            namespace, function = config.main.rsplit(":", 1)
        else:
            namespace, function = config.main, "main"
        available = index.available_names(namespace)
        if available is None:
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_MAIN,
                    message=f":main namespace '{namespace}' cannot be resolved",
                )
            )
        elif normalize_name(function) not in available:
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_MAIN,
                    message=(
                        f":main function '{function}' is not defined by namespace "
                        f"'{namespace}'"
                    ),
                )
            )
        else:
            main_target = index.resolve_namespace(namespace)
            if isinstance(main_target, IndexedDocument):
                definition = next(
                    (
                        item
                        for name, item in main_target.definitions.items()
                        if normalize_name(name) == normalize_name(function)
                    ),
                    None,
                )
                if definition is not None and definition.kind != "function":
                    diagnostics.append(
                        CheckDiagnostic(
                            path=manifest,
                            code=INVALID_MAIN,
                            message=(
                                f":main target '{namespace}:{function}' is a "
                                f"{definition.kind}, not a function"
                            ),
                        )
                    )

    api = config.api
    if api is None:
        return
    if not _validate_api_identifier(api.source_module):
        diagnostics.append(
            CheckDiagnostic(
                path=manifest,
                code=INVALID_API,
                message=f"Invalid module or namespace name in :api: {api.source_module!r}",
            )
        )
        return
    source_document = index.namespaces.get(api.source_module)
    if source_document is None or source_document.root_kind != "source":
        diagnostics.append(
            CheckDiagnostic(
                path=manifest,
                code=INVALID_API,
                message=f":api :from module was not compiled: {api.source_module!r}",
            )
        )
        return
    available = source_document.available_names

    if api.spork:
        normalized = [normalize_name(name) for name in api.spork.exports]
        _validate_api_names(
            diagnostics, manifest, normalized, available, "spork"
        )
        if not _validate_api_identifier(api.spork.namespace):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=f"Invalid module or namespace name in :api: {api.spork.namespace!r}",
                )
            )
        duplicates = sorted(
            {name for name in normalized if normalized.count(name) > 1}
        )
        if duplicates:
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=(
                        ":api :spork exports duplicate normalized names: "
                        + ", ".join(duplicates)
                    ),
                )
            )
        if any(not name.isidentifier() for name in normalized):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=":api :spork exports must normalize to identifiers",
                )
            )
        if normalize_name(api.spork.namespace) == normalize_name(api.source_module):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=":api :spork :namespace cannot equal :api :from",
                )
            )
        if _validate_api_identifier(api.spork.namespace):
            namespace_parts = [
                normalize_name(part) for part in api.spork.namespace.split(".")
            ]
            for root in (Path(path) for path in config.get_absolute_source_paths()):
                initializer = root.joinpath(*namespace_parts, "__init__.spork")
                if _is_handwritten_generated_target(
                    initializer,
                    ";; Generated by spork build from :api; do not edit.",
                ):
                    diagnostics.append(
                        CheckDiagnostic(
                            path=initializer,
                            code=INVALID_API,
                            message="Generated Spork API would overwrite a hand-written file",
                        )
                    )

    if api.python:
        if not _validate_api_identifier(api.python.package):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=f"Invalid module or namespace name in :api: {api.python.package!r}",
                )
            )
        if normalize_name(api.python.package) == normalize_name(api.source_module):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=":api :from cannot be the generated package initializer",
                )
            )
        exports = [
            (normalize_name(name), normalize_name(name)) for name in api.python.exports
        ]
        exports.extend(
            (normalize_name(source), normalize_name(public))
            for source, public in api.python.aliases.items()
        )
        _validate_api_names(
            diagnostics,
            manifest,
            [source for source, _ in exports],
            available,
            "python",
        )
        public_names = [public for _, public in exports]
        duplicates = sorted(
            {name for name in public_names if public_names.count(name) > 1}
        )
        if duplicates:
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=":api :python exports duplicate public names: " + ", ".join(duplicates),
                )
            )
        if any(not source.isidentifier() or not public.isidentifier() for source, public in exports):
            diagnostics.append(
                CheckDiagnostic(
                    path=manifest,
                    code=INVALID_API,
                    message=":api :python exports and aliases must normalize to Python identifiers",
                )
            )
        if api.python.typed:
            for document in index.documents:
                stub = document.path.with_suffix(".pyi")
                if document.root_kind == "source" and _is_handwritten_generated_target(
                    stub,
                    "# Generated by spork build from typed Spork declarations; do not edit.",
                ):
                    diagnostics.append(
                        CheckDiagnostic(
                            path=stub,
                            code=INVALID_API,
                            message="Generated typing API would overwrite a hand-written file",
                        )
                    )
        if _validate_api_identifier(api.python.package):
            package_parts = [
                normalize_name(part) for part in api.python.package.split(".")
            ]
            generated_names = ["__init__.py"]
            if api.python.typed:
                generated_names.extend(["__init__.pyi", "py.typed"])
            for root in (Path(path) for path in config.get_absolute_source_paths()):
                package = root.joinpath(*package_parts)
                for name in generated_names:
                    generated_target = package / name
                    allowed_header = (
                        "# Generated by spork build from :api; do not edit."
                        if name != "py.typed"
                        else None
                    )
                    if _is_handwritten_generated_target(
                        generated_target, allowed_header
                    ):
                        diagnostics.append(
                            CheckDiagnostic(
                                path=generated_target,
                                code=INVALID_API,
                                message="Generated Python API would overwrite a hand-written file",
                            )
                        )


def _validate_api_names(
    diagnostics: list[CheckDiagnostic],
    manifest: Path,
    names: list[str],
    available: set[str],
    target: str,
) -> None:
    missing = sorted(set(names).difference(available))
    if missing:
        diagnostics.append(
            CheckDiagnostic(
                path=manifest,
                code=INVALID_API,
                message=(
                    f":api :{target} exports are missing from the source module: "
                    + ", ".join(missing)
                ),
            )
        )


def _compile_documents(index: ProjectIndex, diagnostics: list[CheckDiagnostic]) -> None:
    from spork.compiler.loader import compile_file_to_python

    for document in index.documents:
        if document.has_parse_error:
            continue
        document_errors = [
            item
            for item in diagnostics
            if item.path.resolve() == document.path.resolve()
            and item.code in {INVALID_NAMESPACE_CLAUSE, UNRESOLVED_NAMESPACE}
        ]
        if document_errors:
            continue
        try:
            compile_file_to_python(
                document.source,
                str(document.path),
                aot=True,
                check_only=True,
            )
        except Exception as exc:
            candidate = CheckDiagnostic(
                path=document.path,
                range=_exception_range(exc),
                code=COMPILE_ERROR,
                message=str(exc),
            )
            diagnostics.append(candidate)


def _write_virtual_spork_api(config: ProjectConfig, root: Path) -> None:
    if not config.api or not config.api.spork:
        return
    api = config.api.spork
    if not _validate_api_identifier(api.namespace) or not _validate_api_identifier(
        config.api.source_module
    ):
        return
    package = root.joinpath(
        *(normalize_name(part) for part in api.namespace.split("."))
    )
    package.mkdir(parents=True, exist_ok=True)
    exports = " ".join(api.exports)
    (package / "__init__.spork").write_text(
        f"(ns {api.namespace}\n  (:require [{config.api.source_module} :refer [{exports}]]))\n",
        encoding="utf-8",
    )


def _python_module_is_resolvable(module_name: str) -> bool:
    """Resolve a dotted module without importing parent package code."""
    parts = module_name.split(".")
    search_path: Any = None
    for index, _part in enumerate(parts):
        qualified = ".".join(parts[: index + 1])
        loaded = sys.modules.get(qualified)
        spec = getattr(loaded, "__spec__", None) if loaded is not None else None
        if spec is None:
            try:
                if index == 0:
                    # Looking up a top-level spec never imports parent code and
                    # retains support for installed editable-package finders.
                    spec = importlib.util.find_spec(qualified)
                else:
                    spec = importlib.machinery.PathFinder.find_spec(
                        qualified, search_path
                    )
            except (AttributeError, ImportError, ModuleNotFoundError, ValueError):
                return False
        if spec is None:
            return False
        if index < len(parts) - 1:
            search_path = spec.submodule_search_locations
            if search_path is None:
                # A few standard-library compatibility modules, notably
                # ``os.path``, are pre-registered beneath a non-package.
                remainder = ".".join(parts[: index + 2])
                if remainder not in sys.modules:
                    return False
    return True


def _validate_api_identifier(name: str) -> bool:
    return bool(name) and all(
        normalize_name(part).isidentifier() for part in name.split(".")
    )


def _is_handwritten_generated_target(
    path: Path, allowed_header: Optional[str]
) -> bool:
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    if not content:
        return False
    return allowed_header is None or not content.startswith(allowed_header)


def _first_symbol(form: Any) -> Optional[Symbol]:
    if isinstance(form, Symbol):
        return form
    if isinstance(form, VectorLiteral):
        return next((item for item in form.items if isinstance(item, Symbol)), None)
    return None


def _require_refer_forms(spec: Any) -> list[Symbol]:
    if not isinstance(spec, VectorLiteral):
        return []
    for index, item in enumerate(spec.items):
        if (
            isinstance(item, Keyword)
            and item.name == "refer"
            and index + 1 < len(spec.items)
            and isinstance(spec.items[index + 1], VectorLiteral)
        ):
            return [
                name for name in spec.items[index + 1].items if isinstance(name, Symbol)
            ]
    return []


def _exception_range(exc: BaseException) -> SourceRange:
    line = getattr(exc, "lineno", None)
    offset = getattr(exc, "offset", None)
    end_line = getattr(exc, "end_lineno", None)
    end_offset = getattr(exc, "end_offset", None)
    message = str(exc)
    if not line:
        match = re.search(r"(?:at\s+)?line[:\s]+(\d+)", message, re.IGNORECASE)
        if match:
            line = int(match.group(1))
    if offset is None:
        match = re.search(r"col(?:umn)?[:\s]+(\d+)", message, re.IGNORECASE)
        offset = int(match.group(1)) + 1 if match else 1
    line = max(1, int(line or 1))
    column = max(0, int(offset or 1) - 1)
    final_line = max(line, int(end_line or line))
    final_column = max(column + 1, int(end_offset or column + 2) - 1)
    return SourceRange(line, column, final_line, final_column)


def _deduplicate_and_sort(
    diagnostics: list[CheckDiagnostic], project_root: Path
) -> list[CheckDiagnostic]:
    unique: dict[tuple[Any, ...], CheckDiagnostic] = {}
    for item in diagnostics:
        key = (
            item.path.resolve(),
            item.range.line,
            item.range.column,
            item.code,
            item.message,
            item.severity,
        )
        unique[key] = item

    def sort_key(item: CheckDiagnostic) -> tuple[Any, ...]:
        try:
            path = item.path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            path = item.path.resolve().as_posix()
        return (path, item.range.line, item.range.column, item.code, item.message)

    return sorted(unique.values(), key=sort_key)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
