"""
spork.project.dist - Create distributions from compiled Spork projects

This module handles the `spork dist` command which creates wheel and sdist
archives from the compiled .spork-out directory.

Output structure:
    dist/
        <project>-<version>-py3-none-any.whl
        <project>-<version>.tar.gz
"""

import ast
import json
import os
import shutil
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

import spork
from spork.commands import COMMAND_ENTRY_POINT_GROUP
from spork.project.build import build_project, find_project_root
from spork.project.config import ProjectConfig

SPORK_RUNTIME_REQUIREMENT = "spork-runtime>=0.1.1,<0.2.0"


@dataclass
class DistResult:
    """Result of creating distributions."""

    wheel_path: Optional[Path]
    sdist_path: Optional[Path]
    dist_dir: Path
    success: bool
    error: Optional[str] = None


def _toml_string(value: str) -> str:
    """Return a JSON-escaped string, which is also a TOML basic string."""
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: list[str], indent: str = "    ") -> list[str]:
    if not values:
        return ["[]"]
    return ["[", *(f"{indent}{_toml_string(value)}," for value in values), "]"]


def stage_project_metadata(
    out_dir: Path, project_root: Path, config: ProjectConfig
) -> Optional[str]:
    """Copy README and license files into the isolated build tree."""
    readme_name: Optional[str] = None
    readme = config.readme
    if readme is None and (project_root / "README.md").is_file():
        readme = "README.md"
    if readme:
        source = project_root / readme
        if not source.is_file():
            raise FileNotFoundError(f"Configured :readme does not exist: {source}")
        readme_name = source.name
        shutil.copy2(source, out_dir / readme_name)

    license_paths: list[Path] = []
    if config.license_file:
        license_paths.append(project_root / config.license_file)
    else:
        license_paths.extend(
            path
            for path in sorted(project_root.glob("LICENSE*"))
            if path.is_file()
        )
    for source in license_paths:
        if not source.is_file():
            raise FileNotFoundError(
                f"Configured :license-file does not exist: {source}"
            )
        shutil.copy2(source, out_dir / source.name)

    return readme_name


def generate_dist_pyproject(
    out_dir: Path,
    config: ProjectConfig,
    packages: list[str],
    readme_name: Optional[str] = None,
) -> Path:
    """Generate escaped, PyPI-ready metadata for the staged project."""
    description = config.description or f"Spork project: {config.name}"
    spork_requirement = config.spork_version or f"=={spork.__version__}"
    try:
        supported_compilers = SpecifierSet(spork_requirement)
    except InvalidSpecifier as error:
        raise ValueError(
            ":spork-version must be a version specifier such as "
            '\">=0.6,<0.7\"'
        ) from error
    if Version(spork.__version__) not in supported_compilers:
        raise ValueError(
            f"project requires spork-lang{spork_requirement}, but the active "
            f"compiler is spork-lang=={spork.__version__}"
        )
    all_dependencies = [SPORK_RUNTIME_REQUIREMENT, *config.dependencies]

    lines = [
        "[build-system]",
        'requires = ["setuptools>=77"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f"name = {_toml_string(config.name)}",
        f"version = {_toml_string(config.version)}",
        f"description = {_toml_string(description)}",
        f"requires-python = {_toml_string(config.requires_python)}",
    ]
    if readme_name:
        lines.append(f"readme = {_toml_string(readme_name)}")
    if config.license:
        lines.append(f"license = {_toml_string(config.license)}")
    if config.authors:
        author_values = []
        for author in config.authors:
            fields = ", ".join(
                f"{key} = {_toml_string(author[key])}"
                for key in ("name", "email")
                if key in author
            )
            author_values.append(f"{{ {fields} }}")
        lines.append(f"authors = [{', '.join(author_values)}]")
    if config.keywords:
        lines.append("keywords = " + "\n".join(_toml_array(config.keywords)))
    if config.classifiers:
        lines.append("classifiers = " + "\n".join(_toml_array(config.classifiers)))
    lines.append("dependencies = " + "\n".join(_toml_array(all_dependencies)))

    if config.optional_dependencies:
        lines.extend(["", "[project.optional-dependencies]"])
        for extra, requirements in config.optional_dependencies.items():
            lines.append(
                f"{_toml_string(extra)} = "
                + "\n".join(_toml_array(requirements))
            )
    if config.urls:
        lines.extend(["", "[project.urls]"])
        for label, url in config.urls.items():
            lines.append(f"{_toml_string(label)} = {_toml_string(url)}")
    if config.commands:
        lines.extend(["", f'[project.entry-points."{COMMAND_ENTRY_POINT_GROUP}"]'])
        for name, command in sorted(config.commands.items()):
            lines.append(f"{name} = {_toml_string(command.python_target)}")

    lines.extend(
        [
            "",
            "[tool.setuptools]",
            "packages = " + "\n".join(_toml_array(packages)),
            "include-package-data = false",
            "",
            "[tool.setuptools.package-data]",
            '"*" = ["*.spork", "*.spork.map.json", "*.pyi", "py.typed"]',
            "",
        ]
    )

    pyproject_path = out_dir / "pyproject.toml"
    pyproject_path.write_text("\n".join(lines), encoding="utf-8")
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
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and d not in SKIP_PACKAGE_DIRS
        )

        if "__init__.py" in files:
            rel_path = Path(root).relative_to(out_dir)
            package_name = str(rel_path).replace(os.sep, ".")
            packages.append(package_name)

    return sorted(packages)


