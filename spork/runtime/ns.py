"""
Spork Namespace System - Manages namespace resolution, registration, and lookup.

This module provides the infrastructure for Spork's namespace system, including:
- NAMESPACE_REGISTRY: Global registry of loaded namespaces
- SOURCE_ROOTS: Ordered list of directories to search for .spork files
- Resolution functions to map namespace names to file paths
- Registration functions to track loaded namespaces
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spork.runtime.types import normalize_name


class NamespaceProxy:
    """
    A proxy object that wraps a namespace's environment dict.

    This allows attribute-style access to namespace symbols, e.g.:
        h.add_nums  instead of  h["add_nums"]

    Also handles hyphen-to-underscore normalization for Spork names.
    """

    def __init__(self, env: dict[str, Any], ns_name: str):
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_ns_name", ns_name)

    def __getattr__(self, name: str) -> Any:
        env = object.__getattribute__(self, "_env")
        ns_name = object.__getattribute__(self, "_ns_name")

        # Try the name as-is first
        if name in env:
            return env[name]

        # Try with hyphens converted to underscores (Spork convention)
        hyphen_name = name.replace("_", "-")
        if hyphen_name in env:
            return env[hyphen_name]

        # Try underscore version
        underscore_name = name.replace("-", "_")
        if underscore_name in env:
            return env[underscore_name]

        raise AttributeError(f"Namespace '{ns_name}' has no symbol '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        env = object.__getattribute__(self, "_env")
        env[name] = value

    def __repr__(self) -> str:
        ns_name = object.__getattribute__(self, "_ns_name")
        return f"<NamespaceProxy '{ns_name}'>"

    def __dir__(self) -> list[str]:
        env = object.__getattribute__(self, "_env")
        return [k for k in env.keys() if not k.startswith("_")]


@dataclass
class NamespaceInfo:
    """Information about a loaded namespace."""

    name: str  # Fully qualified namespace name, e.g., "my.app.core"
    file: Optional[str]  # Absolute path to the .spork file, or None for built-in
    env: dict[str, Any]  # The namespace's environment dict
    macros: dict[str, Callable]  # Macros defined in this namespace
    loaded: bool = True
    timestamp: float = 0.0  # Last modification time of file when loaded
    refers: dict[str, str] = field(
        default_factory=dict
    )  # symbol -> source-ns for referred symbols
    aliases: dict[str, str] = field(
        default_factory=dict
    )  # alias -> full-ns-name for :as aliases


# Global namespace registry
# Maps namespace name (str) -> NamespaceInfo
NAMESPACE_REGISTRY: dict[str, NamespaceInfo] = {}

# Ordered list of source roots to search for .spork files
# Populated at startup from:
# 1. Directory of current file being executed
# 2. Project root (if detected)
# 3. Current working directory
# 4. $SPORK_PATH entries
# 5. CLI --source-path flags
SOURCE_ROOTS: list[str] = []


def ns_to_relpath(ns: str) -> str:
    """
    Convert a namespace name to a relative file path.

    Hyphens in namespace names are converted to underscores in file paths,
    following the Clojure convention.

    Examples:
        "my.app.core" -> "my/app/core.spork"
        "my.app-utils" -> "my/app_utils.spork"
        "spork.pds" -> "spork/pds.spork"
        "utils" -> "utils.spork"
    """
    # Split by dots, normalize each segment (hyphen -> underscore), rejoin as path
    segments = ns.split(".")
    normalized_segments = [normalize_name(seg) for seg in segments]
    return os.sep.join(normalized_segments) + ".spork"


def relpath_to_ns(relpath: str) -> str:
    """
    Convert a relative file path to a namespace name.

    Examples:
        "my/app/core.spork" -> "my.app.core"
        "utils.spork" -> "utils"
    """
    # Remove .spork extension
    if relpath.endswith(".spork"):
        relpath = relpath[:-6]
    # Convert path separators to dots
    return relpath.replace(os.sep, ".").replace("/", ".")


def _get_std_dir() -> str:
    """Get the path to the spork/std directory."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "std")


