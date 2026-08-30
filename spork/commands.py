"""Shared command definitions for the Spork CLI.

Core commands and future package-provided commands use the same immutable
provider, context, descriptor, and invocation contract. Project runtime
services are exposed through the context, while metadata-only provider
resolution and lazy loading live in :mod:`spork.command_discovery`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Optional, TypeAlias

if TYPE_CHECKING:
    from spork.project.config import ProjectConfig
    from spork.project.runtime import ProjectRuntime

COMMAND_API_VERSION = 1
COMMAND_ENTRY_POINT_GROUP = f"spork.commands.v{COMMAND_API_VERSION}"
COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
RESERVED_COMMAND_NAMES = frozenset(
    {
        "add",
        "build",
        "check",
        "clean",
        "dist",
        "lsp",
        "new",
        "plugin",
        "remove",
        "repl",
        "run",
        "sync",
        "test",
        "version",
    }
)

CommandScope: TypeAlias = Literal["core", "project", "active", "global"]


class ProjectRequiredError(RuntimeError):
    """Raised when a command needs project services outside a project."""


class CommandResultError(TypeError):
    """Raised when a selected command violates the result contract."""


@dataclass(frozen=True)
class CommandProvider:
    """Provenance for a statically or dynamically supplied command."""

    name: str
    scope: CommandScope
    version: Optional[str] = None
    location: Optional[Path] = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("command provider name must not be empty")


@dataclass(frozen=True)
class CommandContext:
    """Read-only context supplied to every selected command handler.

    Project-backed contexts expose reusable source loading without leaking
    mutable compiler state into the provider contract.
    """

    command: str
    scope: CommandScope
    cwd: Path
    provider: CommandProvider
    api_version: int = COMMAND_API_VERSION
    project: ProjectConfig | None = None
    project_root: Path | None = None
    _runtime: ProjectRuntime | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command name must not be empty")
        if self.scope != self.provider.scope:
            raise ValueError("command context scope must match its provider")
        if self.project is None and self.project_root is not None:
            raise ValueError("command context project root requires a project")
        if self._runtime is not None and self.project is not self._runtime.config:
            raise ValueError("command context runtime must match its project")

    def require_project(self) -> ProjectConfig:
        """Return the current project or raise an actionable command error."""
        if self.project is None:
            raise ProjectRequiredError(
                f"command {self.command!r} requires a Spork project; "
                "run it below a directory containing spork.it"
            )
        return self.project

    def _project_runtime(self) -> ProjectRuntime:
        if self._runtime is not None:
            return self._runtime

        from spork.project.runtime import ProjectRuntime

        return ProjectRuntime(self.require_project())

    def load_entry(self, target: str) -> object:
        """Load a value from an unbuilt source project namespace."""
        return self._project_runtime().load_entry(target)

    def invoke_entry(self, target: str, args: list[str]) -> int:
        """Invoke a function from an unbuilt source project namespace."""
        return self._project_runtime().invoke_entry(target, args)


CommandHandler: TypeAlias = Callable[[CommandContext, list[str]], Optional[int]]


@dataclass(frozen=True)
class CommandSpec:
    """Immutable description and raw-argument handler for one command."""

    name: str
    summary: str
    handler: CommandHandler
    provider: CommandProvider

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("command name must not be empty")
        if not self.summary:
            raise ValueError("command summary must not be empty")
        if not callable(self.handler):
            raise TypeError("command handler must be callable")

    def invoke(self, context: CommandContext, argv: list[str]) -> int:
        """Invoke the command and normalize its result to an exit status."""
        if context.command != self.name:
            raise ValueError(
                f"command context is for {context.command!r}, not {self.name!r}"
            )
        if context.provider != self.provider:
            raise ValueError("command context provider does not match command spec")

        result = self.handler(context, list(argv))
        if result is None:
            return 0
        if type(result) is not int:
            raise CommandResultError(
                f"command {self.name!r} returned {type(result).__name__}; "
                "expected int or None"
            )
        return result


def create_command_context(
    spec: CommandSpec,
    *,
    cwd: Path | None = None,
    project: ProjectConfig | None = None,
    project_root: Path | None = None,
    runtime: ProjectRuntime | None = None,
) -> CommandContext:
    """Create the standard immutable context for a selected command."""
    if runtime is not None:
        if project is not None and project is not runtime.config:
            raise ValueError("command runtime must match the selected project")
        project = runtime.config
    elif project is not None:
        from spork.project.runtime import ProjectRuntime

        runtime = ProjectRuntime(project)

    resolved_root = project_root.resolve() if project_root is not None else None
    if project is not None:
        configured_root = Path(project.project_root).resolve()
        if resolved_root is not None and resolved_root != configured_root:
            raise ValueError("command project root must match the selected project")
        resolved_root = configured_root
    elif resolved_root is not None:
        raise ValueError("command project root requires a project")

    return CommandContext(
        command=spec.name,
        scope=spec.provider.scope,
        cwd=(cwd or Path.cwd()).resolve(),
        provider=spec.provider,
        project=project,
        project_root=resolved_root,
        _runtime=runtime,
    )


def invoke_command(
    spec: CommandSpec,
    argv: list[str],
    *,
    context: CommandContext | None = None,
) -> int:
    """Invoke a command through the common command-system boundary."""
    selected_context = context or create_command_context(spec)
    return spec.invoke(selected_context, argv)
