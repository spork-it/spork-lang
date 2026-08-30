"""
spork.project.config - Project configuration loader

This module handles parsing and loading spork.it project manifest files.
It provides the ProjectConfig class which holds all project metadata
and configuration.

The spork.it file uses Spork map syntax:
    {:name "my-project"
     :version "0.1.0"
     :description "A sample project"
     :requires-python ">=3.10"
     :spork-version ">=0.6,<0.7"
     :dependencies ["requests" "numpy>=1.20"]
     :dev-dependencies ["mypy>=1.11"]
     :source-paths ["src"]
     :test-paths ["tests"]
     :main "my-project.core:main"}
"""

import keyword
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from spork.compiler.reader import read_str
from spork.runtime.types import Keyword, MapLiteral, VectorLiteral

# Default configuration values
DEFAULT_SOURCE_PATHS = ["src"]
DEFAULT_TEST_PATHS = ["tests"]
DEFAULT_REQUIRES_PYTHON = ">=3.10"
PROJECT_FILENAME = "spork.it"


@dataclass(frozen=True)
class CommandConfig:
    """One package-provided top-level command declaration."""

    main: str
    description: Optional[str] = None

    @property
    def namespace(self) -> str:
        """Return the Spork namespace containing the command function."""
        return self.main.rsplit(":", 1)[0]

    @property
    def function(self) -> str:
        """Return the Spork function selected by the declaration."""
        return self.main.rsplit(":", 1)[1]

    @property
    def python_target(self) -> str:
        """Return the normalized Python entry-point target."""
        from spork.runtime.types import normalize_name

        module = ".".join(
            normalize_name(part) for part in self.namespace.split(".")
        )
        return f"{module}:{normalize_name(self.function)}"


@dataclass(frozen=True)
class SporkAPIConfig:
    """Generated public Spork namespace configuration."""

    namespace: str
    exports: list[str]


@dataclass(frozen=True)
class PythonAPIConfig:
    """Generated Python package facade and typing configuration."""

    package: str
    exports: list[str]
    aliases: dict[str, str] = field(default_factory=dict)
    include_version: bool = True
    typed: bool = True


@dataclass(frozen=True)
class APIConfig:
    """Public API generated from one canonical Spork namespace."""

    source_module: str
    spork: Optional[SporkAPIConfig] = None
    python: Optional[PythonAPIConfig] = None


def spork_to_python(value: Any) -> Any:
    """
    Convert Spork types to Python native types for internal tooling use.

    - Keyword -> str (without the colon)
    - VectorLiteral -> list
    - MapLiteral -> dict
    - Other types pass through unchanged
    """
    if isinstance(value, Keyword):
        return value.name
    elif isinstance(value, VectorLiteral):
        return [spork_to_python(item) for item in value.items]
    elif isinstance(value, MapLiteral):
        return {spork_to_python(k): spork_to_python(v) for k, v in value.pairs}
    elif isinstance(value, list):
        return [spork_to_python(item) for item in value]
    elif isinstance(value, dict):
        return {spork_to_python(k): spork_to_python(v) for k, v in value.items()}
    else:
        return value


def _freeze_manifest_value(value: Any) -> Any:
    """Recursively expose parsed manifest values through immutable containers."""
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_manifest_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_manifest_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_manifest_value(item) for item in value)
    return value


def _validate_command_target(command_name: str, target: Any) -> str:
    """Validate and return one source namespace/function target."""
    from spork.runtime.types import normalize_name

    field = f":commands {command_name!r} :main"
    if not isinstance(target, str) or not target:
        raise ValueError(f"{field} must be a non-empty string")
    if target != target.strip() or target.count(":") != 1:
        raise ValueError(f"{field} must use namespace:function form")

    namespace, function = target.split(":", 1)
    namespace_parts = namespace.split(".")
    normalized_parts = [normalize_name(part) for part in namespace_parts]
    if (
        not namespace
        or any(not part for part in namespace_parts)
        or any(
            not part.isidentifier() or keyword.iskeyword(part)
            for part in normalized_parts
        )
    ):
        raise ValueError(
            f"{field} namespace must normalize to a dotted Python module name"
        )

    normalized_function = normalize_name(function)
    if (
        not function
        or not normalized_function.isidentifier()
        or keyword.iskeyword(normalized_function)
    ):
        raise ValueError(f"{field} function must normalize to a Python identifier")
    return target


