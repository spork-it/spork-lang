"""
spork.compiler.macros - Macro system for Spork

This module implements Spork's macro system, including:
- MACRO_ENV: Global registry of macros
- MACRO_EXEC_ENV: Shared environment for macro execution
- Standard library macros (when, unless, cond, ->, ->>, etc.)
- Protocol macros (defprotocol, extend-type, extend-protocol)
- Macro expansion functions

Macros are compile-time transformations that convert Spork forms
into other Spork forms before code generation.
"""

import importlib
import os
from typing import Any, Callable

from spork.runtime.core import (
    add,
    assoc,
    concat,
    conj,
    contains_q,
    count,
    cycle,
    dec,
    dedupe,
    disj,
    dissoc,
    distinct,
    div,
    doall,
    dorun,
    drop,
    drop_while,
    empty,
    even_q,
    every,
    # Sequence operations
    first,
    flatten,
    frequencies,
    get,
    group_by,
    # Math
    inc,
    interleave,
    interpose,
    into,
    iterate,
    keep,
    keep_indexed,
    map_indexed,
    mapcat,
    mod,
    mul,
    neg_q,
    not_any,
    not_every,
    nth,
    odd_q,
    partition,
    partition_all,
    pos_q,
    quot,
    reduce,
    reductions,
    rest,
    reverse,
    seq,
    # Predicates and reducers
    some,
    sort,
    sort_by,
    split_at,
    split_with,
    spork_abs,
    spork_filter,
    # Lazy sequences
    spork_map,
    spork_max,
    spork_min,
    spork_repeat,
    sub,
    take,
    take_while,
    zero_q,
    # Collection utilities
    zipmap,
)
from spork.runtime.pds import (
    EMPTY_MAP,
    EMPTY_SET,
    EMPTY_VECTOR,
    Cons,
    Map,
    Set,
    Vector,
    cons,
    hash_map,
    hash_set,
    vec,
    vec_f64,
    vec_i64,
)
from spork.runtime.types import (
    Decorated,
    Keyword,
    MapLiteral,
    SetLiteral,
    Symbol,
    VectorLiteral,
)

# =============================================================================
# Global Macro Environment
# =============================================================================

# Global macro environment (name -> Python callable)
MACRO_ENV: dict[str, Callable] = {}

# Macro execution environment - shared by all macros
MACRO_EXEC_ENV: dict[str, Any] = {}


# =============================================================================
# Library File Paths
# =============================================================================


def _get_lib_path(filename: str) -> str:
    """Get the path to a file in the spork/lib directory."""
    lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "std")
    return os.path.join(lib_dir, filename)


