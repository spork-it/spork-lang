"""
spork.project.manager - Project environment and dependency management

This module provides the ProjectManager class which handles:
- Virtual environment creation and management
- Dependency installation via pip
- Runtime injection (ensuring spork-runtime is always available)

The manager ensures that user projects run in isolated environments
while the Spork toolchain itself runs globally.
"""

import os
import subprocess
import sys
import venv
from typing import Optional

from spork.project.config import ProjectConfig


class ProjectManager:
    """
    Manages the project environment including virtual environment and dependencies.

    This class handles:
    - Creating and validating virtual environments
    - Installing dependencies from spork.it
    - Ensuring the spork-runtime is available in the project environment
    """

    def __init__(self, config: ProjectConfig):
        """
        Initialize a ProjectManager with a project configuration.

        Args:
            config: A loaded ProjectConfig instance
        """
        self.config = config

    @property
    def venv_path(self) -> str:
        """Path to the project's virtual environment."""
        return self.config.venv_path

    @property
    def venv_python(self) -> str:
        """Path to the Python executable in the venv."""
        return self.config.venv_python

    @property
    def venv_pip(self) -> str:
        """Path to the pip executable in the venv."""
        return self.config.venv_pip

    def has_venv(self) -> bool:
        """Check if the virtual environment exists and is valid."""
        return self.config.has_venv()

    def create_venv(self, with_pip: bool = True, upgrade_pip: bool = True) -> bool:
        """
        Create a new virtual environment for the project.

        Args:
            with_pip: Whether to include pip in the venv (default: True)
            upgrade_pip: Whether to upgrade pip after creation (default: True)

        Returns:
            True if venv was created successfully, False otherwise.

        Raises:
            RuntimeError: If venv creation fails.
        """
        print(f"Creating virtual environment at {self.venv_path}...")

        try:
            # Create the venv using Python's venv module
            builder = venv.EnvBuilder(
                system_site_packages=False,
                clear=False,
                symlinks=(os.name != "nt"),  # Use symlinks on Unix, copies on Windows
                with_pip=with_pip,
            )
            builder.create(self.venv_path)
        except Exception as e:
            raise RuntimeError(f"Failed to create virtual environment: {e}") from e

        # Verify it was created
        if not self.has_venv():
            raise RuntimeError(
                f"Virtual environment was not created properly at {self.venv_path}"
            )

        print("  ✓ Created virtual environment")

        # Upgrade pip if requested
        if with_pip and upgrade_pip:
            try:
                self._run_pip(["install", "--upgrade", "pip"], quiet=True)
                print("  ✓ Upgraded pip")
            except Exception as e:
                # Non-fatal, just warn
                print(f"  ⚠ Could not upgrade pip: {e}")

        return True

    def ensure_venv(self) -> bool:
        """
        Ensure the virtual environment exists, creating it if necessary.

        Returns:
            True if venv exists (was already present or just created).
        """
        if self.has_venv():
            return True
        return self.create_venv()

    def _run_pip(
        self,
        args: list[str],
        quiet: bool = False,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Run a pip command in the project's virtual environment.

        Args:
            args: Arguments to pass to pip
            quiet: If True, suppress output
            capture_output: If True, capture stdout/stderr

        Returns:
            CompletedProcess instance with the result.

        Raises:
            RuntimeError: If pip is not available or command fails.
        """
        if not self.has_venv():
            raise RuntimeError(
                f"Virtual environment does not exist at {self.venv_path}. "
                "Run 'spork sync' to create it."
            )

        # Use the venv's Python with -m pip for reliability
        cmd = [self.venv_python, "-m", "pip"] + args

        if quiet:
            cmd.insert(3, "-q")  # After "pip"

        try:
            result = subprocess.run(
                cmd,
                cwd=self.config.project_root,
                capture_output=capture_output,
                text=True,
                check=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            raise RuntimeError(f"pip command failed: {error_msg}") from e
        except FileNotFoundError:
            raise RuntimeError(
                f"Python executable not found at {self.venv_python}"
            ) from None

    def install_dependencies(
        self,
        include_runtime: bool = True,
        dev: bool = False,
        quiet: bool = False,
    ) -> bool:
        """
        Install all dependencies from the project configuration.

        This method:
        1. Ensures the venv exists
        2. Installs all dependencies from spork.it
        3. Installs spork-runtime (unless disabled)

        Args:
            include_runtime: Whether to install spork-runtime (default: True)
            dev: Whether to install dev dependencies (for future use)
            quiet: Suppress pip output

        Returns:
            True if all dependencies were installed successfully.
        """
        # Ensure venv exists
        self.ensure_venv()

        dependencies = list(self.config.dependencies)

        # Add spork to dependencies so the project can run independently
        spork_installed = False
        if include_runtime:
            install_spec = self._get_spork_install_spec()
            if install_spec:
                # Editable install from source
                dependencies.insert(0, install_spec)
                spork_installed = True
            else:
                # Will install via copy after other dependencies
                pass

        # Check if we have anything to do
        needs_spork_copy = include_runtime and not spork_installed

        if not dependencies and not needs_spork_copy:
            print("No dependencies to install.")
            return True

        if dependencies:
            print(f"Installing {len(dependencies)} dependencies...")

        # Build pip install command
        install_args = ["install"]

        for dep in dependencies:
            if dep.startswith("-e "):
                # Editable install - need to handle specially
                editable_path = dep[3:]
                try:
                    self._run_pip(["install", "-e", editable_path], quiet=quiet)
                    print(f"  ✓ Installed {editable_path} (editable)")
                except RuntimeError as e:
                    print(f"  ✗ Failed to install {editable_path}: {e}")
                    return False
            else:
                install_args.append(dep)

        # Install non-editable dependencies in one batch
        regular_deps = [d for d in dependencies if not d.startswith("-e ")]
        if regular_deps:
            try:
                self._run_pip(["install"] + regular_deps, quiet=quiet)
                for dep in regular_deps:
                    print(f"  ✓ Installed {dep}")
            except RuntimeError as e:
                print(f"  ✗ Failed to install dependencies: {e}")
                return False

        # Install spork by copying from current environment if not already done
        if needs_spork_copy:
            if not self._install_spork_from_current_env(quiet=quiet):
                return False

        print("✓ All dependencies installed")
        return True

    def _find_spork_source_dir(self) -> Optional[str]:
        """
        Find the spork source directory for editable/development installs.

        Looks for a pyproject.toml that indicates this is the spork source tree.

        Returns:
            Path to spork source directory, or None if not found.
        """
        # Try to find spork package relative to this file
        # This handles the case when running from source
        this_file = os.path.abspath(__file__)
        spork_project_dir = os.path.dirname(os.path.dirname(os.path.dirname(this_file)))

        # Check if it looks like a valid spork source directory
        pyproject_path = os.path.join(spork_project_dir, "pyproject.toml")
        if os.path.isfile(pyproject_path):
            try:
                with open(pyproject_path) as f:
                    content = f.read()
                    if 'name = "spork-lang"' in content:
                        return spork_project_dir
            except Exception:
                pass

        return None

    def _find_spork_install_location(self) -> Optional[str]:
        """
        Find where the spork package is installed.

        This looks for the installed spork package location, which can be used
        to install spork into the project venv by copying from the current environment.

        Returns:
            Path to the directory containing the installed spork package, or None.
        """
        try:
            import spork

            # Get the directory containing the spork package
            spork_init = getattr(spork, "__file__", None)
            if spork_init:
                # spork/__init__.py -> spork/ -> site-packages/
                spork_pkg_dir = os.path.dirname(spork_init)
                site_packages = os.path.dirname(spork_pkg_dir)
                return site_packages
        except ImportError:
            pass

        return None

    def _install_spork_from_current_env(self, quiet: bool = False) -> bool:
        """
        Install spork into the project venv by copying from the current environment.

        This method copies the spork package from wherever the currently running
        spork CLI is installed into the project's virtual environment.

        Args:
            quiet: Suppress output

        Returns:
            True if installation succeeded, False otherwise.
        """
        import shutil

        # First, check if we're running from source (editable install)
        spork_source_dir = self._find_spork_source_dir()
        if spork_source_dir:
            # Install in editable mode from local source
            try:
                self._run_pip(["install", "-e", spork_source_dir], quiet=quiet)
                print(f"  ✓ Installed spork-lang (editable from {spork_source_dir})")
                return True
            except RuntimeError as e:
                print(f"  ✗ Failed to install spork-lang: {e}")
                return False

        # Otherwise, copy the installed spork package to the project venv
        try:
            import spork

            spork_init = getattr(spork, "__file__", None)
            if not spork_init:
                print("  ✗ Could not locate spork package")
                return False

            # Source: the spork package directory
            src_spork_dir = os.path.dirname(spork_init)

            # Destination: project venv site-packages
            dest_site_packages = self.config.venv_site_packages
            if not dest_site_packages or not os.path.isdir(dest_site_packages):
                print("  ✗ Could not find project venv site-packages")
                return False

            dest_spork_dir = os.path.join(dest_site_packages, "spork")

            # Remove existing spork if present
            if os.path.exists(dest_spork_dir):
                shutil.rmtree(dest_spork_dir)

            # Copy the entire spork package
            shutil.copytree(src_spork_dir, dest_spork_dir)

            # Also copy the dist-info if it exists (for proper package metadata)
            src_site_packages = os.path.dirname(src_spork_dir)
            for item in os.listdir(src_site_packages):
                if item.startswith("spork_lang-") and item.endswith(".dist-info"):
                    src_dist_info = os.path.join(src_site_packages, item)
                    dest_dist_info = os.path.join(dest_site_packages, item)
                    if os.path.exists(dest_dist_info):
                        shutil.rmtree(dest_dist_info)
                    shutil.copytree(src_dist_info, dest_dist_info)
                    break

            print("  ✓ Installed spork-lang (copied from current environment)")
            return True

        except Exception as e:
            print(f"  ✗ Failed to install spork-lang: {e}")
            return False

    def _get_spork_install_spec(self) -> Optional[str]:
        """
        Get the pip install specification for spork-lang.

        Note: This method now returns None to signal that spork should be
        installed via _install_spork_from_current_env() instead of pip.

        Returns:
            A pip install specification string for editable installs, or None.
        """
        # Check if we're running from source (editable install)
        spork_source_dir = self._find_spork_source_dir()
        if spork_source_dir:
            return f"-e {spork_source_dir}"

        # Return None to signal that we need to use the copy method
        return None

    def get_installed_packages(self) -> list[str]:
        """
        Get a list of packages installed in the project's venv.

        Returns:
            List of package names.
        """
        if not self.has_venv():
            return []

        try:
            result = self._run_pip(["freeze"], capture_output=True, quiet=True)
            packages = []
            for line in result.stdout.strip().split("\n"):
                if line and "==" in line:
                    packages.append(line.split("==")[0])
            return packages
        except RuntimeError:
            return []

    def is_dependency_installed(self, package_name: str) -> bool:
        """
        Check if a specific package is installed in the venv.

        Args:
            package_name: Name of the package to check

        Returns:
            True if the package is installed.
        """
        installed = self.get_installed_packages()
        # Normalize package names for comparison (pip normalizes _ to -)
        normalized_name = package_name.lower().replace("_", "-")
        return any(p.lower().replace("_", "-") == normalized_name for p in installed)

    def inject_venv_paths(self) -> bool:
        """
        Inject the project's venv site-packages into sys.path.

        This allows the Spork toolchain to import packages installed
        in the project's virtual environment.

        Returns:
            True if paths were injected successfully.
        """
        site_packages = self.config.venv_site_packages
        if site_packages and os.path.isdir(site_packages):
            if site_packages not in sys.path:
                sys.path.insert(0, site_packages)
            return True
        return False

    def clean(self, venv_only: bool = True) -> bool:
        """
        Clean project artifacts.

        Args:
            venv_only: If True, only remove the venv. If False, also remove
                      other build artifacts.

        Returns:
            True if cleanup was successful.
        """
        import shutil

        if os.path.isdir(self.venv_path):
            print(f"Removing virtual environment at {self.venv_path}...")
            try:
                shutil.rmtree(self.venv_path)
                print("  ✓ Removed .venv")
            except Exception as e:
                print(f"  ✗ Failed to remove .venv: {e}")
                return False

        if not venv_only:
            # Remove other artifacts
            for artifact_dir in ["target", "dist", ".spork-out", "__pycache__"]:
                artifact_path = os.path.join(self.config.project_root, artifact_dir)
                if os.path.isdir(artifact_path):
                    try:
                        shutil.rmtree(artifact_path)
                        print(f"  ✓ Removed {artifact_dir}")
                    except Exception as e:
                        print(f"  ✗ Failed to remove {artifact_dir}: {e}")

        return True


def sync_project(config: Optional[ProjectConfig] = None) -> bool:
    """
    Convenience function to sync a project's dependencies.

    Equivalent to running 'spork sync'.

    Args:
        config: Optional ProjectConfig. If None, loads from current directory.

    Returns:
        True if sync was successful.
    """
    from spork.project.config import load_config

    if config is None:
        config = load_config()

    manager = ProjectManager(config)
    return manager.install_dependencies()