def _validate_raw_command_names(config_form: MapLiteral) -> None:
    """Retain the schema distinction between string and keyword map keys."""
    for key, value in config_form.pairs:
        key_name = key.name if isinstance(key, Keyword) else key
        if key_name != "commands" or not isinstance(value, MapLiteral):
            continue
        seen: set[str] = set()
        for command_name, _declaration in value.pairs:
            if not isinstance(command_name, str):
                raise ValueError(":commands names must be strings")
            if command_name in seen:
                raise ValueError(
                    f":commands contains duplicate name {command_name!r}"
                )
            seen.add(command_name)


def _parse_commands(value: Any) -> dict[str, CommandConfig]:
    """Parse typed package command declarations from a manifest value."""
    from spork.commands import COMMAND_NAME_PATTERN, RESERVED_COMMAND_NAMES

    if not isinstance(value, dict):
        raise ValueError(":commands must be a map")

    commands: dict[str, CommandConfig] = {}
    for name, declaration in value.items():
        if not isinstance(name, str) or not COMMAND_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                ":commands names must use lowercase letters, digits, and single "
                "hyphens, beginning with a letter"
            )
        if name in RESERVED_COMMAND_NAMES:
            raise ValueError(f":commands name {name!r} is reserved by spork-lang")

        description: Optional[str] = None
        if isinstance(declaration, str):
            main = declaration
        elif isinstance(declaration, dict):
            unknown = set(declaration).difference({"main", "description"})
            if unknown:
                fields = ", ".join(sorted(repr(item) for item in unknown))
                raise ValueError(
                    f":commands {name!r} contains unknown fields: {fields}"
                )
            if "main" not in declaration:
                raise ValueError(f":commands {name!r} is missing required field :main")
            main = declaration["main"]
            description = declaration.get("description")
            if description is not None and (
                not isinstance(description, str) or not description.strip()
            ):
                raise ValueError(
                    f":commands {name!r} :description must be a non-empty string"
                )
        else:
            raise ValueError(
                f":commands {name!r} must be a target string or a command map"
            )

        commands[name] = CommandConfig(
            main=_validate_command_target(name, main),
            description=description,
        )
    return commands


def find_project_root(start_path: Optional[str] = None) -> Optional[str]:
    """
    Find the project root by walking up directory trees looking for spork.it.

    Args:
        start_path: Path to start searching from. If None, uses current working directory.
                   Can be a file or directory path.

    Returns:
        Absolute path to the directory containing spork.it, or None if not found.
    """
    if start_path is None:
        current = os.getcwd()
    elif os.path.isfile(start_path):
        current = os.path.dirname(os.path.abspath(start_path))
    else:
        current = os.path.abspath(start_path)

    # Walk up the directory tree
    while True:
        project_file = os.path.join(current, PROJECT_FILENAME)
        if os.path.isfile(project_file):
            return current

        parent = os.path.dirname(current)
        if parent == current:
            # Reached filesystem root
            return None
        current = parent


