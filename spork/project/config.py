"""
spork.project.config - Project configuration loader

This module handles parsing and loading spork.it project manifest files.
It provides the ProjectConfig class which holds all project metadata
and configuration.

The spork.it file uses Spork map syntax:
    {:name "my-project"
     :version "0.1.0"
     :description "A sample project"
     :dependencies ["requests" "numpy>=1.20"]
     :source-paths ["src"]
     :test-paths ["tests"]
     :main "my-project.core/main"}
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from spork.compiler.reader import read_str
from spork.runtime.types import Keyword, MapLiteral, VectorLiteral

# Default configuration values
DEFAULT_SOURCE_PATHS = ["src"]
DEFAULT_TEST_PATHS = ["tests"]
PROJECT_FILENAME = "spork.it"


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
        dependencies: List of dependency specifications (pip-style)
        source_paths: List of source directories (default: ["src"])
        test_paths: List of test directories (default: ["tests"])
        main: Entry point function (e.g., "my-app.core/main")

    Computed fields:
        project_root: Absolute path to the directory containing spork.it
    """

    name: str
    version: str
    project_root: str
    description: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=lambda: DEFAULT_SOURCE_PATHS.copy())
    test_paths: list[str] = field(default_factory=lambda: DEFAULT_TEST_PATHS.copy())
    main: Optional[str] = None

    # Store the raw config for any additional fields
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

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
        source_paths = config_dict.get("source-paths", DEFAULT_SOURCE_PATHS.copy())
        test_paths = config_dict.get("test-paths", DEFAULT_TEST_PATHS.copy())
        main = config_dict.get("main")

        # Validate types
        if not isinstance(name, str):
            raise ValueError(f":name must be a string, got {type(name).__name__}")
        if not isinstance(version, str):
            raise ValueError(f":version must be a string, got {type(version).__name__}")
        if description is not None and not isinstance(description, str):
            raise ValueError(
                f":description must be a string, got {type(description).__name__}"
            )
        if not isinstance(dependencies, list):
            raise ValueError(
                f":dependencies must be a vector, got {type(dependencies).__name__}"
            )
        if not isinstance(source_paths, list):
            raise ValueError(
                f":source-paths must be a vector, got {type(source_paths).__name__}"
            )
        if not isinstance(test_paths, list):
            raise ValueError(
                f":test-paths must be a vector, got {type(test_paths).__name__}"
            )
        if main is not None and not isinstance(main, str):
            raise ValueError(f":main must be a string, got {type(main).__name__}")

        return cls(
            name=name,
            version=version,
            project_root=project_root,
            description=description,
            dependencies=dependencies,
            source_paths=source_paths,
            test_paths=test_paths,
            main=main,
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