def find_spork_file_for_ns(
    ns: str, extra_roots: Optional[list[str]] = None
) -> Optional[str]:
    """
    Find the .spork file for a given namespace name.

    Searches through SOURCE_ROOTS (and any extra_roots) in order,
    looking for the corresponding .spork file.

    For std.* namespaces, also searches the spork package's std/ directory.

    Args:
        ns: The namespace name, e.g., "my.app.core"
        extra_roots: Additional directories to search (searched first)

    Returns:
        Absolute path to the .spork file if found, None otherwise.
    """
    # Handle std.* namespaces specially - look in spork/std/
    if ns.startswith("std."):
        # Convert std.string -> string.spork in std/ dir
        std_rel = ns[4:].replace(".", os.sep) + ".spork"
        std_path = os.path.join(_get_std_dir(), std_rel)
        if os.path.isfile(std_path):
            return os.path.abspath(std_path)

    rel = ns_to_relpath(ns)

    # Build search path: extra_roots first, then SOURCE_ROOTS
    search_paths = []
    if extra_roots:
        search_paths.extend(extra_roots)
    search_paths.extend(SOURCE_ROOTS)

    for root in search_paths:
        if not root:
            continue
        candidate = os.path.join(root, rel)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    return None


def find_project_root(start_path: str) -> Optional[str]:
    """
    Find the project root by walking up from start_path.

    Looks for common project markers:
    - .git directory
    - pyproject.toml
    - .spork_project file
    - setup.py

    Args:
        start_path: Path to start searching from (usually a file path)

    Returns:
        Absolute path to project root if found, None otherwise.
    """
    if os.path.isfile(start_path):
        current = os.path.dirname(os.path.abspath(start_path))
    else:
        current = os.path.abspath(start_path)

    markers = [".git", "pyproject.toml", ".spork_project", "setup.py"]

    while current != os.path.dirname(current):  # Stop at filesystem root
        for marker in markers:
            if os.path.exists(os.path.join(current, marker)):
                return current
        current = os.path.dirname(current)

    return None


def init_source_roots(
    current_file: Optional[str] = None,
    extra_paths: Optional[list[str]] = None,
    include_cwd: bool = True,
) -> None:
    """
    Initialize SOURCE_ROOTS based on context.

    This should be called at startup (e.g., in exec_file or REPL init).

    Args:
        current_file: The file being executed (if any)
        extra_paths: Additional paths from CLI --source-path flags
        include_cwd: Whether to include current working directory
    """
    global SOURCE_ROOTS
    SOURCE_ROOTS = []

    # 1. Directory of current file
    if current_file:
        file_dir = os.path.dirname(os.path.abspath(current_file))
        if file_dir and file_dir not in SOURCE_ROOTS:
            SOURCE_ROOTS.append(file_dir)

        # 2. Project root (if detected)
        project_root = find_project_root(current_file)
        if project_root and project_root not in SOURCE_ROOTS:
            SOURCE_ROOTS.append(project_root)

    # 3. Current working directory
    if include_cwd:
        cwd = os.getcwd()
        if cwd not in SOURCE_ROOTS:
            SOURCE_ROOTS.append(cwd)

    # 4. $SPORK_PATH entries
    spork_path = os.environ.get("SPORK_PATH", "")
    if spork_path:
        for p in spork_path.split(os.pathsep):
            p = p.strip()
            if p and os.path.isdir(p) and p not in SOURCE_ROOTS:
                SOURCE_ROOTS.append(p)

    # 5. CLI --source-path flags
    if extra_paths:
        for p in extra_paths:
            p = os.path.abspath(p)
            if p not in SOURCE_ROOTS:
                SOURCE_ROOTS.append(p)