@dataclass
class ProjectConfig:
    """
    Represents a Spork project configuration loaded from spork.it.

    Required fields:
        name: Project name (string)
        version: Project version (string, e.g., "0.1.0")

    Optional fields:
        description: Project description
        dependencies: Runtime dependency specifications (pip-style)
        dev_dependencies: Development-only dependency specifications
        source_paths: List of source directories (default: ["src"])
        test_paths: List of test directories (default: ["tests"])
        main: Entry point function (e.g., "my-app.core:main")
        requires_python: Supported Python requirement
        readme/license/authors/keywords/classifiers/urls: Distribution metadata
        optional_dependencies: Named Python package extras
        spork_version: spork-lang compiler compatibility requirement
        api: Generated Spork and Python public API configuration
        commands: Package-provided top-level command declarations

    Computed fields:
        project_root: Absolute path to the directory containing spork.it
    """

    name: str
    version: str
    project_root: str
    description: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=lambda: DEFAULT_SOURCE_PATHS.copy())
    test_paths: list[str] = field(default_factory=lambda: DEFAULT_TEST_PATHS.copy())
    main: Optional[str] = None
    requires_python: str = DEFAULT_REQUIRES_PYTHON
    readme: Optional[str] = None
    license: Optional[str] = None
    license_file: Optional[str] = None
    authors: list[dict[str, str]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    classifiers: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)
    optional_dependencies: dict[str, list[str]] = field(default_factory=dict)
    spork_version: Optional[str] = None
    api: Optional[APIConfig] = None
    commands: dict[str, CommandConfig] = field(default_factory=dict)

    # Store the raw config for internal tooling and expose an immutable view.
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)
    _manifest: Mapping[str, Any] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._manifest = _freeze_manifest_value(self._raw)

    @property
    def manifest(self) -> Mapping[str, Any]:
        """Return the complete parsed manifest through a read-only view."""
        return self._manifest

    def get(self, key: str, default: Any = None) -> Any:
        """Return a read-only manifest value, including package-specific data."""
        return self._manifest.get(key, default)

    def get_plugin_config(self, name: str, default: Any = None) -> Any:
        """Return read-only configuration owned by a command-provider package."""
        if not isinstance(name, str) or not name:
            raise ValueError("plugin configuration name must be a non-empty string")
        return self._manifest.get(name, default)

    @property
    def venv_path(self) -> str:
        """Path to the project's virtual environment."""
        return os.path.join(self.project_root, ".venv")

    @property
    def venv_python(self) -> str:
        """Path to the Python executable in the venv."""
        if os.name == "nt":  # Windows
            return os.path.join(self.venv_path, "Scripts", "python.exe")
        else:
            return os.path.join(self.venv_path, "bin", "python")

    @property
    def venv_pip(self) -> str:
        """Path to the pip executable in the venv."""
        if os.name == "nt":  # Windows
            return os.path.join(self.venv_path, "Scripts", "pip.exe")
        else:
            return os.path.join(self.venv_path, "bin", "pip")

    @property
    def venv_site_packages(self) -> Optional[str]:
        """Path to the site-packages directory in the venv."""
        if os.name == "nt":
            site_packages = os.path.join(self.venv_path, "Lib", "site-packages")
        else:
            # Find the Python version directory
            lib_path = os.path.join(self.venv_path, "lib")
            if os.path.isdir(lib_path):
                for entry in os.listdir(lib_path):
                    if entry.startswith("python"):
                        site_packages = os.path.join(lib_path, entry, "site-packages")
                        if os.path.isdir(site_packages):
                            return site_packages
            return None
        return site_packages if os.path.isdir(site_packages) else None

    def get_absolute_source_paths(self) -> list[str]:
        """Return absolute paths for all source directories."""
        return [os.path.join(self.project_root, p) for p in self.source_paths]

    def get_absolute_test_paths(self) -> list[str]:
        """Return absolute paths for all test directories."""
        return [os.path.join(self.project_root, p) for p in self.test_paths]

    def has_venv(self) -> bool:
        """Check if the virtual environment exists."""
        return os.path.isdir(self.venv_path) and os.path.isfile(self.venv_python)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "ProjectConfig":
        """
        Load a ProjectConfig from a spork.it file.

        Args:
            path: Path to spork.it file, directory containing it, or None to search
                  from current directory upward.

        Returns:
            Loaded ProjectConfig instance.

        Raises:
            FileNotFoundError: If no spork.it file can be found.
            ValueError: If the spork.it file is invalid or missing required fields.
        """
        # Determine the project file path
        if path is None:
            project_root = find_project_root()
            if project_root is None:
                raise FileNotFoundError(
                    f"Could not find {PROJECT_FILENAME} in current directory or any parent directory"
                )
        elif os.path.isfile(path):
            if os.path.basename(path) == PROJECT_FILENAME:
                project_root = os.path.dirname(os.path.abspath(path))
            else:
                # Assume it's a file within a project, search upward
                project_root = find_project_root(path)
                if project_root is None:
                    raise FileNotFoundError(
                        f"Could not find {PROJECT_FILENAME} starting from {path}"
                    )
        elif os.path.isdir(path):
            project_file = os.path.join(path, PROJECT_FILENAME)
            if os.path.isfile(project_file):
                project_root = os.path.abspath(path)
            else:
                # Search upward from this directory
                project_root = find_project_root(path)
                if project_root is None:
                    raise FileNotFoundError(
                        f"Could not find {PROJECT_FILENAME} in {path} or any parent directory"
                    )
        else:
            raise FileNotFoundError(f"Path does not exist: {path}")

        project_file = os.path.join(project_root, PROJECT_FILENAME)

        # Read and parse the file
        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        try:
            parsed = read_str(content)
        except Exception as e:
            raise ValueError(f"Failed to parse {project_file}: {e}") from e

        # read_str returns a list of all forms in the file
        # We need to find the first map (the config)
        if isinstance(parsed, list):
            # Find the first MapLiteral in the list
            config_form = None
            for form in parsed:
                if isinstance(form, MapLiteral):
                    config_form = form
                    break
            if config_form is None:
                raise ValueError(f"{project_file} must contain a map as the main form")
            parsed = config_form

        # Preserve string-only command keys before generic keyword conversion.
        if isinstance(parsed, MapLiteral):
            _validate_raw_command_names(parsed)

        # Convert to Python types
        config_dict = spork_to_python(parsed)

        if not isinstance(config_dict, dict):
            raise ValueError(
                f"{project_file} must contain a map, got {type(parsed).__name__}"
            )

        # Validate required fields
        if "name" not in config_dict:
            raise ValueError(f"{project_file} is missing required field :name")
        if "version" not in config_dict:
            raise ValueError(f"{project_file} is missing required field :version")

        # Extract fields with defaults
        name = config_dict["name"]
        version = config_dict["version"]
        description = config_dict.get("description")
        dependencies = config_dict.get("dependencies", [])
        dev_dependencies = config_dict.get("dev-dependencies", [])
        source_paths = config_dict.get("source-paths", DEFAULT_SOURCE_PATHS.copy())
        test_paths = config_dict.get("test-paths", DEFAULT_TEST_PATHS.copy())
        main = config_dict.get("main")
        requires_python = config_dict.get(
            "requires-python", DEFAULT_REQUIRES_PYTHON
        )
        readme = config_dict.get("readme")
        license_value = config_dict.get("license")
        license_file = config_dict.get("license-file")
        authors = config_dict.get("authors", [])
        keywords = config_dict.get("keywords", [])
        classifiers = config_dict.get("classifiers", [])
        urls = config_dict.get("urls", {})
        optional_dependencies = config_dict.get("optional-dependencies", {})
        spork_version = config_dict.get("spork-version")
        api_value = config_dict.get("api")
        commands_value = config_dict.get("commands", {})
        if "python-api" in config_dict:
            raise ValueError(":python-api was replaced by :api in spork-lang 0.4")

        # Validate types
        if not isinstance(name, str):
            raise ValueError(f":name must be a string, got {type(name).__name__}")
        if not isinstance(version, str):
            raise ValueError(f":version must be a string, got {type(version).__name__}")
        if description is not None and not isinstance(description, str):
            raise ValueError(
                f":description must be a string, got {type(description).__name__}"
            )
        def validate_string_list(field_name: str, value: Any) -> None:
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f":{field_name} must be a vector of strings")

        validate_string_list("dependencies", dependencies)
        validate_string_list("dev-dependencies", dev_dependencies)
        validate_string_list("source-paths", source_paths)
        validate_string_list("test-paths", test_paths)
        validate_string_list("keywords", keywords)
        validate_string_list("classifiers", classifiers)

        for field_name, value in (
            ("main", main),
            ("requires-python", requires_python),
            ("readme", readme),
            ("license", license_value),
            ("license-file", license_file),
            ("spork-version", spork_version),
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f":{field_name} must be a string, got {type(value).__name__}"
                )

        if spork_version is not None:
            try:
                SpecifierSet(spork_version)
            except InvalidSpecifier as error:
                raise ValueError(
                    ":spork-version must be a version specifier such as "
                    '\">=0.6,<0.7\"'
                ) from error

        if not isinstance(authors, list) or not all(
            isinstance(author, dict)
            and bool(author)
            and all(
                key in {"name", "email"} and isinstance(value, str)
                for key, value in author.items()
            )
            for author in authors
        ):
            raise ValueError(
                ":authors must be a vector of maps containing string :name/:email values"
            )
        if not isinstance(urls, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in urls.items()
        ):
            raise ValueError(":urls must be a map of string keys and values")
        if not isinstance(optional_dependencies, dict):
            raise ValueError(":optional-dependencies must be a map")
        for extra, requirements in optional_dependencies.items():
            if not isinstance(extra, str):
                raise ValueError(":optional-dependencies keys must be strings or keywords")
            validate_string_list(f"optional-dependencies {extra}", requirements)

        api = None
        if api_value is not None:
            if not isinstance(api_value, dict):
                raise ValueError(":api must be a map")
            allowed_api_keys = {"from", "spork", "python"}
            unknown_keys = set(api_value).difference(allowed_api_keys)
            if unknown_keys:
                unknown = ", ".join(f":{key}" for key in sorted(unknown_keys))
                raise ValueError(f":api contains unknown fields: {unknown}")

            source_module = api_value.get("from")
            if not isinstance(source_module, str) or not source_module:
                raise ValueError(":api :from must be a non-empty string")

            spork_api = None
            spork_api_value = api_value.get("spork")
            if spork_api_value is not None:
                if not isinstance(spork_api_value, dict):
                    raise ValueError(":api :spork must be a map")
                unknown_keys = set(spork_api_value).difference(
                    {"namespace", "exports"}
                )
                if unknown_keys:
                    unknown = ", ".join(f":{key}" for key in sorted(unknown_keys))
                    raise ValueError(
                        f":api :spork contains unknown fields: {unknown}"
                    )
                namespace = spork_api_value.get("namespace")
                spork_exports = spork_api_value.get("exports")
                if not isinstance(namespace, str) or not namespace:
                    raise ValueError(
                        ":api :spork :namespace must be a non-empty string"
                    )
                validate_string_list("api :spork :exports", spork_exports)
                if not spork_exports:
                    raise ValueError(":api :spork :exports must not be empty")
                spork_api = SporkAPIConfig(
                    namespace=namespace,
                    exports=spork_exports,
                )

            python_api = None
            python_api_value = api_value.get("python")
            if python_api_value is not None:
                if not isinstance(python_api_value, dict):
                    raise ValueError(":api :python must be a map")
                allowed_python_api_keys = {
                    "package",
                    "exports",
                    "aliases",
                    "version",
                    "typed",
                }
                unknown_keys = set(python_api_value).difference(
                    allowed_python_api_keys
                )
                if unknown_keys:
                    unknown = ", ".join(f":{key}" for key in sorted(unknown_keys))
                    raise ValueError(
                        f":api :python contains unknown fields: {unknown}"
                    )

                package = python_api_value.get("package")
                python_exports = python_api_value.get("exports")
                aliases = python_api_value.get("aliases", {})
                include_version = python_api_value.get("version", True)
                typed = python_api_value.get("typed", True)

                if not isinstance(package, str) or not package:
                    raise ValueError(
                        ":api :python :package must be a non-empty string"
                    )
                validate_string_list("api :python :exports", python_exports)
                if not python_exports:
                    raise ValueError(":api :python :exports must not be empty")
                if not isinstance(aliases, dict) or not all(
                    isinstance(source, str)
                    and isinstance(public, str)
                    and source
                    and public
                    for source, public in aliases.items()
                ):
                    raise ValueError(
                        ":api :python :aliases must be a map of non-empty "
                        "string names"
                    )
                if not isinstance(include_version, bool):
                    raise ValueError(":api :python :version must be true or false")
                if not isinstance(typed, bool):
                    raise ValueError(":api :python :typed must be true or false")

                python_api = PythonAPIConfig(
                    package=package,
                    exports=python_exports,
                    aliases=aliases,
                    include_version=include_version,
                    typed=typed,
                )

            if spork_api is None and python_api is None:
                raise ValueError(":api must contain :spork, :python, or both")
            api = APIConfig(
                source_module=source_module,
                spork=spork_api,
                python=python_api,
            )

        commands = _parse_commands(commands_value)

        return cls(
            name=name,
            version=version,
            project_root=project_root,
            description=description,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            source_paths=source_paths,
            test_paths=test_paths,
            main=main,
            requires_python=requires_python,
            readme=readme,
            license=license_value,
            license_file=license_file,
            authors=authors,
            keywords=keywords,
            classifiers=classifiers,
            urls=urls,
            optional_dependencies=optional_dependencies,
            spork_version=spork_version,
            api=api,
            commands=commands,
            _raw=config_dict,
        )


def load_config(path: Optional[str] = None) -> ProjectConfig:
    """
    Convenience function to load a ProjectConfig.

    Args:
        path: Path to spork.it file, directory containing it, or None to search
              from current directory upward.

    Returns:
        Loaded ProjectConfig instance.
    """
    return ProjectConfig.load(path)
