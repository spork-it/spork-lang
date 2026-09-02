"""Managed global command-provider environments and registry.

Global plugins are explicit user installations. Each requested distribution is
installed with a compatible Spork host in its own virtual environment, while a
small atomic registry makes metadata-only command discovery possible without
importing providers.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import venv
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlsplit
from urllib.request import url2pathname

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from platformdirs import user_data_path

from spork.commands import (
    COMMAND_API_VERSION,
    COMMAND_NAME_PATTERN,
    RESERVED_COMMAND_NAMES,
    CommandProvider,
)

if TYPE_CHECKING:
    from spork.command_discovery import (
        CommandCatalog,
        CommandDiscoveryDiagnostic,
    )

REGISTRY_VERSION = 1
REGISTRY_FILENAME = "plugins.json"
LOCK_FILENAME = "plugins.lock"
PLUGINS_DIRECTORY = "plugins"


class PluginError(RuntimeError):
    """Base class for actionable managed-plugin failures."""


class PluginRegistryError(PluginError):
    """Raised when the managed global registry is malformed or inaccessible."""


class PluginInstallationError(PluginError):
    """Raised when a staged provider installation cannot be validated."""


@dataclass(frozen=True)
class PluginInstallTarget:
    """A package requirement or local Spork project selected for installation."""

    requirement: str
    distribution: str
    local_project: Path | None = None


@dataclass(frozen=True)
class GlobalPluginRecord:
    """One validated registry record for an explicitly installed provider."""

    requirement: str
    distribution: str
    display_name: str
    version: str
    api_version: int
    commands: tuple[str, ...]
    environment: Path
    site_packages: Path
    host_version: str
    installed_at: str
    installation_host: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "installation_host",
            MappingProxyType(dict(sorted(self.installation_host.items()))),
        )

    @property
    def python(self) -> Path:
        """Return the cross-platform Python executable in this plugin venv."""
        return plugin_environment_python(self.environment)

    @property
    def plugin_root(self) -> Path:
        """Return the managed directory containing this plugin's venv."""
        return self.environment.parent


class _RegistryLock(AbstractContextManager["_RegistryLock"]):
    """Small cross-platform exclusive lock on a stable sidecar file."""

    def __init__(self, path: Path, *, timeout: float = 120.0):
        self.path = path
        self.timeout = timeout
        self._file: Any = None

    def __enter__(self) -> "_RegistryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        if os.name == "nt":
            import msvcrt

            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"\0")
                self._file.flush()
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    self._file.seek(0)
                    locking = getattr(msvcrt, "locking")
                    locking(
                        self._file.fileno(),
                        getattr(msvcrt, "LK_NBLCK"),
                        1,
                    )
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise PluginRegistryError(
                            f"timed out waiting for global plugin registry lock "
                            f"at {self.path}"
                        ) from None
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                locking = getattr(msvcrt, "locking")
                locking(
                    self._file.fileno(),
                    getattr(msvcrt, "LK_UNLCK"),
                    1,
                )
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


