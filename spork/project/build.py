"""
spork.project.build - Build Spork projects to Python

This module handles the `spork build` command which compiles .spork files
to Python source code with source maps.

Output structure:
    .spork-out/
        pyproject.toml
        <package>/
            __init__.py
            module.py
            module.spork.map.json
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Directories to skip when discovering modules
SKIP_DIRS = {
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".spork-out",
    "build",
    "dist",
    ".eggs",
    "*.egg-info",
    "node_modules",
}


@dataclass
class BuildResult:
    """Result of building a single module."""

    spork_path: Path
    python_path: Path
    source_map_path: Path
    module_name: str
    success: bool
    error: Optional[str] = None


@dataclass
class ProjectBuildResult:
    """Result of building an entire project."""

    out_dir: Path
    modules: list[BuildResult]
    total: int
    success_count: int
    failure_count: int

    @property
    def success(self) -> bool:
        return self.failure_count == 0


def find_project_root() -> Optional[Path]:
    """
    Find the project root by looking for spork.it.

    Returns the directory containing spork.it, or None if not found.
    """
    current = Path.cwd()

    while True:
        if (current / "spork.it").is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def get_source_roots(project_root: Path) -> list[Path]:
    """
    Get source roots for a project.

    If spork.it exists and has :source-paths, use those.
    Otherwise, default to ["src", "."] (if they exist).
    """
    spork_it = project_root / "spork.it"

    if spork_it.is_file():
        try:
            from spork.project.config import ProjectConfig

            config = ProjectConfig.load(str(project_root))
            return [Path(p) for p in config.get_absolute_source_paths()]
        except Exception:
            pass

    # Default source roots
    roots = []
    src_dir = project_root / "src"
    if src_dir.is_dir():
        roots.append(src_dir)

    # Also check project root, but be conservative
    if not roots:
        roots.append(project_root)

    return roots


def should_skip_dir(name: str) -> bool:
    """Check if a directory should be skipped during module discovery."""
    if name.startswith("."):
        return True
    if name in SKIP_DIRS:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def discover_spork_files(source_root: Path) -> list[Path]:
    """
    Discover all .spork files under a source root.

    Skips common non-source directories like .venv, build, etc.
    """
    spork_files = []

    for root, dirs, files in os.walk(source_root):
        # Filter out directories to skip
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]

        for file in files:
            if file.endswith(".spork"):
                spork_files.append(Path(root) / file)

    return spork_files


def path_to_module_name(spork_path: Path, source_root: Path) -> str:
    """
    Convert a .spork file path to a module name.

    Example:
        source_root = /project/src
        spork_path = /project/src/my_app/core.spork
        -> "my_app.core"
    """
    rel_path = spork_path.relative_to(source_root)
    # Remove .spork extension
    stem = str(rel_path)[: -len(".spork")]
    # Replace path separators with dots
    module_name = stem.replace(os.sep, ".").replace("/", ".")
    return module_name


def module_name_to_path(module_name: str) -> Path:
    """
    Convert a module name to a relative path (without extension).

    Example:
        "my_app.core" -> Path("my_app/core")
    """
    return Path(module_name.replace(".", os.sep))


def compile_module(
    spork_path: Path,
    source_root: Path,
    out_dir: Path,
) -> BuildResult:
    """
    Compile a single .spork file to Python.

    Args:
        spork_path: Path to the .spork file
        source_root: The source root this file is under
        out_dir: Output directory (.spork-out)

    Returns:
        BuildResult with success/failure info
    """
    from spork.compiler.loader import compile_path_to_python

    module_name = path_to_module_name(spork_path, source_root)
    rel_path = module_name_to_path(module_name)

    python_path = out_dir / rel_path.with_suffix(".py")
    source_map_path = out_dir / (str(rel_path) + ".spork.map.json")

    try:
        # Compile
        python_source, source_map = compile_path_to_python(spork_path)

        # Add python_file to source map
        source_map["python_file"] = str(rel_path.with_suffix(".py"))

        # Ensure output directories exist
        python_path.parent.mkdir(parents=True, exist_ok=True)

        # Write Python source
        with open(python_path, "w", encoding="utf-8") as f:
            f.write(python_source)
            f.write("\n")  # Ensure trailing newline

        # Write source map
        with open(source_map_path, "w", encoding="utf-8") as f:
            json.dump(source_map, f, indent=2)
            f.write("\n")

        return BuildResult(
            spork_path=spork_path,
            python_path=python_path,
            source_map_path=source_map_path,
            module_name=module_name,
            success=True,
        )

    except Exception as e:
        return BuildResult(
            spork_path=spork_path,
            python_path=python_path,
            source_map_path=source_map_path,
            module_name=module_name,
            success=False,
            error=str(e),
        )


def generate_pyproject_toml(
    out_dir: Path,
    project_root: Path,
    name: Optional[str] = None,
    version: Optional[str] = None,
) -> None:
    """
    Generate a minimal pyproject.toml in the output directory.

    This allows Python tools (mypy, ruff, etc.) to treat the output
    as a valid Python project.
    """
    # Try to get project info from spork.it
    if name is None or version is None:
        try:
            from spork.project.config import ProjectConfig

            config = ProjectConfig.load(str(project_root))
            if name is None:
                name = config.name
            if version is None:
                version = config.version
        except Exception:
            pass

    # Defaults
    if name is None:
        name = "spork-out"
    if version is None:
        version = "0.0.0"

    # Compute relative path to project root
    try:
        rel_to_root = os.path.relpath(project_root, out_dir)
    except ValueError:
        rel_to_root = str(project_root)

    content = f'''[project]
name = "{name}"
version = "{version}"
description = "Compiled output from Spork (.spork-out)"
requires-python = ">=3.9"

[tool.spork]
source-root = "{rel_to_root}"
generated = true
'''

    pyproject_path = out_dir / "pyproject.toml"
    with open(pyproject_path, "w", encoding="utf-8") as f:
        f.write(content)


def ensure_init_files(out_dir: Path) -> None:
    """
    Ensure __init__.py files exist in all package directories.

    This makes the output directory a proper Python package structure.
    """
    for root, dirs, files in os.walk(out_dir):
        root_path = Path(root)
        # Skip the top-level .spork-out directory itself
        if root_path == out_dir:
            continue

        # Check if this directory contains any .py files or subdirectories
        has_python = any(f.endswith(".py") for f in files)
        has_subdirs = len(dirs) > 0

        if has_python or has_subdirs:
            init_path = root_path / "__init__.py"
            if not init_path.exists():
                init_path.touch()


def build_project(
    out_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
    clean: bool = False,
    verbose: bool = True,
) -> ProjectBuildResult:
    """
    Build a Spork project to Python.

    Args:
        out_dir: Output directory (default: .spork-out)
        project_root: Project root (default: auto-detect from spork.it)
        clean: If True, remove existing output directory first
        verbose: If True, print progress

    Returns:
        ProjectBuildResult with build statistics
    """
    # Determine project root
    if project_root is None:
        project_root = find_project_root()
        if project_root is None:
            project_root = Path.cwd()

    # Determine output directory
    if out_dir is None:
        out_dir = project_root / ".spork-out"

    # Clean if requested
    if clean and out_dir.exists():
        if verbose:
            print(f"Cleaning {out_dir}")
        shutil.rmtree(out_dir)

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Get source roots
    source_roots = get_source_roots(project_root)

    if verbose:
        print(f"Project root: {project_root}")
        print(f"Output directory: {out_dir}")
        print(f"Source roots: {[str(r) for r in source_roots]}")
        print()

    # Discover and compile all .spork files
    results = []

    for source_root in source_roots:
        if not source_root.exists():
            continue

        spork_files = discover_spork_files(source_root)

        for spork_path in spork_files:
            if verbose:
                rel_path = spork_path.relative_to(project_root)
                print(f"Compiling {rel_path}...", end=" ")

            result = compile_module(spork_path, source_root, out_dir)
            results.append(result)

            if verbose:
                if result.success:
                    print("✓")
                else:
                    print(f"✗ {result.error}")

    # Generate pyproject.toml
    generate_pyproject_toml(out_dir, project_root)

    # Ensure __init__.py files exist
    ensure_init_files(out_dir)

    # Calculate statistics
    success_count = sum(1 for r in results if r.success)
    failure_count = sum(1 for r in results if not r.success)

    if verbose:
        print()
        print(f"Build complete: {success_count} succeeded, {failure_count} failed")

    return ProjectBuildResult(
        out_dir=out_dir,
        modules=results,
        total=len(results),
        success_count=success_count,
        failure_count=failure_count,
    )