def validate_command_sources(config: ProjectConfig) -> None:
    """Reject command targets that are not source-defined functions."""
    if not config.commands:
        return

    from spork.project.check import INVALID_COMMAND, check_project

    result = check_project(config, include_tests=False)
    invalid = [
        item.message for item in result.diagnostics if item.code == INVALID_COMMAND
    ]
    if invalid:
        raise ValueError("; ".join(invalid))


def validate_command_payload(
    out_dir: Path,
    config: ProjectConfig,
    packages: list[str],
) -> None:
    """Ensure generated entry-point modules and functions enter the distribution."""
    for name, command in sorted(config.commands.items()):
        module_name, function_name = command.python_target.split(":", 1)
        relative = Path(*module_name.split("."))
        candidates = [
            out_dir / relative.with_suffix(".py"),
            out_dir / relative / "__init__.py",
        ]
        existing = [path for path in candidates if path.is_file()]
        if not existing:
            raise ValueError(
                f":commands {name!r} generated module {module_name!r} is missing "
                "from compiled output"
            )
        if len(existing) > 1:
            raise ValueError(
                f":commands {name!r} generated module {module_name!r} is ambiguous"
            )
        if not any(
            module_name == package or module_name.startswith(f"{package}.")
            for package in packages
        ):
            raise ValueError(
                f":commands {name!r} generated module {module_name!r} is not "
                "included in a distribution package"
            )

        generated_path = existing[0]
        try:
            tree = ast.parse(generated_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError) as error:
            raise ValueError(
                f":commands {name!r} could not inspect generated module "
                f"{module_name!r}: {error}"
            ) from error
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if function_name not in functions:
            raise ValueError(
                f":commands {name!r} generated function {function_name!r} is "
                f"missing from module {module_name!r}"
            )


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
            manual_sdist_path = dist_dir / f"{sdist_name}.tar.gz"

            with tarfile.open(manual_sdist_path, "w:gz") as tar:
                for item in out_dir.iterdir():
                    if item.name.startswith("."):
                        continue
                    tar.add(item, arcname=f"{sdist_name}/{item.name}")

            return manual_sdist_path
        except Exception as e:
            if verbose:
                print(f"Error creating tarball: {e}", file=sys.stderr)
            return None

    except Exception as e:
        if verbose:
            print(f"Error building sdist: {e}", file=sys.stderr)
        return None


def _clean_staging_artifacts(out_dir: Path) -> None:
    for directory in (out_dir / "build", out_dir / "dist"):
        if directory.is_dir():
            shutil.rmtree(directory)
    for egg_info in out_dir.glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)
        else:
            egg_info.unlink()


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

    project_root = Path(project_root).resolve()

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

    try:
        validate_command_sources(config)
    except Exception as error:
        return DistResult(
            wheel_path=None,
            sdist_path=None,
            dist_dir=Path("dist"),
            success=False,
            error=f"Command validation failed: {error}",
        )

    # Determine project-relative directories consistently from any cwd.
    if out_dir is None:
        out_dir = project_root / ".spork-out"
    elif not out_dir.is_absolute():
        out_dir = project_root / out_dir
    out_dir = out_dir.resolve()

    if dist_dir is None:
        dist_dir = project_root / "dist"
    elif not dist_dir.is_absolute():
        dist_dir = project_root / dist_dir
    dist_dir = dist_dir.resolve()

    # Build first if requested
    if build_first:
        if verbose:
            print("Building project...")
        build_result = build_project(
            out_dir=out_dir,
            project_root=project_root,
            clean=clean,
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

    # Remove artifacts created inside the staging tree by previous setuptools
    # runs even when source compilation is intentionally reused.
    _clean_staging_artifacts(out_dir)

    packages = discover_packages(out_dir)
    if not packages:
        return DistResult(
            wheel_path=None,
            sdist_path=None,
            dist_dir=dist_dir,
            success=False,
            error="No Python packages were found in compiled output",
        )
    if verbose:
        print(f"Found packages: {packages}")
        print("Generating distribution metadata...")

    try:
        validate_command_payload(out_dir, config, packages)
        readme_name = stage_project_metadata(out_dir, project_root, config)
        generate_dist_pyproject(out_dir, config, packages, readme_name)
        generate_setup_py(out_dir, packages)
    except Exception as exc:
        return DistResult(
            wheel_path=None,
            sdist_path=None,
            dist_dir=dist_dir,
            success=False,
            error=f"Failed to generate distribution metadata: {exc}",
        )

    wheel_path = None
    sdist_path = None

    # Build wheel
    if wheel:
        if verbose:
            print("Building wheel...")
        wheel_path = build_wheel(out_dir, dist_dir, verbose)
        if wheel_path:
            if verbose:
                print(f"  [ok] Created {wheel_path.name}")
        else:
            if verbose:
                print("  [error] Failed to create wheel")

    # Build sdist
    if sdist:
        if verbose:
            print("Building source distribution...")
        sdist_path = build_sdist(out_dir, dist_dir, config, verbose)
        if sdist_path:
            if verbose:
                print(f"  [ok] Created {sdist_path.name}")
        else:
            if verbose:
                print("  [error] Failed to create sdist")

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
