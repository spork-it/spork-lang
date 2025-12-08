"""
spork.project.dist - Create distributions from compiled Spork projects

This module handles the `spork dist` command which creates wheel and sdist
archives from the compiled .spork-out directory.

Output structure:
    dist/
        <project>-<version>-py3-none-any.whl
        <project>-<version>.tar.gz
"""

import os
import shutil
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spork.project.build import build_project, find_project_root
from spork.project.config import ProjectConfig


@dataclass
class DistResult:
    """Result of creating distributions."""

    wheel_path: Optional[Path]
    sdist_path: Optional[Path]
    dist_dir: Path
    success: bool
    error: Optional[str] = None


def generate_dist_pyproject(
    out_dir: Path,
    config: ProjectConfig,
) -> Path:
    """
    Generate a pyproject.toml suitable for building a wheel.

    This creates a more complete pyproject.toml than the one used
    for linting, with proper metadata for distribution.
    """
    # Normalize project name for PyPI (hyphens to underscores for package name)
    package_name = config.name.replace("-", "_")

    # Get description
    description = config.description or f"Spork project: {config.name}"

    # Build dependencies list
    deps_str = ""
    if config.dependencies:
        deps_list = ",\n    ".join(f'"{dep}"' for dep in config.dependencies)
        deps_str = f"""
dependencies = [
    {deps_list}
]"""

    content = f'''[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{config.name}"
version = "{config.version}"
description = "{description}"
requires-python = ">=3.9"
{deps_str}

[tool.setuptools]
packages = ["{package_name}"]

[tool.setuptools.package-data]
"*" = ["*.spork.map.json"]
'''

    pyproject_path = out_dir / "pyproject.toml"
    with open(pyproject_path, "w", encoding="utf-8") as f:
        f.write(content)

    return pyproject_path


# Directories to skip when discovering packages in .spork-out
SKIP_PACKAGE_DIRS = {"build", "dist", "__pycache__", ".git", ".venv", "venv"}


def discover_packages(out_dir: Path) -> list[str]:
    """
    Discover all Python packages in the output directory.

    Returns a list of package names (directories containing __init__.py).
    """
    packages = []

    for root, dirs, files in os.walk(out_dir):
        # Skip hidden directories, __pycache__, and build artifacts
        dirs[:] = [
            d for d in dirs if not d.startswith(".") and d not in SKIP_PACKAGE_DIRS
        ]

        if "__init__.py" in files:
            rel_path = Path(root).relative_to(out_dir)
            package_name = str(rel_path).replace(os.sep, ".")
            packages.append(package_name)

    return packages


def generate_setup_py(out_dir: Path, packages: list[str]) -> Path:
    """
    Generate a minimal setup.py for compatibility.
    """
    content = """from setuptools import setup
setup()
"""
    setup_path = out_dir / "setup.py"
    with open(setup_path, "w", encoding="utf-8") as f:
        f.write(content)
    return setup_path


def build_wheel(
    out_dir: Path,
    dist_dir: Path,
    verbose: bool = True,
) -> Optional[Path]:
    """
    Build a wheel from the .spork-out directory.

    Returns the path to the wheel file, or None on failure.
    """
    try:
        import build
        from build import ProjectBuilder

        builder = ProjectBuilder(str(out_dir))
        wheel_path = builder.build("wheel", str(dist_dir))
        return Path(wheel_path)

    except ImportError as e:
        if verbose:
            print(f"build module not available: {e}", file=sys.stderr)
        return None
    except Exception as e:
        if verbose:
            print(f"Error building wheel: {e}", file=sys.stderr)
        return None


def build_sdist(
    out_dir: Path,
    dist_dir: Path,
    config: ProjectConfig,
    verbose: bool = True,
) -> Optional[Path]:
    """
    Build a source distribution (tarball) from the .spork-out directory.

    Returns the path to the sdist file, or None on failure.
    """
    try:
        import build
        from build import ProjectBuilder

        builder = ProjectBuilder(str(out_dir))
        sdist_path = builder.build("sdist", str(dist_dir))
        return Path(sdist_path)

    except ImportError:
        # Fallback: create tarball manually
        if verbose:
            print(
                "build module not available, creating tarball manually", file=sys.stderr
            )
        try:
            sdist_name = f"{config.name}-{config.version}"
            sdist_path = dist_dir / f"{sdist_name}.tar.gz"

            with tarfile.open(sdist_path, "w:gz") as tar:
                for item in out_dir.iterdir():
                    if item.name.startswith("."):
                        continue
                    tar.add(item, arcname=f"{sdist_name}/{item.name}")

            return sdist_path
        except Exception as e:
            if verbose:
                print(f"Error creating tarball: {e}", file=sys.stderr)
            return None

    except Exception as e:
        if verbose:
            print(f"Error building sdist: {e}", file=sys.stderr)
        return None


