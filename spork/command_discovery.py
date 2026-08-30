"""Metadata-only discovery and lazy loading for package command providers."""

from __future__ import annotations

import keyword
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from spork.commands import (
    COMMAND_ENTRY_POINT_GROUP,
    COMMAND_NAME_PATTERN,
    RESERVED_COMMAND_NAMES,
    CommandContext,
    CommandProvider,
    CommandScope,
    CommandSpec,
)

if TYPE_CHECKING:
    from spork.project.config import ProjectConfig


class CommandProviderLoadError(RuntimeError):
    """Raised when selected provider metadata cannot load a callable."""


@dataclass(frozen=True)
class CommandDiscoveryDiagnostic:
    """One deterministic metadata or same-scope collision diagnostic."""

    message: str
    command: str | None = None
    provider: CommandProvider | None = None


@dataclass(frozen=True)
class DiscoveredCommand:
    """A command provider described entirely by distribution metadata."""

    name: str
    target: str
    provider: CommandProvider
    entry_point: metadata.EntryPoint = field(repr=False, compare=False)

    @property
    def summary(self) -> str:
        """Return a top-level help summary without importing provider code."""
        version = f" {self.provider.version}" if self.provider.version else ""
        return f"{self.provider.name}{version} ({self.provider.scope})"

    def create_spec(self) -> CommandSpec:
        """Create a common command spec whose provider is loaded on invocation."""

        def handler(context: CommandContext, argv: list[str]) -> int | None:
            if self.provider.scope == "project":
                from spork.project.manager import ProjectManager

                project = context.require_project()
                if not ProjectManager(project).inject_venv_paths():
                    raise CommandProviderLoadError(
                        f"could not expose project provider environment for "
                        f"command {self.name!r}"
                    )

            try:
                selected = self.entry_point.load()
            except (AttributeError, ImportError) as error:
                raise CommandProviderLoadError(
                    f"could not load command {self.name!r} from "
                    f"{self.provider.name}: {error}"
                ) from error
            if not callable(selected):
                raise CommandProviderLoadError(
                    f"command {self.name!r} from {self.provider.name} resolved "
                    f"to {type(selected).__name__}, not a callable"
                )
            return selected(context, argv)

        return CommandSpec(
            name=self.name,
            summary=self.summary,
            handler=handler,
            provider=self.provider,
        )


@dataclass(frozen=True)
class CommandCatalog:
    """Immutable commands and diagnostics discovered across ordered scopes."""

    commands: Mapping[str, DiscoveredCommand] = field(default_factory=dict)
    diagnostics: tuple[CommandDiscoveryDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "commands",
            MappingProxyType(dict(sorted(self.commands.items()))),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                sorted(
                    self.diagnostics,
                    key=lambda item: (item.command or "", item.message),
                )
            ),
        )

    def diagnostics_for(self, command: str) -> tuple[CommandDiscoveryDiagnostic, ...]:
        """Return diagnostics relevant to one top-level command name."""
        return tuple(item for item in self.diagnostics if item.command == command)


def _provider_label(provider: CommandProvider) -> str:
    version = f"=={provider.version}" if provider.version else ""
    location = f" at {provider.location}" if provider.location else ""
    return f"{provider.name}{version}{location}"


def _distribution_provider(
    distribution: metadata.Distribution,
    scope: CommandScope,
) -> CommandProvider:
    name = distribution.metadata.get("Name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("distribution metadata has no non-empty Name")
    try:
        version = distribution.version
    except Exception:
        version = None
    try:
        location = Path(str(distribution.locate_file(""))).resolve()
    except (OSError, TypeError, ValueError):
        location = None
    return CommandProvider(
        name=name,
        version=version or None,
        scope=scope,
        location=location,
    )


def _validate_entry_point(entry_point: metadata.EntryPoint) -> None:
    name = entry_point.name
    if not COMMAND_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "command name must use lowercase letters, digits, and single hyphens"
        )
    if name in RESERVED_COMMAND_NAMES:
        raise ValueError(f"command name {name!r} is reserved by spork-lang")

    value = entry_point.value
    if not isinstance(value, str) or value.count(":") != 1 or value != value.strip():
        raise ValueError("entry point must use module:function form")
    module, function = value.split(":", 1)
    module_parts = module.split(".")
    if (
        not module
        or any(not part for part in module_parts)
        or any(
            not part.isidentifier() or keyword.iskeyword(part)
            for part in module_parts
        )
    ):
        raise ValueError("entry-point module must be a dotted Python identifier")
    if not function.isidentifier() or keyword.iskeyword(function):
        raise ValueError("entry-point function must be a Python identifier")