def _load_lib_file(filename: str) -> str:
    """Load the contents of a library file."""
    path = _get_lib_path(filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


# =============================================================================
# Protocol Macro Helpers (Python functions called by macros)
# =============================================================================


def extend_type_parse_groups(proto_impls):
    """
    Parse extend-type body into groups of (ProtoName method1 method2 ...).
    """
    groups = []
    current_group = None

    for item in proto_impls:
        if isinstance(item, Symbol):
            # This is a protocol name
            if current_group is not None:
                groups.append(current_group)
            current_group = [item]
        elif isinstance(item, list):
            # This is a method definition
            if current_group is None:
                raise SyntaxError("extend-type: method before protocol name")
            current_group.append(item)
        else:
            raise SyntaxError(f"extend-type: unexpected form {item!r}")

    if current_group is not None:
        groups.append(current_group)

    return groups


def extend_type_for_proto(type_expr, proto_name, methods):
    """
    Generate code to extend a type for a single protocol.
    Returns a list of forms to be spliced into a do block (not a do block itself).
    """
    # Build method dict entries
    method_entries = []
    method_defs = []

    for method in methods:
        if not isinstance(method, list) or len(method) < 2:
            raise SyntaxError(f"extend-type: invalid method form {method!r}")

        mname = method[0]
        if not isinstance(mname, Symbol):
            raise SyntaxError(
                f"extend-type: method name must be a symbol, got {mname!r}"
            )

        params = method[1]
        body = method[2:] if len(method) > 2 else [Symbol("nil")]

        # Create internal function name
        # Use gensym-like naming to avoid conflicts
        internal_name = Symbol(
            f"__{proto_name.name}${type_expr.name if isinstance(type_expr, Symbol) else 'anon'}${mname.name}__"
        )

        # Create the function definition
        fn_def = [Symbol("defn"), internal_name, params] + list(body)
        method_defs.append(fn_def)

        # Add to method entries
        method_entries.append(Keyword(mname.name))
        method_entries.append(internal_name)

    # Build the list of forms to be spliced (NOT wrapped in do)
    result = []
    result.extend(method_defs)

    # Register implementations
    result.append(
        [
            Symbol("register_protocol_impl"),
            proto_name.name,  # String literal for proto name
            type_expr,
            MapLiteral(list(zip(method_entries[::2], method_entries[1::2]))),
        ]
    )

    # Register as virtual subclass for isinstance
    result.append(
        [Symbol("protocol_register_virtual_subclass"), proto_name.name, type_expr]
    )

    return result


def extend_protocol_parse_groups(type_impls):
    """
    Parse extend-protocol body into groups of (Type method1 method2 ...).
    """
    groups = []
    current_group = None

    for item in type_impls:
        if isinstance(item, Symbol):
            # Could be a type name - check if next items are methods
            if current_group is not None:
                groups.append(current_group)
            current_group = [item]
        elif isinstance(item, list):
            # This is a method definition
            if current_group is None:
                raise SyntaxError("extend-protocol: method before type name")
            current_group.append(item)
        else:
            raise SyntaxError(f"extend-protocol: unexpected form {item!r}")

    if current_group is not None:
        groups.append(current_group)

    return groups


# =============================================================================
# Macro Expansion
# =============================================================================


def is_symbol(x, name=None):
    """Check if x is a Symbol, optionally with a specific name."""
    if isinstance(x, Symbol):
        if name is None:
            return True
        return x.name == name
    return False


def is_macro_call(form, macro_env):
    """Check if form is a macro call.

    Supports both simple macros (when, unless) and namespaced macros (alias.macro-name).
    For namespaced macros, checks if 'alias.macro-name' is registered in macro_env.
    """
    if not isinstance(form, list) or len(form) == 0:
        return False
    head = form[0]
    if not isinstance(head, Symbol):
        return False
    name = head.name

    # Check for direct macro name (including dot-qualified names like alias.macro)
    if name in macro_env:
        return True

    # Also check for slash-qualified names during transition period
    # This allows existing code with ns/macro to continue working
    if "/" in name:
        # Convert ns/macro to ns.macro format for lookup
        dot_name = name.replace("/", ".", 1)
        if dot_name in macro_env:
            return True

    return False


def macroexpand_1(form, macro_env):
    """Expand form once if it's a macro call.

    Supports both simple macros and namespaced macros (alias.macro-name).
    """
    if not is_macro_call(form, macro_env):
        return form
    macro_name = form[0].name

    # Look up macro - try direct name first
    if macro_name in macro_env:
        macro_fn = macro_env[macro_name]
    elif "/" in macro_name:
        # Convert ns/macro to ns.macro format for lookup (transition support)
        dot_name = macro_name.replace("/", ".", 1)
        macro_fn = macro_env[dot_name]
    else:
        # Should not reach here if is_macro_call returned True
        raise RuntimeError(f"Macro not found: {macro_name}")

    # Call the macro with the arguments (not including the macro name)
    return macro_fn(*form[1:])


def macroexpand(form, macro_env=None, max_depth=100):
    """Phase 2: Macroexpand - expand macros recursively."""
    if macro_env is None:
        macro_env = MACRO_ENV

    depth = 0
    while is_macro_call(form, macro_env) and depth < max_depth:
        form = macroexpand_1(form, macro_env)
        depth += 1

    if depth >= max_depth:
        raise RuntimeError(f"Macro expansion exceeded maximum depth of {max_depth}")

    return form


def macroexpand_all(forms, macro_env=None):
    """Apply macroexpansion to all forms recursively."""
    # Import here to avoid circular imports
    from spork.compiler.reader import SourceList

    if macro_env is None:
        macro_env = MACRO_ENV

    def expand_recursive(form):
        # First expand the form itself
        form = macroexpand(form, macro_env)

        # Then recursively expand subforms
        if isinstance(form, SourceList):
            # Preserve SourceList with its source location
            if len(form) > 0 and is_symbol(form[0], "quote"):
                return form
            expanded = [expand_recursive(f) for f in form]
            return SourceList(
                expanded, form.line, form.col, form.end_line, form.end_col
            )
        elif isinstance(form, list):
            # Plain list (rare case, e.g., from macro output)
            if len(form) > 0 and is_symbol(form[0], "quote"):
                return form
            return [expand_recursive(f) for f in form]
        elif isinstance(form, VectorLiteral):
            expanded = [expand_recursive(f) for f in form.items]
            return VectorLiteral(
                expanded, form.line, form.col, form.end_line, form.end_col
            )
        elif isinstance(form, MapLiteral):
            expanded = [
                (expand_recursive(k), expand_recursive(v)) for k, v in form.pairs
            ]
            return MapLiteral(
                expanded, form.line, form.col, form.end_line, form.end_col
            )
        elif isinstance(form, SetLiteral):
            expanded = [expand_recursive(f) for f in form.items]
            return SetLiteral(
                expanded, form.line, form.col, form.end_line, form.end_col
            )
        else:
            return form

    return [expand_recursive(f) for f in forms]


# =============================================================================
# Macro Processing
# =============================================================================


def process_defmacros(forms, macro_env, compile_defn_fn, normalize_name_fn):
    """
    First pass: process defmacro forms and register them in macro_env.
    Returns the forms with defmacros removed.

    Args:
        forms: List of forms to process
        macro_env: Macro environment to add macros to
        compile_defn_fn: Function to compile defn forms (from codegen)
        normalize_name_fn: Function to normalize names (from codegen)
    """
    import ast

    remaining_forms = []
    for form in forms:
        if isinstance(form, list) and len(form) > 0 and is_symbol(form[0], "defmacro"):
            # Execute the defmacro to register the macro
            if len(form) < 4:
                raise SyntaxError(
                    "defmacro requires at least 3 arguments: name, params, and body"
                )

            name_form = form[1]
            params_form = form[2]
            body_forms = form[3:]

            if not isinstance(name_form, Symbol):
                raise SyntaxError("defmacro name must be a symbol")
            if not isinstance(params_form, (list, VectorLiteral)):
                raise SyntaxError("defmacro params must be a list or vector")

            macro_name = name_form.name

            # Compile the macro as a Python function
            func_def = compile_defn_fn([name_form, params_form] + body_forms)

            # Execute the function definition to register it
            mod = ast.Module(body=[func_def], type_ignores=[])
            ast.fix_missing_locations(mod)
            code = compile(mod, "<defmacro>", "exec")
            # Use the shared macro execution environment
            exec(code, MACRO_EXEC_ENV, MACRO_EXEC_ENV)

            # Register the macro (use normalized name for lookup)
            macro_env[macro_name] = MACRO_EXEC_ENV[normalize_name_fn(macro_name)]
        else:
            remaining_forms.append(form)

    return remaining_forms


def process_import_macros(forms, macro_env):
    """
    Handle top-level (import-macros module [m1 m2 ...]) forms.

    For each such form:
      - import the Python module
      - read its __spork_macros__ dict
      - copy requested macro functions into macro_env
    Returns forms with import-macros removed.
    """
    remaining = []
    for form in forms:
        if (
            isinstance(form, list)
            and len(form) >= 3
            and is_symbol(form[0], "import-macros")
        ):
            _, module_form, names_vec, *rest = form

            if not isinstance(module_form, Symbol):
                raise SyntaxError("import-macros module name must be a symbol")
            if not isinstance(names_vec, VectorLiteral):
                raise SyntaxError("import-macros requires a vector of macro names")

            if rest:
                raise SyntaxError(
                    "import-macros currently supports only (import-macros module [m1 m2 ...])"
                )

            # Convert module symbol to Python module name
            py_mod_name = module_form.name.replace("/", ".")

            try:
                mod = importlib.import_module(py_mod_name)
            except ImportError as e:
                raise SyntaxError(
                    f"import-macros: could not import module {py_mod_name!r}: {e}"
                ) from e

            macros_dict = getattr(mod, "__spork_macros__", None)
            if macros_dict is None:
                raise SyntaxError(
                    f"import-macros: module {py_mod_name!r} has no __spork_macros__ "
                    "(is it a Spork module with defmacros?)"
                )

            # Pull requested macro functions into this file's macro env
            # Get the module alias (convert dots to match how it would be used)
            module_alias = module_form.name.replace("/", ".")

            for name_form in names_vec.items:
                if not isinstance(name_form, Symbol):
                    raise SyntaxError("import-macros names must be symbols")
                macro_name = name_form.name
                if macro_name not in macros_dict:
                    raise SyntaxError(
                        f"import-macros: macro {macro_name!r} not found in module {py_mod_name!r}"
                    )
                # Register unqualified name
                macro_env[macro_name] = macros_dict[macro_name]
                # Register with dot notation (canonical format)
                macro_env[f"{module_alias}.{macro_name}"] = macros_dict[macro_name]
                # Also register with slash notation for backwards compatibility
                macro_env[f"{module_form.name}/{macro_name}"] = macros_dict[macro_name]

            # Do NOT keep this form; it's compile-time only
        else:
            remaining.append(form)
    return remaining


# =============================================================================
# Initialization
# =============================================================================


def init_macro_exec_env():
    """Initialize the shared macro execution environment."""
    global MACRO_EXEC_ENV
    MACRO_EXEC_ENV = {
        # AST types for macros (capitalized Python class names)
        "Symbol": Symbol,
        "Keyword": Keyword,
        "VectorLiteral": VectorLiteral,
        "Decorated": Decorated,
        "MapLiteral": MapLiteral,
        "SetLiteral": SetLiteral,
        # Clojure-compatible lowercase constructor functions
        # Handle both string and Symbol arguments
        "symbol": lambda name: Symbol(
            name.name if isinstance(name, Symbol) else str(name)
        ),
        "keyword": lambda name: Keyword(
            name.name if isinstance(name, Symbol) else str(name)
        ),
        # Python builtins
        "list": list,
        "len": len,
        "isinstance": isinstance,
        "str": str,
        "map": map,
        "slice": slice,
        "print": print,
        "type": type,
        "getattr": getattr,
        "hasattr": hasattr,
        "range": range,
        "tuple": tuple,
        "dict": dict,
        "set": set,
        "frozenset": frozenset,
        "int": int,
        "float": float,
        "bool": bool,
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "sorted": sorted,
        "reversed": reversed,
        "enumerate": enumerate,
        "zip": zip,
        "all": all,
        "any": any,
        "filter": filter,
        "repr": repr,
        "id": id,
        "callable": callable,
        "iter": iter,
        "next": next,
        "None": None,
        "True": True,
        "False": False,
        # PDS constructors and types
        "vec": vec,
        "vec_f64": vec_f64,
        "vec_i64": vec_i64,
        "hash_map": hash_map,
        "hash_set": hash_set,
        "cons": cons,
        "Vector": Vector,
        "Map": Map,
        "Set": Set,
        "Cons": Cons,
        "EMPTY_VECTOR": EMPTY_VECTOR,
        "EMPTY_MAP": EMPTY_MAP,
        "EMPTY_SET": EMPTY_SET,
        # Sequence operations from runtime
        "first": first,
        "rest": rest,
        "seq": seq,
        "nth": nth,
        "conj": conj,
        "assoc": assoc,
        "dissoc": dissoc,
        "disj": disj,
        "get": get,
        "count": count,
        "contains_q": contains_q,
        "empty": empty,
        "into": into,
        "concat": concat,
        "reverse": reverse,
        "sort": sort,
        "sort_by": sort_by,
        # Lazy sequences
        "spork_map": spork_map,
        "spork_filter": spork_filter,
        "take": take,
        "take_while": take_while,
        "drop": drop,
        "drop_while": drop_while,
        "spork_repeat": spork_repeat,
        "cycle": cycle,
        "iterate": iterate,
        "interleave": interleave,
        "interpose": interpose,
        "partition": partition,
        "partition_all": partition_all,
        "keep": keep,
        "keep_indexed": keep_indexed,
        "map_indexed": map_indexed,
        "dedupe": dedupe,
        "distinct": distinct,
        "flatten": flatten,
        "mapcat": mapcat,
        # Predicates and reducers
        "some": some,
        "every": every,
        "not_every": not_every,
        "not_any": not_any,
        "reduce": reduce,
        "reductions": reductions,
        # Collection utilities
        "zipmap": zipmap,
        "group_by": group_by,
        "frequencies": frequencies,
        "split_at": split_at,
        "split_with": split_with,
        "doall": doall,
        "dorun": dorun,
        # Math
        "inc": inc,
        "dec": dec,
        "even_q": even_q,
        "odd_q": odd_q,
        "pos_q": pos_q,
        "neg_q": neg_q,
        "zero_q": zero_q,
        "add": add,
        "sub": sub,
        "mul": mul,
        "div": div,
        "mod": mod,
        "quot": quot,
        "spork_max": spork_max,
        "spork_min": spork_min,
        "spork_abs": spork_abs,
    }


def init_stdlib_macros(compile_defn_fn, normalize_name_fn):
    """Initialize standard library macros from prelude.spork.

    This loads the prelude which contains all macros that should be
    available in every Spork namespace without explicit imports.
    """
    from spork.compiler.reader import read_str

    # Register helper functions in MACRO_EXEC_ENV so protocol macros can call them
    MACRO_EXEC_ENV["extend_type_parse_groups"] = extend_type_parse_groups
    MACRO_EXEC_ENV["extend_type_for_proto"] = extend_type_for_proto
    MACRO_EXEC_ENV["extend_protocol_parse_groups"] = extend_protocol_parse_groups
    MACRO_EXEC_ENV["mapcat"] = lambda f, coll: [item for x in coll for item in f(x)]

    # Also register with hyphenated names for Spork code
    MACRO_ENV["extend-type-parse-groups"] = extend_type_parse_groups
    MACRO_ENV["extend-type-for-proto"] = extend_type_for_proto
    MACRO_ENV["extend-protocol-parse-groups"] = extend_protocol_parse_groups

    # Load all macros from prelude.spork
    prelude_source = _load_lib_file("prelude.spork")
    forms = read_str(prelude_source)
    process_defmacros(forms, MACRO_ENV, compile_defn_fn, normalize_name_fn)


# Initialize the base execution environment on module load
init_macro_exec_env()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Environments
    "MACRO_ENV",
    "MACRO_EXEC_ENV",
    # Library loading
    "_get_lib_path",
    "_load_lib_file",
    # Helper functions
    "extend_type_parse_groups",
    "extend_type_for_proto",
    "extend_protocol_parse_groups",
    # Expansion functions
    "is_symbol",
    "is_macro_call",
    "macroexpand_1",
    "macroexpand",
    "macroexpand_all",
    # Processing functions
    "process_defmacros",
    "process_import_macros",
    # Initialization
    "init_macro_exec_env",
    "init_stdlib_macros",
]