def plugin_home() -> Path:
    """Return the platform-specific Spork user data directory.

    ``SPORK_HOME`` deliberately replaces the entire default directory, making
    tests, portable installations, and administrative setups deterministic.
    """
    override = os.environ.get("SPORK_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_path("spork", appauthor=False)).expanduser().resolve()


def plugin_environment_python(environment: str | Path) -> Path:
    """Return a virtual environment's Python executable on this platform."""
    root = Path(environment)
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _clean_install_value(value: str) -> str:
    if not isinstance(value, str):
        raise PluginInstallationError(
            "plugin requirement or project path must be a string"
        )
    cleaned = value.strip()
    if not cleaned:
        raise PluginInstallationError(
            "plugin requirement or project path must not be empty"
        )
    if cleaned != value or any(ord(character) < 32 for character in cleaned):
        raise PluginInstallationError(
            "plugin requirement or project path must not contain surrounding "
            "whitespace or control characters"
        )
    return cleaned


def _looks_like_local_path(value: str) -> bool:
    separators = {os.sep}
    if os.altsep:
        separators.add(os.altsep)
    try:
        expanded = Path(value).expanduser()
    except (OSError, RuntimeError):
        expanded = Path(value)
    return (
        value in {".", "..", "~"}
        or value.startswith("~")
        or expanded.is_absolute()
        or any(separator in value for separator in separators)
    )


def _file_url_path(url: str) -> Path | None:
    """Return a local path for a simple file URL, otherwise ``None``."""
    try:
        selected = urlsplit(url)
    except ValueError:
        return None
    if selected.scheme.casefold() != "file":
        return None
    if selected.netloc in {"", "localhost"}:
        url_path = selected.path
    elif os.name == "nt":
        url_path = f"//{selected.netloc}{selected.path}"
    else:
        return None
    try:
        return Path(url2pathname(url_path)).expanduser()
    except (OSError, RuntimeError, ValueError):
        return None


def _local_project_target(
    path: Path,
    *,
    requested: Requirement | None = None,
) -> PluginInstallTarget:
    """Resolve and validate a source Spork command-provider project."""
    try:
        selected = path.expanduser().resolve()
    except (OSError, RuntimeError) as error:
        raise PluginInstallationError(
            f"could not resolve local plugin project path {path}: {error}"
        ) from error
    if not selected.exists():
        raise PluginInstallationError(
            f"local plugin project path does not exist: {selected}"
        )
    if selected.is_file():
        if selected.name != "spork.it":
            raise PluginInstallationError(
                f"local plugin project path must be a directory or spork.it: "
                f"{selected}"
            )
        selected = selected.parent
    if not selected.is_dir():
        raise PluginInstallationError(
            f"local plugin project path is not a directory: {selected}"
        )
    manifest = selected / "spork.it"
    if not manifest.is_file():
        raise PluginInstallationError(
            f"local plugin project {selected} has no spork.it manifest; "
            "Python projects must use a named direct reference such as "
            f"`package @ {selected.as_uri()}`"
        )

    from spork.project.config import ProjectConfig

    try:
        config = ProjectConfig.load(str(selected))
    except (OSError, ValueError) as error:
        raise PluginInstallationError(
            f"could not load local plugin project {selected}: {error}"
        ) from error
    if not config.commands:
        raise PluginInstallationError(
            f"local Spork project {selected} does not declare any :commands"
        )

    try:
        identity = Requirement(config.name)
    except InvalidRequirement as error:
        raise PluginInstallationError(
            f"local Spork project :name {config.name!r} is not a valid "
            f"distribution name: {error}"
        ) from error
    if identity.extras or identity.specifier or identity.url or identity.marker:
        raise PluginInstallationError(
            f"local Spork project :name {config.name!r} must be a plain "
            "distribution name"
        )
    normalized = canonicalize_name(identity.name)
    if requested is not None:
        if requested.extras or requested.marker:
            raise PluginInstallationError(
                "local Spork project direct references do not support extras "
                "or environment markers"
            )
        if canonicalize_name(requested.name) != normalized:
            raise PluginInstallationError(
                f"local Spork project at {selected} is named {config.name!r}, not "
                f"{requested.name!r}"
            )

    requirement = f"{config.name} @ {selected.as_uri()}"
    # Keep registry requirements PEP 508-valid so existing registry validation
    # and repair diagnostics continue to work without a schema migration.
    try:
        Requirement(requirement)
    except InvalidRequirement as error:  # pragma: no cover - defensive
        raise PluginInstallationError(
            f"could not represent local plugin project as a requirement: {error}"
        ) from error
    return PluginInstallTarget(
        requirement=requirement,
        distribution=normalized,
        local_project=selected,
    )


def _resolve_install_target(value: str) -> PluginInstallTarget:
    """Resolve a package requirement or an explicit local Spork project path."""
    cleaned = _clean_install_value(value)
    try:
        parsed = Requirement(cleaned)
    except InvalidRequirement as error:
        if _looks_like_local_path(cleaned):
            return _local_project_target(Path(cleaned))
        raise PluginInstallationError(
            f"invalid plugin requirement {cleaned!r}: {error}"
        ) from error

    if parsed.url:
        local_path = _file_url_path(parsed.url)
        if local_path is not None:
            manifest = (
                local_path
                if local_path.name == "spork.it"
                else local_path / "spork.it"
            )
            if manifest.is_file():
                return _local_project_target(local_path, requested=parsed)

    return PluginInstallTarget(
        requirement=cleaned,
        distribution=canonicalize_name(parsed.name),
    )


def _clean_distribution_name(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PluginError("plugin package name must be a non-empty distribution name")
    try:
        parsed = Requirement(value)
    except InvalidRequirement as error:
        raise PluginError(f"invalid plugin package name {value!r}: {error}") from error
    if parsed.extras or parsed.specifier or parsed.url or parsed.marker:
        raise PluginError(
            "plugin removal accepts a package name, not a requirement; for "
            "example: `spork plugin remove spork-site`"
        )
    return canonicalize_name(parsed.name)


def _path_inside(root: Path, value: Any, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PluginRegistryError(f"registry field {field_name} must be a path string")
    relative = Path(value)
    if relative.is_absolute():
        raise PluginRegistryError(f"registry field {field_name} must be relative")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise PluginRegistryError(
            f"registry field {field_name} escapes the Spork plugin directory"
        ) from None
    return resolved


def _relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise PluginRegistryError(
            f"managed plugin path {path} is outside the Spork home {root}"
        ) from None
    return relative.as_posix()


def _parse_record(home: Path, key: str, value: Any) -> GlobalPluginRecord:
    if not isinstance(key, str) or canonicalize_name(key) != key:
        raise PluginRegistryError(f"invalid normalized plugin key {key!r}")
    if not isinstance(value, dict):
        raise PluginRegistryError(f"registry plugin {key!r} must be an object")

    def required_string(field_name: str) -> str:
        selected = value.get(field_name)
        if not isinstance(selected, str) or not selected:
            raise PluginRegistryError(
                f"registry plugin {key!r} field {field_name!r} must be a "
                "non-empty string"
            )
        return selected

    requirement = required_string("requirement")
    try:
        parsed_requirement = Requirement(requirement)
    except InvalidRequirement as error:
        raise PluginRegistryError(
            f"registry plugin {key!r} has an invalid requirement: {error}"
        ) from error

    distribution = required_string("distribution")
    if distribution != key or canonicalize_name(distribution) != distribution:
        raise PluginRegistryError(
            f"registry plugin {key!r} has inconsistent distribution identity"
        )
    if canonicalize_name(parsed_requirement.name) != distribution:
        raise PluginRegistryError(
            f"registry plugin {key!r} requirement names another distribution"
        )

    api_version = value.get("api_version")
    if type(api_version) is not int or api_version < 1:
        raise PluginRegistryError(
            f"registry plugin {key!r} has an invalid command API version"
        )

    raw_commands = value.get("commands")
    if (
        not isinstance(raw_commands, list)
        or not raw_commands
        or not all(isinstance(command, str) for command in raw_commands)
    ):
        raise PluginRegistryError(
            f"registry plugin {key!r} commands must be a non-empty string list"
        )
    commands = tuple(sorted(raw_commands))
    if len(commands) != len(set(commands)) or any(
        not COMMAND_NAME_PATTERN.fullmatch(command)
        or command in RESERVED_COMMAND_NAMES
        for command in commands
    ):
        raise PluginRegistryError(
            f"registry plugin {key!r} contains invalid command names"
        )

    environment = _path_inside(home, value.get("environment"), "environment")
    expected_environment = (home / PLUGINS_DIRECTORY / distribution / ".venv").resolve()
    if environment != expected_environment:
        raise PluginRegistryError(
            f"registry plugin {key!r} environment must be "
            f"{expected_environment}"
        )
    site_relative = value.get("site_packages")
    if not isinstance(site_relative, str) or not site_relative:
        raise PluginRegistryError(
            f"registry plugin {key!r} field 'site_packages' must be a path string"
        )
    site_path = Path(site_relative)
    if site_path.is_absolute():
        raise PluginRegistryError(
            f"registry plugin {key!r} site-packages path must be relative"
        )
    site_packages = (environment / site_path).resolve()
    try:
        site_packages.relative_to(environment.resolve())
    except ValueError:
        raise PluginRegistryError(
            f"registry plugin {key!r} site-packages path escapes its environment"
        ) from None

    installation_host = value.get("installation_host", {})
    if not isinstance(installation_host, dict) or not all(
        isinstance(host_key, str) and isinstance(host_value, str)
        for host_key, host_value in installation_host.items()
    ):
        raise PluginRegistryError(
            f"registry plugin {key!r} installation_host must contain strings"
        )

    return GlobalPluginRecord(
        requirement=requirement,
        distribution=distribution,
        display_name=required_string("display_name"),
        version=required_string("version"),
        api_version=api_version,
        commands=commands,
        environment=environment,
        site_packages=site_packages,
        host_version=required_string("host_version"),
        installed_at=required_string("installed_at"),
        installation_host=installation_host,
    )


def _record_json(home: Path, record: GlobalPluginRecord) -> dict[str, Any]:
    return {
        "requirement": record.requirement,
        "distribution": record.distribution,
        "display_name": record.display_name,
        "version": record.version,
        "api_version": record.api_version,
        "commands": list(record.commands),
        "environment": _relative_path(home, record.environment),
        "site_packages": _relative_path(record.environment, record.site_packages),
        "host_version": record.host_version,
        "installed_at": record.installed_at,
        "installation_host": dict(record.installation_host),
    }


def _distribution_at(path: Path, name: str) -> metadata.Distribution | None:
    selected = canonicalize_name(name)
    matches = []
    try:
        distributions = metadata.distributions(path=[str(path)])
        for distribution in distributions:
            distribution_name = distribution.metadata.get("Name")
            if (
                isinstance(distribution_name, str)
                and canonicalize_name(distribution_name) == selected
            ):
                matches.append(distribution)
    except Exception as error:
        raise PluginInstallationError(
            f"could not inspect installed distribution metadata: {error}"
        ) from error
    if len(matches) > 1:
        raise PluginInstallationError(
            f"environment contains multiple installations of {name}"
        )
    return matches[0] if matches else None


def _venv_site_packages(environment: Path) -> Path:
    python = plugin_environment_python(environment)
    probe = "import sysconfig; print(sysconfig.get_path('purelib'))"
    try:
        completed = subprocess.run(
            [str(python), "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise PluginInstallationError(
            f"could not query staged plugin environment: {error}"
        ) from error
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or "site-packages probe failed"
        raise PluginInstallationError(
            f"could not query staged plugin environment: {detail}"
        )
    selected = Path(completed.stdout.strip()).resolve()
    try:
        selected.relative_to(environment.resolve())
    except ValueError:
        raise PluginInstallationError(
            "staged plugin environment reported site-packages outside itself"
        ) from None
    return selected


def _host_install_requirement() -> str:
    """Use the source checkout when editable, otherwise the exact host release."""
    import spork

    project_root = Path(__file__).resolve().parents[1]
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if 'name = "spork-lang"' in content:
            return str(project_root)
    return f"spork-lang=={spork.__version__}"


def _installation_host() -> dict[str, str]:
    return {
        "executable": sys.executable,
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _build_local_project_wheel(
    project_root: Path,
    build_root: Path,
    *,
    quiet: bool,
) -> Path:
    """Compile one local Spork provider into an isolated temporary wheel."""
    from spork.project.dist import create_dist

    try:
        result = create_dist(
            project_root=project_root,
            out_dir=build_root / "compiled",
            dist_dir=build_root / "dist",
            build_first=True,
            clean=True,
            wheel=True,
            sdist=False,
            verbose=not quiet,
        )
    except Exception as error:
        raise PluginInstallationError(
            f"could not build local Spork plugin {project_root}: {error}"
        ) from error
    if not result.success or result.wheel_path is None:
        detail = result.error or "wheel creation failed"
        raise PluginInstallationError(
            f"could not build local Spork plugin {project_root}: {detail}"
        )
    wheel = result.wheel_path.resolve()
    if not wheel.is_file():
        raise PluginInstallationError(
            f"local Spork plugin build did not create wheel {wheel}"
        )
    return wheel


class PluginManager:
    """Install, inspect, and remove isolated global command providers."""

    def __init__(self, home: str | Path | None = None):
        self.home = Path(home).expanduser().resolve() if home else plugin_home()
        self.registry_path = self.home / REGISTRY_FILENAME
        self.lock_path = self.home / LOCK_FILENAME
        self.plugins_path = self.home / PLUGINS_DIRECTORY

    def _load_records_unlocked(self) -> dict[str, GlobalPluginRecord]:
        if not self.registry_path.exists():
            return {}
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PluginRegistryError(
                f"global plugin registry {self.registry_path} is corrupt: {error}; "
                "restore it or remove it and reinstall plugins"
            ) from error
        if not isinstance(raw, dict) or raw.get("registry_version") != REGISTRY_VERSION:
            raise PluginRegistryError(
                f"global plugin registry {self.registry_path} has an unsupported "
                "or missing registry version"
            )
        plugins = raw.get("plugins")
        if not isinstance(plugins, dict):
            raise PluginRegistryError(
                f"global plugin registry {self.registry_path} has no plugin map"
            )
        records: dict[str, GlobalPluginRecord] = {}
        for key, value in sorted(plugins.items()):
            record = _parse_record(self.home, key, value)
            records[key] = record
        return records

    def records(self) -> tuple[GlobalPluginRecord, ...]:
        """Return all registry records in normalized package-name order."""
        return tuple(self._load_records_unlocked().values())

    def _write_records_unlocked(
        self, records: Mapping[str, GlobalPluginRecord]
    ) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {
            "registry_version": REGISTRY_VERSION,
            "plugins": {
                name: _record_json(self.home, record)
                for name, record in sorted(records.items())
            },
        }
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.home,
                prefix=f".{REGISTRY_FILENAME}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            try:
                os.chmod(temporary_name, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary_name, self.registry_path)
            temporary_name = None
        except OSError as error:
            raise PluginRegistryError(
                f"could not update global plugin registry {self.registry_path}: "
                f"{error}"
            ) from error
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _run_install(
        self,
        environment: Path,
        requirement: str,
        *,
        quiet: bool,
        display_requirement: str | None = None,
    ) -> None:
        python = plugin_environment_python(environment)
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
        ]
        if quiet:
            command.append("--quiet")
        command.extend([_host_install_requirement(), requirement])
        label = display_requirement or requirement
        try:
            completed = subprocess.run(command, text=True, check=False)
        except OSError as error:
            raise PluginInstallationError(
                f"could not install plugin requirement {label!r}: {error}"
            ) from error
        if completed.returncode != 0:
            raise PluginInstallationError(
                f"pip could not install plugin requirement {label!r}"
            )

        try:
            check = subprocess.run(
                [str(python), "-m", "pip", "check"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise PluginInstallationError(
                f"could not validate installed plugin packages: {error}"
            ) from error
        if check.returncode != 0:
            detail = (check.stdout + check.stderr).strip()
            raise PluginInstallationError(
                f"installed plugin environment has inconsistent packages: {detail}"
            )

    def _inspect_staged(
        self,
        environment: Path,
        requirement: str,
        distribution_name: str,
    ) -> tuple[GlobalPluginRecord, Path]:
        from spork.command_discovery import discover_commands

        site_packages = _venv_site_packages(environment)
        distribution = _distribution_at(site_packages, distribution_name)
        if distribution is None:
            raise PluginInstallationError(
                f"installed requirement did not provide distribution "
                f"{distribution_name!r}"
            )

        catalog = discover_commands(
            "global",
            paths=[site_packages],
            provider_names=[distribution_name],
        )
        if catalog.diagnostics:
            details = "; ".join(item.message for item in catalog.diagnostics)
            raise PluginInstallationError(
                f"invalid command-provider metadata: {details}"
            )
        if not catalog.commands:
            raise PluginInstallationError(
                f"distribution {distribution_name!r} exposes no "
                f"spork.commands.v{COMMAND_API_VERSION} entry points"
            )

        host = _distribution_at(site_packages, "spork-lang")
        if host is None:
            raise PluginInstallationError(
                "plugin environment does not contain a Spork command host"
            )
        try:
            host_version = host.version
            provider_version = distribution.version
        except Exception as error:
            raise PluginInstallationError(
                f"installed plugin metadata has no usable version: {error}"
            ) from error
        display_name = distribution.metadata.get("Name")
        if not isinstance(display_name, str) or not display_name:
            raise PluginInstallationError(
                "installed plugin metadata has no distribution name"
            )

        return (
            GlobalPluginRecord(
                requirement=requirement,
                distribution=distribution_name,
                display_name=display_name,
                version=provider_version,
                api_version=COMMAND_API_VERSION,
                commands=tuple(sorted(catalog.commands)),
                environment=environment,
                site_packages=site_packages,
                host_version=host_version,
                installed_at=datetime.now(timezone.utc).isoformat(),
                installation_host=_installation_host(),
            ),
            site_packages.relative_to(environment),
        )

    def add(self, requirement: str, *, quiet: bool = False) -> GlobalPluginRecord:
        """Stage and atomically install or replace one global provider."""
        target = _resolve_install_target(requirement)
        normalized_name = target.distribution
        self.plugins_path.mkdir(parents=True, exist_ok=True)

        with _RegistryLock(self.lock_path):
            records = self._load_records_unlocked()
            stage_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{normalized_name}-",
                    suffix=".tmp",
                    dir=self.plugins_path,
                )
            )
            backup_root: Path | None = None
            moved_stage = False
            final_root = self.plugins_path / normalized_name
            try:
                install_requirement = target.requirement
                build_root = stage_root / ".local-build"
                if target.local_project is not None:
                    install_requirement = str(
                        _build_local_project_wheel(
                            target.local_project,
                            build_root,
                            quiet=quiet,
                        )
                    )

                environment = stage_root / ".venv"
                try:
                    venv.EnvBuilder(
                        with_pip=True,
                        clear=True,
                        symlinks=(os.name != "nt"),
                    ).create(environment)
                except Exception as error:
                    raise PluginInstallationError(
                        f"could not create plugin environment: {error}"
                    ) from error

                self._run_install(
                    environment,
                    install_requirement,
                    quiet=quiet,
                    display_requirement=target.requirement,
                )
                if build_root.exists():
                    try:
                        shutil.rmtree(build_root)
                    except OSError as error:
                        raise PluginInstallationError(
                            f"could not clean temporary local plugin build: {error}"
                        ) from error
                staged_record, site_relative = self._inspect_staged(
                    environment,
                    target.requirement,
                    normalized_name,
                )

                command_owners = {
                    command: record.distribution
                    for record in records.values()
                    if record.distribution != normalized_name
                    for command in record.commands
                }
                collisions = sorted(
                    command
                    for command in staged_record.commands
                    if command in command_owners
                )
                if collisions:
                    details = ", ".join(
                        f"{command!r} (owned by {command_owners[command]})"
                        for command in collisions
                    )
                    raise PluginInstallationError(
                        f"global command collision: {details}"
                    )

                final_environment = final_root / ".venv"
                final_record = replace(
                    staged_record,
                    environment=final_environment,
                    site_packages=final_environment / site_relative,
                )
                updated = dict(records)
                updated[normalized_name] = final_record

                if final_root.exists():
                    backup_root = self.plugins_path / (
                        f".{normalized_name}-{uuid.uuid4().hex}.backup"
                    )
                    os.replace(final_root, backup_root)
                try:
                    os.replace(stage_root, final_root)
                except Exception:
                    if backup_root is not None and backup_root.exists():
                        os.replace(backup_root, final_root)
                    raise
                moved_stage = True
                try:
                    self._write_records_unlocked(updated)
                except Exception:
                    if final_root.exists():
                        shutil.rmtree(final_root, ignore_errors=True)
                    if backup_root is not None and backup_root.exists():
                        os.replace(backup_root, final_root)
                    raise

                if backup_root is not None:
                    shutil.rmtree(backup_root, ignore_errors=True)
                return final_record
            finally:
                if not moved_stage:
                    shutil.rmtree(stage_root, ignore_errors=True)

    def remove(self, package: str) -> GlobalPluginRecord:
        """Atomically unregister and remove one explicitly installed provider."""
        normalized_name = _clean_distribution_name(package)
        with _RegistryLock(self.lock_path):
            records = self._load_records_unlocked()
            try:
                record = records[normalized_name]
            except KeyError:
                raise PluginError(
                    f"global plugin {normalized_name!r} is not installed"
                ) from None

            updated = dict(records)
            del updated[normalized_name]
            plugin_root = record.plugin_root
            tombstone: Path | None = None
            if plugin_root.exists():
                tombstone = self.plugins_path / (
                    f".{normalized_name}-{uuid.uuid4().hex}.removing"
                )
                try:
                    os.replace(plugin_root, tombstone)
                except OSError as error:
                    raise PluginError(
                        f"could not stage removal of {normalized_name}: {error}"
                    ) from error
            try:
                self._write_records_unlocked(updated)
            except Exception:
                if tombstone is not None and tombstone.exists():
                    os.replace(tombstone, plugin_root)
                raise
            if tombstone is not None:
                try:
                    shutil.rmtree(tombstone)
                except OSError as error:
                    raise PluginError(
                        f"removed {normalized_name} from the registry but could not "
                        f"delete {tombstone}: {error}"
                    ) from error
            return record


def _broken_record_diagnostics(
    record: GlobalPluginRecord, message: str
) -> list[CommandDiscoveryDiagnostic]:
    from spork.command_discovery import CommandDiscoveryDiagnostic

    provider = CommandProvider(
        name=record.display_name,
        version=record.version,
        scope="global",
        location=record.site_packages,
    )
    requirement_argument = (
        json.dumps(record.requirement)
        if any(character.isspace() for character in record.requirement)
        else record.requirement
    )
    repair = (
        f"managed global plugin {record.display_name} is broken: {message}; "
        f"repair it with `spork plugin remove {record.distribution}` followed by "
        f"`spork plugin add {requirement_argument}`"
    )
    return [
        CommandDiscoveryDiagnostic(
            command=command,
            provider=provider,
            message=repair,
        )
        for command in record.commands
    ]


def discover_global_commands(
    manager: PluginManager | None = None,
) -> CommandCatalog:
    """Discover and validate registered globals without importing providers."""
    from spork.command_discovery import (
        CommandCatalog,
        CommandDiscoveryDiagnostic,
        DiscoveredCommand,
        discover_commands,
    )

    selected_manager = manager or PluginManager()
    try:
        records = selected_manager.records()
    except PluginRegistryError as error:
        return CommandCatalog(
            diagnostics=(CommandDiscoveryDiagnostic(message=str(error)),)
        )

    candidates: dict[str, list[DiscoveredCommand]] = {}
    diagnostics: list[CommandDiscoveryDiagnostic] = []
    for record in records:
        try:
            if record.api_version != COMMAND_API_VERSION:
                raise PluginInstallationError(
                    f"command API v{record.api_version} is not supported by this "
                    f"v{COMMAND_API_VERSION} host"
                )
            if not record.environment.is_dir():
                raise PluginInstallationError(
                    f"environment {record.environment} is missing"
                )
            if not record.python.is_file():
                raise PluginInstallationError(
                    f"Python executable {record.python} is missing"
                )
            if not record.site_packages.is_dir():
                raise PluginInstallationError(
                    f"site-packages {record.site_packages} is missing"
                )

            host = _distribution_at(record.site_packages, "spork-lang")
            if host is None or host.version != record.host_version:
                actual = None if host is None else host.version
                raise PluginInstallationError(
                    f"host version is {actual or 'missing'}, expected "
                    f"{record.host_version}"
                )
            provider_distribution = _distribution_at(
                record.site_packages, record.distribution
            )
            if (
                provider_distribution is None
                or provider_distribution.version != record.version
            ):
                actual = (
                    None
                    if provider_distribution is None
                    else provider_distribution.version
                )
                raise PluginInstallationError(
                    f"provider version is {actual or 'missing'}, expected "
                    f"{record.version}"
                )

            catalog = discover_commands(
                "global",
                paths=[record.site_packages],
                provider_names=[record.distribution],
            )
            if catalog.diagnostics:
                raise PluginInstallationError(
                    "; ".join(item.message for item in catalog.diagnostics)
                )
            actual_commands = tuple(sorted(catalog.commands))
            if actual_commands != record.commands:
                raise PluginInstallationError(
                    f"registered commands {record.commands!r} do not match "
                    f"installed commands {actual_commands!r}"
                )

            for command_name, command in catalog.commands.items():
                executable = replace(
                    command,
                    execution_python=record.python,
                    host_version=record.host_version,
                )
                candidates.setdefault(command_name, []).append(executable)
        except (PluginError, OSError, ValueError) as error:
            diagnostics.extend(_broken_record_diagnostics(record, str(error)))

    commands: dict[str, DiscoveredCommand] = {}
    for name, matches in sorted(candidates.items()):
        if len(matches) == 1:
            commands[name] = matches[0]
            continue
        providers = ", ".join(
            sorted(
                f"{match.provider.name}=={match.provider.version}"
                for match in matches
            )
        )
        diagnostics.append(
            CommandDiscoveryDiagnostic(
                command=name,
                message=(
                    f"command {name!r} has multiple managed global providers: "
                    f"{providers}; remove one conflicting plugin"
                ),
            )
        )
    return CommandCatalog(commands=commands, diagnostics=tuple(diagnostics))
