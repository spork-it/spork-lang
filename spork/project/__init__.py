"""
spork.project - Spork Project System

This package contains the project management system for Spork, including:

- config.py: Parser for spork.it project manifest files
- manager.py: Virtual environment creation and dependency management
- scaffold.py: Project scaffolding for 'spork new'
- builder.py: Build orchestration for 'spork build' (future)

Usage:
    from spork.project import ProjectConfig, ProjectManager, load_config

    # Load project configuration
    config = load_config()  # Searches upward for spork.it

    # Create manager and sync dependencies
    manager = ProjectManager(config)
    manager.install_dependencies()

    # Create a new project
    from spork.project import create_project
    create_project("my-app", "/path/to/parent")
"""

from spork.project.build import (
    BuildResult,
    ProjectBuildResult,
    build_project,
    compile_module,
    discover_spork_files,
    generate_pyproject_toml,
    get_source_roots,
    module_name_to_path,
    path_to_module_name,
)
from spork.project.config import (
    DEFAULT_SOURCE_PATHS,
    DEFAULT_TEST_PATHS,
    PROJECT_FILENAME,
    ProjectConfig,
    find_project_root,
    load_config,
    spork_to_python,
)
from spork.project.dist import (
    DistResult,
    create_dist,
)
from spork.project.manager import (
    ProjectManager,
    sync_project,
)
from spork.project.scaffold import (
    create_project,
    generate_core_spork,
    generate_gitignore,
    generate_readme,
    generate_spork_it,
    generate_test_spork,
    name_to_dir_segment,
    name_to_ns_segment,
    normalize_project_name,
)

__all__ = [
    # Build
    "build_project",
    "BuildResult",
    "ProjectBuildResult",
    "compile_module",
    "discover_spork_files",
    "get_source_roots",
    "path_to_module_name",
    "module_name_to_path",
    "generate_pyproject_toml",
    # Dist
    "create_dist",
    "DistResult",
    # Config
    "ProjectConfig",
    "load_config",
    "find_project_root",
    "spork_to_python",
    "PROJECT_FILENAME",
    "DEFAULT_SOURCE_PATHS",
    "DEFAULT_TEST_PATHS",
    # Manager
    "ProjectManager",
    "sync_project",
    # Scaffold
    "create_project",
    "normalize_project_name",
    "name_to_ns_segment",
    "name_to_dir_segment",
    "generate_spork_it",
    "generate_core_spork",
    "generate_test_spork",
    "generate_gitignore",
    "generate_readme",
]
