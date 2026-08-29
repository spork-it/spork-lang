"""Public source-to-code and execution pipeline."""

import __future__
import ast
import os
from typing import Any, Optional

from spork.compiler.codegen import compile_module
from spork.compiler.context import compilation_context, get_compile_context
from spork.compiler.functions import compile_defn
from spork.compiler.macros import MACRO_ENV, macroexpand_all, process_ns_macros
from spork.compiler.macros import process_defmacros as _process_defmacros_base
from spork.compiler.reader import read_str
from spork.runtime import setup_runtime_env
from spork.runtime.types import normalize_name


def process_defmacros(forms, macro_env):
    """
    Wrapper that calls macros.process_defmacros with compile_defn and normalize_name.
    """
    return _process_defmacros_base(forms, macro_env, compile_defn, normalize_name)


def compile_forms_to_code(src: str, filename: str = "<string>"):
    """
    Process Spork source through all compilation phases.
    Returns (compiled code object, local macro env).
    """
    # Set up compilation context with filename
    ctx = get_compile_context()
    ctx.current_file = filename if filename != "<string>" else None

    # Phase 1: Read
    forms = read_str(src)
    # Process defmacros (creates a local macro environment)
    local_macro_env = dict(MACRO_ENV)
    forms = process_defmacros(forms, local_macro_env)
    # Process ns :require clauses to load macros at compile-time
    forms = process_ns_macros(forms, local_macro_env, ctx.current_file)
    # Phase 2: Macroexpand with local macro environment
    forms = macroexpand_all(forms, local_macro_env)
    # Phase 3 & 4: Analyze & Lower
    mod = compile_module(forms, filename=filename)
    code = compile(
        mod,
        filename,
        "exec",
        flags=__future__.annotations.compiler_flag,
    )
    return code, local_macro_env


def eval_str(src: str, env: Optional[dict[str, Any]] = None):
    """Execute Spork source string in the given environment."""
    if env is None:
        env = {}
    setup_runtime_env(env)
    with compilation_context():
        code, _ = compile_forms_to_code(src, "<string>")
        exec(code, env, env)
    return env


def exec_file(path: str, env: Optional[dict[str, Any]] = None):
    """Execute a Spork source file."""
    from spork.runtime.ns import (
        init_source_roots,
        register_namespace,
    )

    # Initialize source roots based on the file being executed
    init_source_roots(current_file=path)

    with open(path, encoding="utf-8") as f:
        src = f.read()
    if env is None:
        env = {
            "__name__": "__main__",
            "__file__": path,
        }
    setup_runtime_env(env)

    with compilation_context() as ctx:
        ctx.current_file = path
        code, macro_env = compile_forms_to_code(src, path)
        env["__spork_macros__"] = macro_env
        exec(code, env, env)

        # Register namespace if this file declared one via (ns ...)
        if ctx.current_ns:
            register_namespace(
                name=ctx.current_ns,
                file=os.path.abspath(path),
                env=env,
                macros=macro_env,
                refers=ctx.ns_refers,
                aliases=ctx.ns_aliases,
            )

    return env


def export_file(path: str):
    """Convert a Spork source file to Python and output to stdout."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    with compilation_context() as ctx:
        ctx.current_file = path
        forms = read_str(src)
        local_macro_env = dict(MACRO_ENV)
        forms = process_defmacros(forms, local_macro_env)
        forms = process_ns_macros(forms, local_macro_env, path)
        forms = macroexpand_all(forms, local_macro_env)
        mod = compile_module(forms, filename=path)
    python_code = ast.unparse(mod)
    print(python_code)