def discover_commands(
    scope: CommandScope,
    *,
    paths: Sequence[str | Path] | None = None,
) -> CommandCatalog:
    """Discover one scope from entry-point metadata without importing providers."""
    if scope not in {"project", "active", "global"}:
        raise ValueError(f"cannot discover command providers in {scope!r} scope")

    diagnostics: list[CommandDiscoveryDiagnostic] = []
    candidates: dict[str, list[DiscoveredCommand]] = {}
    distribution_paths = None if paths is None else [str(Path(path)) for path in paths]

    try:
        if distribution_paths is None:
            distributions = list(metadata.distributions())
        else:
            distributions = list(metadata.distributions(path=distribution_paths))
    except Exception as error:
        return CommandCatalog(
            diagnostics=(
                CommandDiscoveryDiagnostic(
                    message=f"could not inspect {scope} command metadata: {error}"
                ),
            )
        )

    for distribution in distributions:
        provider: CommandProvider | None = None
        try:
            provider = _distribution_provider(distribution, scope)
            entry_points = distribution.entry_points
        except Exception as error:
            diagnostics.append(
                CommandDiscoveryDiagnostic(
                    message=f"invalid {scope} provider metadata: {error}",
                    provider=provider,
                )
            )
            continue

        for entry_point in entry_points:
            if entry_point.group != COMMAND_ENTRY_POINT_GROUP:
                continue
            command_name = (
                entry_point.name if isinstance(entry_point.name, str) else None
            )
            try:
                _validate_entry_point(entry_point)
            except (TypeError, ValueError) as error:
                diagnostics.append(
                    CommandDiscoveryDiagnostic(
                        command=command_name,
                        provider=provider,
                        message=(
                            f"invalid {scope} command metadata from "
                            f"{_provider_label(provider)}: {error}"
                        ),
                    )
                )
                continue

            candidate = DiscoveredCommand(
                name=entry_point.name,
                target=entry_point.value,
                provider=provider,
                entry_point=entry_point,
            )
            candidates.setdefault(candidate.name, []).append(candidate)

    commands: dict[str, DiscoveredCommand] = {}
    for name, matches in sorted(candidates.items()):
        ordered = sorted(
            matches,
            key=lambda item: (
                item.provider.name.casefold(),
                item.provider.version or "",
                str(item.provider.location or ""),
                item.target,
            ),
        )
        if len(ordered) == 1:
            commands[name] = ordered[0]
            continue
        providers = ", ".join(_provider_label(item.provider) for item in ordered)
        diagnostics.append(
            CommandDiscoveryDiagnostic(
                command=name,
                message=(
                    f"command {name!r} has multiple {scope} providers: {providers}"
                ),
            )
        )

    return CommandCatalog(commands=commands, diagnostics=tuple(diagnostics))


def _within(path: Path | None, root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _without_location(catalog: CommandCatalog, root: Path) -> CommandCatalog:
    """Remove active results that were already classified as project-local."""
    commands = {
        name: command
        for name, command in catalog.commands.items()
        if not _within(command.provider.location, root)
    }
    diagnostics = tuple(
        item
        for item in catalog.diagnostics
        if item.provider is None or not _within(item.provider.location, root)
    )
    return CommandCatalog(commands=commands, diagnostics=diagnostics)


def combine_command_catalogs(catalogs: Iterable[CommandCatalog]) -> CommandCatalog:
    """Combine scopes while preserving failures at the highest claiming scope."""
    commands: dict[str, DiscoveredCommand] = {}
    diagnostics: list[CommandDiscoveryDiagnostic] = []
    blocked: set[str] = set()
    for catalog in catalogs:
        for diagnostic in catalog.diagnostics:
            if diagnostic.command is None:
                diagnostics.append(diagnostic)
            elif (
                diagnostic.command not in commands
                and diagnostic.command not in blocked
            ):
                diagnostics.append(diagnostic)
                blocked.add(diagnostic.command)
        for name, command in catalog.commands.items():
            if name not in commands and name not in blocked:
                commands[name] = command
    return CommandCatalog(commands=commands, diagnostics=tuple(diagnostics))


def discover_extension_commands(project: ProjectConfig | None) -> CommandCatalog:
    """Discover project and active providers in deterministic precedence order."""
    catalogs: list[CommandCatalog] = []
    project_environment: Path | None = None
    if project is not None and project.venv_site_packages is not None:
        project_environment = Path(project.venv_site_packages).resolve()
        catalogs.append(
            discover_commands("project", paths=[project_environment])
        )

    active = discover_commands("active")
    if project_environment is not None:
        active = _without_location(active, project_environment)
    catalogs.append(active)
    return combine_command_catalogs(catalogs)