def add_source_root(path: str, prepend: bool = False) -> None:
    """
    Add a directory to SOURCE_ROOTS.

    Args:
        path: Directory path to add
        prepend: If True, add to front of list (higher priority)
    """
    path = os.path.abspath(path)
    if path not in SOURCE_ROOTS:
        if prepend:
            SOURCE_ROOTS.insert(0, path)
        else:
            SOURCE_ROOTS.append(path)


def register_namespace(
    name: str,
    file: Optional[str],
    env: dict[str, Any],
    macros: dict[str, Callable],
    refers: Optional[dict[str, str]] = None,
    aliases: Optional[dict[str, str]] = None,
) -> NamespaceInfo:
    """
    Register a namespace in the global registry.

    Args:
        name: Fully qualified namespace name
        file: Absolute path to the source file (or None for synthetic/REPL ns)
        env: The namespace's environment dictionary
        macros: Macros defined in this namespace
        refers: Symbol -> source namespace mapping for referred symbols
        aliases: Alias -> namespace name mapping for :as aliases

    Returns:
        The NamespaceInfo that was registered.
    """
    timestamp = 0.0
    if file and os.path.isfile(file):
        timestamp = os.path.getmtime(file)

    info = NamespaceInfo(
        name=name,
        file=file,
        env=env,
        macros=macros,
        loaded=True,
        timestamp=timestamp,
        refers=refers or {},
        aliases=aliases or {},
    )
    NAMESPACE_REGISTRY[name] = info
    return info


def get_namespace(name: str) -> Optional[NamespaceInfo]:
    """
    Get a namespace from the registry.

    Args:
        name: Fully qualified namespace name

    Returns:
        NamespaceInfo if found, None otherwise.
    """
    return NAMESPACE_REGISTRY.get(name)


def namespace_loaded(name: str) -> bool:
    """
    Check if a namespace is already loaded.

    Args:
        name: Fully qualified namespace name

    Returns:
        True if namespace is in registry and marked as loaded.
    """
    info = NAMESPACE_REGISTRY.get(name)
    return info is not None and info.loaded


def needs_reload(name: str) -> bool:
    """
    Check if a namespace needs to be reloaded (file changed since load).

    Args:
        name: Fully qualified namespace name

    Returns:
        True if the source file has been modified since the namespace was loaded.
    """
    info = NAMESPACE_REGISTRY.get(name)
    if info is None or info.file is None:
        return False

    if not os.path.isfile(info.file):
        return False

    current_mtime = os.path.getmtime(info.file)
    return current_mtime > info.timestamp


def unload_namespace(name: str) -> bool:
    """
    Remove a namespace from the registry.

    Args:
        name: Fully qualified namespace name

    Returns:
        True if namespace was removed, False if it wasn't in registry.
    """
    if name in NAMESPACE_REGISTRY:
        del NAMESPACE_REGISTRY[name]
        return True
    return False


def list_namespaces() -> list[str]:
    """
    List all registered namespace names.

    Returns:
        List of fully qualified namespace names.
    """
    return list(NAMESPACE_REGISTRY.keys())


def clear_registry() -> None:
    """Clear all namespaces from the registry."""
    NAMESPACE_REGISTRY.clear()


# ============================================================================
# Require Resolution
# ============================================================================


def is_python_module(name: str) -> bool:
    """
    Check if a name refers to an importable Python module.

    Args:
        name: Module name (e.g., "math", "collections.abc")

    Returns:
        True if the module can be imported as a Python module.
    """
    import importlib.util

    try:
        spec = importlib.util.find_spec(name)
        return spec is not None
    except (ModuleNotFoundError, ValueError):
        return False