def create_dist(
    out_dir: Optional[Path] = None,
    dist_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
    build_first: bool = True,
    clean: bool = False,
    wheel: bool = True,
    sdist: bool = True,
    verbose: bool = True,
) -> DistResult:
    """
    Create distribution packages from a Spork project.

    Args:
        out_dir: The .spork-out directory (default: auto-detect)
        dist_dir: Output directory for distributions (default: dist/)
        project_root: Project root (default: auto-detect)
        build_first: Run `spork build` before creating dist
        clean: Clean dist directory before building
        wheel: Build a wheel
        sdist: Build a source distribution
        verbose: Print progress

    Returns:
        DistResult with paths to created distributions
    """
    # Determine project root
    if project_root is None:
        project_root = find_project_root()
        if project_root is None:
            return DistResult(
                wheel_path=None,
                sdist_path=None,
                dist_dir=Path("dist"),
                success=False,
                error="No spork.it found. Are you in a Spork project?",
            )

    # Load project config
    try:
        config = ProjectConfig.load(str(project_root))
    except Exception as e:
        return DistResult(
            wheel_path=None,
            sdist_path=None,
            dist_dir=Path("dist"),
            success=False,
            error=f"Failed to load project config: {e}",
        )

    # Determine directories
    if out_dir is None:
        out_dir = project_root / ".spork-out"

    if dist_dir is None:
        dist_dir = project_root / "dist"

    # Build first if requested
    if build_first:
        if verbose:
            print("Building project...")
        build_result = build_project(
            out_dir=out_dir,
            project_root=project_root,
            clean=False,
            verbose=verbose,
        )
        if not build_result.success:
            return DistResult(
                wheel_path=None,
                sdist_path=None,
                dist_dir=dist_dir,
                success=False,
                error=f"Build failed: {build_result.failure_count} files failed to compile",
            )

    # Check that .spork-out exists
    if not out_dir.exists():
        return DistResult(
            wheel_path=None,
            sdist_path=None,
            dist_dir=dist_dir,
            success=False,
            error=f"Output directory {out_dir} does not exist. Run `spork build` first.",
        )

    # Clean dist directory if requested
    if clean and dist_dir.exists():
        if verbose:
            print(f"Cleaning {dist_dir}")
        shutil.rmtree(dist_dir)

    # Create dist directory
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Generate proper pyproject.toml for distribution
    if verbose:
        print("Generating distribution metadata...")
    generate_dist_pyproject(out_dir, config)

    # Discover packages and update pyproject.toml if needed
    packages = discover_packages(out_dir)
    if verbose:
        print(f"Found packages: {packages}")

    # Generate setup.py for compatibility
    generate_setup_py(out_dir, packages)

    wheel_path = None
    sdist_path = None

    # Build wheel
    if wheel:
        if verbose:
            print("Building wheel...")
        wheel_path = build_wheel(out_dir, dist_dir, verbose)
        if wheel_path:
            if verbose:
                print(f"  ✓ Created {wheel_path.name}")
        else:
            if verbose:
                print("  ✗ Failed to create wheel")

    # Build sdist
    if sdist:
        if verbose:
            print("Building source distribution...")
        sdist_path = build_sdist(out_dir, dist_dir, config, verbose)
        if sdist_path:
            if verbose:
                print(f"  ✓ Created {sdist_path.name}")
        else:
            if verbose:
                print("  ✗ Failed to create sdist")

    success = (not wheel or wheel_path is not None) and (
        not sdist or sdist_path is not None
    )

    if verbose:
        print()
        if success:
            print(f"Distributions created in: {dist_dir}")
        else:
            print("Some distributions failed to build")

    return DistResult(
        wheel_path=wheel_path,
        sdist_path=sdist_path,
        dist_dir=dist_dir,
        success=success,
    )
