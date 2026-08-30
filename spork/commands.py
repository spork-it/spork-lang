"""Shared command definitions for the Spork CLI.

Core commands and future package-provided commands use the same immutable
provider, context, descriptor, and invocation contract.  Discovery and project
runtime services are added by later command-system phases; this module keeps
the foundational contract independent from either mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional, TypeAlias

COMMAND_API_VERSION = 1

CommandScope: TypeAlias = Literal["core", "project", "active", "global"]


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

    Project loading and source-entry operations intentionally arrive in the
    next command-system phase.  Defining their shared context now lets core and
    extension handlers use one stable invocation boundary from the start.
    """

    command: str
    scope: CommandScope
    cwd: Path
    provider: CommandProvider
    api_version: int = COMMAND_API_VERSION
    project: object | None = None
    project_root: Path | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command name must not be empty")
        if self.scope != self.provider.scope:
            raise ValueError("command context scope must match its provider")


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
            raise TypeError(
                f"command {self.name!r} returned {type(result).__name__}; "
                "expected int or None"
            )
        return result


def create_command_context(
    spec: CommandSpec,
    *,
    cwd: Path | None = None,
    project: object | None = None,
    project_root: Path | None = None,
) -> CommandContext:
    """Create the standard immutable context for a selected command."""
    return CommandContext(
        command=spec.name,
        scope=spec.provider.scope,
        cwd=(cwd or Path.cwd()).resolve(),
        provider=spec.provider,
        project=project,
        project_root=project_root.resolve() if project_root is not None else None,
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