def resolve_require(
    ns_name: str, current_file: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """
    Resolve a require target to either a Spork file or Python module.

    Args:
        ns_name: The namespace/module name to require
        current_file: The file doing the requiring (for relative resolution)

    Returns:
        A tuple of (type, path) where:
        - type is "spork" or "python"
        - path is the absolute file path for Spork, or None for Python
    """
    # Build extra roots from current file
    extra_roots = []
    if current_file:
        file_dir = os.path.dirname(os.path.abspath(current_file))
        if file_dir:
            extra_roots.append(file_dir)

    # Try to find a Spork file first
    spork_file = find_spork_file_for_ns(ns_name, extra_roots=extra_roots)
    if spork_file:
        return ("spork", spork_file)

    # Fall back to Python module
    if is_python_module(ns_name):
        return ("python", None)

    # Not found
    raise FileNotFoundError(
        f"Cannot resolve namespace '{ns_name}': "
        f"no .spork file found and not a Python module"
    )


def parse_require_spec(spec) -> dict[str, Any]:
    """
    Parse a require specification from Spork syntax.

    Handles forms like:
    - ns-name (just the symbol)
    - [ns-name]
    - [ns-name :as alias]
    - [ns-name :refer [sym1 sym2]]
    - [ns-name :as alias :refer [sym1 sym2]]
    - [ns-name :refer :all]

    Args:
        spec: A Symbol or Vector from Spork reader

    Returns:
        Dict with keys:
        - "ns": namespace name (str)
        - "alias": alias name or None
        - "refer": list of symbol names, ":all", or None
    """
    # Import here to avoid circular imports
    from spork.compiler import Keyword, Symbol, VectorLiteral

    result: dict[str, Any] = {"ns": None, "alias": None, "refer": None}

    # Handle bare symbol
    if isinstance(spec, Symbol):
        result["ns"] = spec.name
        return result

    # Handle vector form
    if isinstance(spec, VectorLiteral):
        items = spec.items
        if not items:
            raise SyntaxError("Empty require spec")

        # First element must be the namespace
        if not isinstance(items[0], Symbol):
            raise SyntaxError("Require spec must start with namespace symbol")
        result["ns"] = items[0].name

        # Parse keyword arguments
        i = 1
        while i < len(items):
            item = items[i]
            if isinstance(item, Keyword):
                if item.name == "as":
                    if i + 1 >= len(items):
                        raise SyntaxError(":as requires an alias symbol")
                    alias = items[i + 1]
                    if not isinstance(alias, Symbol):
                        raise SyntaxError(":as alias must be a symbol")
                    result["alias"] = alias.name
                    i += 2
                elif item.name == "refer":
                    if i + 1 >= len(items):
                        raise SyntaxError(":refer requires symbols or :all")
                    refer_spec = items[i + 1]
                    if isinstance(refer_spec, Keyword) and refer_spec.name == "all":
                        result["refer"] = ":all"
                    elif isinstance(refer_spec, VectorLiteral):
                        result["refer"] = []
                        for sym in refer_spec.items:
                            if not isinstance(sym, Symbol):
                                raise SyntaxError(":refer items must be symbols")
                            result["refer"].append(sym.name)
                    else:
                        raise SyntaxError(":refer must be followed by vector or :all")
                    i += 2
                else:
                    raise SyntaxError(f"Unknown require option :{item.name}")
            else:
                raise SyntaxError(f"Unexpected item in require spec: {item}")

        return result

    raise SyntaxError(f"Invalid require spec: {spec}")


def validate_ns_name(ns_name: str, file_path: Optional[str] = None) -> bool:
    """
    Validate that a namespace name matches its file path.

    Args:
        ns_name: The namespace name declared in (ns ...)
        file_path: The file containing the namespace declaration

    Returns:
        True if valid, raises error if not.
    """
    if not file_path:
        return True  # Can't validate without file path

    # Get expected namespace from file path
    # We need to figure out which source root the file is under
    abs_path = os.path.abspath(file_path)

    for root in SOURCE_ROOTS:
        root = os.path.abspath(root)
        if abs_path.startswith(root + os.sep):
            rel_path = abs_path[len(root) + 1 :]
            expected_ns = relpath_to_ns(rel_path)
            if ns_name != expected_ns:
                raise ValueError(
                    f"Namespace name '{ns_name}' does not match file path. "
                    f"Expected '{expected_ns}' based on path '{file_path}'"
                )
            return True

    # File not under any source root - can't validate, allow it
    return True
