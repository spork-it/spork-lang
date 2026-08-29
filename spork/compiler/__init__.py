"""
spork.compiler - The Spork Compiler Toolchain

This package compiles Spork source code to Python.

Phases:
1. Read (reader.py): Text -> Spork Forms
2. Macroexpand (macros.py): Expand macros
3. Analyze & Lower (codegen.py + feature modules): Forms -> Python AST
4. Compile: Python AST -> bytecode (via Python's compile())
"""

# Public compilation APIs
from spork.compiler.context import CompilationContext, get_compile_context
from spork.compiler.functions import compile_defn
from spork.compiler.pipeline import (
    compile_forms_to_code,
    eval_str,
    exec_file,
    export_file,
)
from spork.runtime.types import normalize_name

# Re-export loader (import hooks and cache)
from spork.compiler.loader import (
    COMPILER_CACHE_VERSION,
    SporkFinder,
    SporkLoader,
    cache_compiled_code,
    clear_cache,
    compile_file_to_python,
    compile_path_to_python,
    compile_with_cache,
    get_cached_code,
    install_import_hook,
)

# Re-export macros
from spork.compiler.macros import (
    MACRO_ENV,
    MACRO_EXEC_ENV,
    init_macro_exec_env,
    is_macro_call,
    macroexpand,
    macroexpand_all,
)
from spork.compiler.reader import (
    Reader,
    SourceList,
    SourceLocation,
    Token,
    copy_location,
    get_source_location,
    read_str,
    set_location,
    tokenize,
)

# Re-export reader macro types
from spork.compiler.reader_macros import (
    DISCARD,
    AnonFnLiteral,
    FStringLiteral,
    InstLiteral,
    PathLiteral,
    ReadTimeEval,
    RegexLiteral,
    SliceLiteral,
    UUIDLiteral,
    is_discard,
)

# Re-export types for backward compatibility
from spork.runtime.types import (
    Decorated,
    Keyword,
    MapLiteral,
    MatchError,
    SetLiteral,
    Symbol,
    VectorLiteral,
)


# Initialize macros and install import hook on package load
def _initialize():
    from spork.compiler.functions import compile_defn
    from spork.compiler.macros import init_stdlib_macros
    from spork.runtime.types import normalize_name

    init_stdlib_macros(compile_defn, normalize_name)


_initialize()
