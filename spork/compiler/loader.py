"""
spork.compiler.loader - Spork import hook and compilation cache

This module handles:
- In-memory compilation cache with automatic invalidation
- Import hooks for .spork files (SporkLoader, SporkFinder)
- Build utilities for compiling .spork files to Python source

Cache invalidation happens when:
- The .spork file's mtime changes
- The compiler cache version changes (COMPILER_CACHE_VERSION)
"""

import ast
import importlib.abc
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from types import CodeType
from typing import Any, Optional

# Version string for cache invalidation - bump when compiler lowering changes
COMPILER_CACHE_VERSION = "spork-compiler-v4"

# Process-local compile cache
# Key: (absolute_path, mtime, COMPILER_CACHE_VERSION)
# Value: (code, macro_env)
_COMPILE_CACHE: dict[tuple[str, float, str], tuple[CodeType, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def get_cache_key(path: str) -> tuple[str, float, str]:
    """Generate a cache key for the given file path."""
    abs_path = os.path.abspath(path)
    mtime = os.path.getmtime(abs_path)
    return (abs_path, mtime, COMPILER_CACHE_VERSION)


def get_cached_code(
    path: str,
) -> Optional[tuple[CodeType, dict[str, Any]]]:
    """
    Look up compiled code in the cache.

    Returns (code, macro_env) if cached and valid, None otherwise.
    """
    try:
        key = get_cache_key(path)
    except OSError:
        return None

    with _CACHE_LOCK:
        return _COMPILE_CACHE.get(key)


def cache_compiled_code(path: str, code: CodeType, macro_env: dict[str, Any]) -> None:
    """Store compiled code in the cache."""
    try:
        key = get_cache_key(path)
    except OSError:
        return

    with _CACHE_LOCK:
        _COMPILE_CACHE[key] = (code, macro_env)


def clear_cache() -> None:
    """Clear the compilation cache (useful for testing)."""
    with _CACHE_LOCK:
        _COMPILE_CACHE.clear()


def compile_with_cache(src: str, path: str) -> tuple[CodeType, dict[str, Any]]:
    """
    Compile Spork source, using cache if available.

    Args:
        src: The source code string
        path: The file path (for cache key and error messages)

    Returns:
        (compiled_code, macro_env) tuple
    """
    # Import here to avoid circular imports
    from spork.compiler.pipeline import compile_forms_to_code

    # Check cache first
    cached = get_cached_code(path)
    if cached is not None:
        return cached

    # Compile
    code, macro_env = compile_forms_to_code(src, path)

    # Cache the result
    cache_compiled_code(path, code, macro_env)

    return code, macro_env


# =============================================================================
# Import Hooks
# =============================================================================


class SporkLoader(importlib.abc.Loader):
    """
    Loader for .spork files.

    Uses the compilation cache to avoid recompiling unchanged files.
    """

    def __init__(self, fullname: str, path: str):
        self.fullname = fullname
        self.path = path

    def create_module(self, spec):
        return None  # default module creation

    def exec_module(self, module):
        from spork.runtime import setup_runtime_env

        path = os.path.abspath(self.path)

        # Try to get from cache
        cached = get_cached_code(path)

        if cached is not None:
            code, macro_env = cached
        else:
            # Need to compile
            with open(path, encoding="utf-8") as f:
                src = f.read()

            code, macro_env = compile_with_cache(src, path)

        # Setup runtime environment in module (always, not cached)
        setup_runtime_env(module.__dict__)

        # Expose this module's macro env for :require macro loading
        module.__dict__["__spork_macros__"] = macro_env

        # Execute the code
        exec(code, module.__dict__, module.__dict__)


class SporkFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder for .spork files.

    Searches sys.path (and provided path) for .spork files matching
    the requested module name.
    """

    def find_spec(self, fullname, path, target=None):
        # simple: only non-package modules, .spork alongside normal paths
        name = fullname.rpartition(".")[2]
        search_paths = path or sys.path
        for base in search_paths:
            candidate = os.path.join(base, name + ".spork")
            if os.path.isfile(candidate):
                loader = SporkLoader(fullname, candidate)
                return importlib.util.spec_from_loader(
                    fullname, loader, origin=candidate
                )
        return None


def install_import_hook():
    """Install the .spork file import hook after standard Python finders.

    Distributions intentionally ship ``module.py`` and ``module.spork`` side by
    side. Python imports must prefer compiled modules; the Spork finder is a
    fallback for source-only modules.
    """
    for finder in sys.meta_path:
        if isinstance(finder, SporkFinder):
            return
    sys.meta_path.append(SporkFinder())


# =============================================================================
# Build Utilities
# =============================================================================


def compile_file_to_python(
    src: str, src_path: str, *, aot: bool = True
) -> tuple[str, dict[str, Any]]:
    """Compile Spork source to importable Python and a source map.

    AOT output initializes its runtime globals and lowers project ``:require``
    clauses to ordinary Python imports. This keeps compiled packages usable by
    normal Python import machinery and avoids loading a second copy of a type
    through the Spork namespace registry.
    """
    from spork.compiler.codegen import compile_module
    from spork.compiler.context import compilation_context
    from spork.compiler.functions import compile_defn
    from spork.runtime.types import normalize_name
    from spork.compiler.macros import (
        MACRO_ENV,
        macroexpand_all,
        process_ns_macros,
    )
    from spork.compiler.macros import (
        process_defmacros as _process_defmacros_base,
    )
    from spork.compiler.reader import read_str

    with compilation_context(aot_imports=aot) as ctx:
        ctx.current_file = src_path if src_path != "<string>" else None
        forms = read_str(src)
        local_macro_env = dict(MACRO_ENV)
        forms = _process_defmacros_base(
            forms, local_macro_env, compile_defn, normalize_name
        )
        forms = process_ns_macros(forms, local_macro_env, ctx.current_file)
        forms = macroexpand_all(forms, local_macro_env)
        mod = compile_module(forms, filename=src_path)

    if aot:
        public_names = _collect_public_names(mod)
        prelude = ast.parse(
            "from __future__ import annotations\n"
            "from spork.runtime import setup_runtime_env as __spork_setup_runtime_env\n"
            "__spork_setup_runtime_env(globals())\n"
            "del __spork_setup_runtime_env\n"
        )
        mod.body = prelude.body + mod.body
        mod.body.append(
            ast.Assign(
                targets=[ast.Name(id="__all__", ctx=ast.Store())],
                value=ast.List(
                    elts=[ast.Constant(value=name) for name in public_names],
                    ctx=ast.Load(),
                ),
            )
        )
        ast.fix_missing_locations(mod)

    python_source = ast.unparse(mod)
    source_map = generate_source_map(mod, src_path)
    return python_source, source_map


def _collect_public_names(mod: ast.Module) -> list[str]:
    """Collect names intentionally defined or imported by a compiled module."""
    names: list[str] = []

    def add(name: Optional[str]) -> None:
        if name and not name.startswith("_") and name not in names:
            names.append(name)

    def add_target(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                add_target(element)

    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                add_target(target)
        elif isinstance(node, ast.AnnAssign):
            add_target(node.target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    add(alias.asname or alias.name)

    return names


def generate_source_map(mod: ast.Module, spork_file: str) -> dict[str, Any]:
    """
    Generate a source map from a Python AST module.

    Extracts line/column mappings from AST nodes that have location info.
    """
    mappings = []

    class LocationVisitor(ast.NodeVisitor):
        def generic_visit(self, node):
            if hasattr(node, "lineno") and hasattr(node, "col_offset"):
                # Get the original spork location if preserved
                # The AST node's location should reflect the spork source
                mapping = {
                    "py_line": node.lineno,
                    "py_col": node.col_offset,
                    "spork_line": node.lineno,  # Same for now, we preserve locations
                    "spork_col": node.col_offset,
                }
                if hasattr(node, "end_lineno") and node.end_lineno:
                    mapping["py_end_line"] = node.end_lineno
                    mapping["spork_end_line"] = node.end_lineno
                if hasattr(node, "end_col_offset") and node.end_col_offset:
                    mapping["py_end_col"] = node.end_col_offset
                    mapping["spork_end_col"] = node.end_col_offset
                mappings.append(mapping)
            super().generic_visit(node)

    LocationVisitor().visit(mod)

    # Deduplicate mappings (same py_line, py_col)
    seen = set()
    unique_mappings = []
    for m in mappings:
        key = (m["py_line"], m["py_col"])
        if key not in seen:
            seen.add(key)
            unique_mappings.append(m)

    return {
        "version": 1,
        "spork_file": spork_file,
        "mappings": unique_mappings,
    }


def compile_path_to_python(
    path: Path, *, aot: bool = True
) -> tuple[str, dict[str, Any]]:
    """
    Compile a .spork file to Python source and source map.

    Args:
        path: Path to the .spork file

    Returns:
        (python_source, source_map) tuple
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return compile_file_to_python(src, str(path), aot=aot)
