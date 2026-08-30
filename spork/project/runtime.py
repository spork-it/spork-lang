"""Reusable execution support for entries in a Spork source project."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from spork.project.config import ProjectConfig
from spork.project.manager import ProjectManager


class ProjectRuntimeError(RuntimeError):
    """Base class for expected project entry-loading failures."""


class ProjectEnvironmentError(ProjectRuntimeError):
    """Raised when the project environment cannot be prepared."""


class InvalidProjectEntryError(ProjectRuntimeError, ValueError):
    """Raised when an entry target does not identify a namespace and value."""


class ProjectNamespaceNotFoundError(ProjectRuntimeError, LookupError):
    """Raised when an entry target's namespace cannot be found."""


class ProjectEntryNotFoundError(ProjectRuntimeError, LookupError):
    """Raised when a namespace does not export the requested entry."""


class ProjectEntryNotCallableError(ProjectRuntimeError, TypeError):
    """Raised when an entry selected for invocation is not callable."""


def _parse_entry_target(target: str) -> tuple[str, str]:
    if not isinstance(target, str) or not target.strip():
        raise InvalidProjectEntryError(
            "project entry target must be a non-empty string"
        )

    if ":" in target:
        namespace, entry = target.rsplit(":", 1)
    else:
        namespace, entry = target, "main"

    if (
        not namespace
        or not entry
        or namespace != namespace.strip()
        or entry != entry.strip()
    ):
        raise InvalidProjectEntryError(
            "project entry target must use namespace:value form"
        )
    return namespace, entry


class ProjectRuntime:
    """Load and invoke values directly from a project's Spork source.

    The runtime prepares configured source roots and project site-packages on
    first use. By default it preserves ``spork run`` behavior and synchronizes
    a missing environment. Embedding callers that intentionally need only
    source files may disable that with ``ensure_environment=False``.
    """

    def __init__(
        self,
        config: ProjectConfig,
        *,
        ensure_environment: bool = True,
        manager: Optional[ProjectManager] = None,
    ) -> None:
        self.config = config
        self.manager = manager or ProjectManager(config)
        self.ensure_environment = ensure_environment
        self._prepared = False

    @property
    def project_root(self) -> Path:
        """Return the absolute project root."""
        return Path(self.config.project_root).resolve()

    @property
    def environment_missing(self) -> bool:
        """Return whether the project has no usable virtual environment."""
        return not self.manager.has_venv()

    def prepare(self) -> None:
        """Expose project dependencies and configured source roots once."""
        if self._prepared:
            return

        if self.environment_missing and self.ensure_environment:
            try:
                success = self.manager.install_dependencies(quiet=False)
            except Exception as error:
                raise ProjectEnvironmentError(
                    f"Could not initialize project environment: {error}"
                ) from error
            if not success or not self.manager.has_venv():
                raise ProjectEnvironmentError(
                    "Failed to initialize project environment"
                )

        if self.manager.has_venv() and not self.manager.inject_venv_paths():
            raise ProjectEnvironmentError(
                "Could not expose project environment site-packages"
            )

        from spork.runtime.ns import add_source_root, init_source_roots

        init_source_roots(include_cwd=True)
        # add_source_root prepends, so iterate backwards to retain manifest order.
        for source_path in reversed(self.config.get_absolute_source_paths()):
            if os.path.isdir(source_path):
                add_source_root(source_path, prepend=True)

        self._prepared = True

    def _load_namespace(self, namespace: str) -> dict[str, Any]:
        from spork.compiler import exec_file
        from spork.runtime.ns import (
            find_spork_file_for_ns,
            get_namespace,
            register_namespace,
            unload_namespace,
        )

        self.prepare()
        spork_file = find_spork_file_for_ns(namespace)
        if spork_file is None:
            searched = self.config.get_absolute_source_paths()
            raise ProjectNamespaceNotFoundError(
                f"Namespace {namespace!r} not found\nSearched in: {searched}"
            )

        absolute_file = Path(spork_file).resolve()
        namespace_info = get_namespace(namespace)
        if namespace_info is not None and namespace_info.file is not None:
            loaded_file = Path(namespace_info.file).resolve()
            if loaded_file == absolute_file:
                return namespace_info.env

        # Avoid reusing a same-named namespace loaded from another project in
        # a long-lived embedding process.
        if namespace_info is not None:
            unload_namespace(namespace)

        environment = exec_file(str(absolute_file))
        namespace_info = get_namespace(namespace)
        if namespace_info is None:
            namespace_info = register_namespace(
                name=namespace,
                file=str(absolute_file),
                env=environment,
                macros=environment.get("__spork_macros__", {}),
            )
        return namespace_info.env

    def load_entry(self, target: str) -> object:
        """Load and return a source namespace value without invoking it."""
        from spork.runtime.types import normalize_name

        namespace, entry = _parse_entry_target(target)
        environment = self._load_namespace(namespace)
        normalized_entry = normalize_name(entry)

        if normalized_entry in environment:
            return environment[normalized_entry]
        if entry in environment:
            return environment[entry]
        raise ProjectEntryNotFoundError(
            f"Entry {entry!r} not found in namespace {namespace!r}"
        )

    def invoke_entry(self, target: str, args: list[str]) -> int:
        """Invoke a project source function and normalize its process status."""
        arguments = list(args)
        if not all(isinstance(argument, str) for argument in arguments):
            raise TypeError("project entry arguments must be strings")

        entry = self.load_entry(target)
        if not callable(entry):
            namespace, name = _parse_entry_target(target)
            raise ProjectEntryNotCallableError(
                f"Entry {name!r} in namespace {namespace!r} is not callable"
            )

        result = entry(*arguments)
        if isinstance(result, int):
            return int(result)
        return 0
