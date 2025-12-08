"""
spork.project.scaffold - Project scaffolding

This module provides functionality for creating new Spork projects
with the standard directory structure and template files.

The scaffolding creates:
    name/
    ├── spork.it          # The project manifest
    ├── src/
    │   └── name/
    │       └── core.spork # Hello world entry point
    ├── tests/
    │   └── name/
    │       └── core_test.spork
    └── .gitignore
"""

import os
import re
import subprocess
from typing import Optional


def normalize_project_name(name: str) -> str:
    """
    Normalize a project name for use in directory and namespace names.

    Converts to lowercase, replaces underscores with hyphens,
    and removes invalid characters.

    Args:
        name: The raw project name

    Returns:
        Normalized project name suitable for use in paths and namespaces
    """
    # Convert to lowercase
    normalized = name.lower()
    # Replace underscores with hyphens (Lisp convention)
    normalized = normalized.replace("_", "-")
    # Remove any characters that aren't alphanumeric, hyphen, or dot
    normalized = re.sub(r"[^a-z0-9\-.]", "", normalized)
    # Remove leading/trailing hyphens or dots
    normalized = normalized.strip("-.")
    # Collapse multiple hyphens
    normalized = re.sub(r"-+", "-", normalized)

    if not normalized:
        raise ValueError(
            f"Invalid project name: '{name}' produces empty normalized name"
        )

    return normalized


def name_to_ns_segment(name: str) -> str:
    """
    Convert a project name to a valid namespace segment.

    Spork namespaces use dots as separators and hyphens within segments.

    Args:
        name: Project name (possibly with hyphens)

    Returns:
        A valid namespace segment
    """
    return normalize_project_name(name)


def name_to_dir_segment(name: str) -> str:
    """
    Convert a project name to a valid directory name.

    Args:
        name: Project name

    Returns:
        A valid directory name
    """
    return normalize_project_name(name)


def generate_spork_it(name: str, version: str = "0.1.0", description: str = "") -> str:
    """
    Generate the content for a spork.it project manifest file.

    Args:
        name: Project name
        version: Project version (default: "0.1.0")
        description: Project description

    Returns:
        The spork.it file content as a string
    """
    ns_name = name_to_ns_segment(name)

    desc_line = ""
    if description:
        desc_line = f'\n :description "{description}"'

    return f""";; Spork Project Manifest
;; See https://spork.it.com for more information

{{:name "{name}"
 :version "{version}"{desc_line}

 ;; Dependencies (pip-style specifications)
 :dependencies []

 ;; Source code locations
 :source-paths ["src"]

 ;; Entry point for 'spork run'
 :main "{ns_name}.core/main"}}
"""


def generate_core_spork(name: str) -> str:
    """
    Generate a hello world core.spork file.

    Args:
        name: Project name

    Returns:
        The core.spork file content
    """
    ns_name = name_to_ns_segment(name)

    return f""";; {name} - Core module
(ns {ns_name}.core)

(defn ^int main [& args]
  "Main entry point for the application."
  (print (+ "Welcome to " "{name}" "!"))
  0)
"""


def generate_test_spork(name: str) -> str:
    """
    Generate a test file for the core module.

    Args:
        name: Project name

    Returns:
        The core_test.spork file content
    """
    ns_name = name_to_ns_segment(name)

    return f""";; Tests for {ns_name}.core
(ns {ns_name}.core-test
  (:require [{ns_name}.core :as core]))

(defn test-greet []
  "Test the greet function."
  (assert (= (core/greet "Spork") "Hello, Spork!")))

(defn run-tests []
  "Run all tests."
  (print "Running tests...")
  (test-greet)
  (print "All tests passed!"))
"""


def generate_gitignore() -> str:
    """
    Generate a .gitignore file for Spork projects.

    Returns:
        The .gitignore file content
    """
    return """# Spork project artifacts
.venv/
target/
dist/
*.egg-info/

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/

# OS
.DS_Store
Thumbs.db

# REPL history
.spork_history
.nrepl-port

# Spork builds
.spork-out/
"""


def generate_readme(name: str, description: str = "") -> str:
    """
    Generate a README.md file.

    Args:
        name: Project name
        description: Project description

    Returns:
        The README.md content
    """
    desc = description or "A Spork project"

    return f"""# {name}

{desc}

## Getting Started

### Prerequisites

- Python 3.9+
- Spork language toolchain

### Installation

```bash
# Install dependencies
spork sync
```

### Usage

```bash
# Start the REPL
spork repl

# Run the main function
spork run

# Execute a specific file
spork src/{name_to_dir_segment(name)}/core.spork
```

## Project Structure

```
{name}/
├── spork.it          # Project manifest
├── src/
│   └── {name_to_dir_segment(name)}/
│       └── core.spork
├── tests/
│   └── {name_to_dir_segment(name)}/
│       └── core_test.spork
└── README.md
```

## License

MIT
"""


def create_project(
    name: str,
    parent_dir: Optional[str] = None,
    description: str = "",
    version: str = "0.1.0",
    create_git: bool = False,
) -> str:
    """
    Create a new Spork project with the standard directory structure.

    Args:
        name: Project name
        parent_dir: Parent directory to create project in (default: current directory)
        description: Project description
        version: Initial version (default: "0.1.0")
        create_git: Whether to initialize a git repository (default: True)

    Returns:
        Absolute path to the created project directory

    Raises:
        ValueError: If the project name is invalid
        FileExistsError: If the project directory already exists
        OSError: If directory creation fails
    """
    # Normalize the name
    normalized_name = normalize_project_name(name)
    dir_name = name_to_dir_segment(normalized_name)

    # Determine project path
    if parent_dir is None:
        parent_dir = os.getcwd()
    else:
        parent_dir = os.path.abspath(parent_dir)

    project_path = os.path.join(parent_dir, dir_name)

    # Check if directory already exists
    if os.path.exists(project_path):
        raise FileExistsError(f"Directory already exists: {project_path}")

    # Create directory structure
    os.makedirs(project_path)

    src_dir = os.path.join(project_path, "src", dir_name)
    os.makedirs(src_dir)

    # TODO: Re-add once we have testing infrastructure
    # tests_dir = os.path.join(project_path, "tests", dir_name)
    # os.makedirs(tests_dir)

    # Write spork.it
    spork_it_path = os.path.join(project_path, "spork.it")
    with open(spork_it_path, "w", encoding="utf-8") as f:
        f.write(generate_spork_it(normalized_name, version, description))

    # Write core.spork
    core_path = os.path.join(src_dir, "core.spork")
    with open(core_path, "w", encoding="utf-8") as f:
        f.write(generate_core_spork(normalized_name))

    # TODO: Re-add once we have testing infrastructure
    # Write core_test.spork
    # test_path = os.path.join(tests_dir, "core_test.spork")
    # with open(test_path, "w", encoding="utf-8") as f:
    #     f.write(generate_test_spork(normalized_name))

    # Write .gitignore
    gitignore_path = os.path.join(project_path, ".gitignore")
    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write(generate_gitignore())

    # Write README.md
    readme_path = os.path.join(project_path, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(generate_readme(normalized_name, description))

    # Initialize git repository if requested
    if create_git:
        try:
            subprocess.run(
                ["git", "init"],
                cwd=project_path,
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Git not available or failed, skip silently
            pass

    return project_path
