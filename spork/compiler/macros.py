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
from spork.runtime import (
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
    else:
        # Should not reach here if is_macro_call returned True
        raise RuntimeError(f"Macro not found: {macro_name}")

    # Call the macro with the arguments (not including the macro name). Keep
    # the invocation location on a generated list so failures in built-in and
    # user macros point at the source call rather than an enclosing definition.
    expanded = macro_fn(*form[1:])
    from spork.compiler.reader import SourceList

    if isinstance(form, SourceList) and isinstance(expanded, list) and not isinstance(
        expanded, SourceList
    ):
        return SourceList(
            expanded,
            form.line,
            form.col,
            form.end_line,
            form.end_col,
        )
    return expanded


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


def _load_namespace_macros_only(req_ns, current_file=None):
    """Load only compile-time declarations from a required namespace.

    ``spork check`` must expand user macros to validate the resulting program,
    but it must not execute ordinary module forms.  A provisional namespace is
    registered before recursively processing macro imports so cycles terminate.
    """
    from spork.compiler.context import get_compile_context
    from spork.compiler.functions import compile_defn
    from spork.compiler.reader import read_str
    from spork.runtime.ns import (
        get_namespace,
        register_namespace,
        resolve_require,
    )
    from spork.runtime.types import normalize_name

    existing = get_namespace(req_ns)
    if existing is not None:
        return existing

    resolve_type, path = resolve_require(req_ns, current_file)
    if resolve_type != "spork":
        raise ValueError(f"{req_ns!r} is not a Spork source namespace")
    with open(path, encoding="utf-8") as source_file:
        forms = read_str(source_file.read())

    local_macro_env = dict(MACRO_ENV)
    remaining = process_defmacros(
        forms,
        local_macro_env,
        compile_defn,
        normalize_name,
    )
    info = register_namespace(
        name=req_ns,
        file=os.path.abspath(path),
        env={},
        macros=local_macro_env,
    )

    # Recursive imports see the provisional namespace above.  The active
    # check-only compilation context makes this call use the same safe loader.
    if get_compile_context().check_only:
        process_ns_macros(remaining, local_macro_env, path)
    info.macros = local_macro_env
    return info


def process_ns_macros(forms, macro_env, current_file=None):
    """
    Process (ns ...) forms to load macros at compile-time from :require clauses.

    This runs BEFORE macroexpansion to ensure macros are available.
    For each :require clause:
      - Resolve and load the source or Python-backed Spork namespace
      - Read its registered macro mapping
      - For :refer [sym1 sym2]: if symbol is a macro, add to macro_env
      - For :as alias: register macros under qualified names (alias.macro-name)
      - For :refer :all: import all macros from the module

    Returns forms unchanged (actual import code is generated by compile_ns).
    """
    from spork.runtime.ns import (
        get_namespace,
        namespace_loaded,
        parse_require_spec,
        resolve_require,
    )
    from spork.runtime.utils import __spork_require__

    for form in forms:
        # Look for (ns name (:require ...) ...)
        if not (isinstance(form, list) and len(form) > 0 and is_symbol(form[0], "ns")):
            continue

        # Process clauses after the ns name
        for clause in form[2:]:
            if not isinstance(clause, list) or len(clause) == 0:
                continue

            clause_head = clause[0]
            if not (isinstance(clause_head, Keyword) and clause_head.name == "require"):
                continue

            # Process each require spec
            for spec in clause[1:]:
                req_info = parse_require_spec(spec)
                req_ns = req_info["ns"]
                alias = req_info["alias"]
                refer = req_info["refer"]

                try:
                    resolve_type, _ = resolve_require(req_ns, current_file)
                except FileNotFoundError:
                    # Not found - compile_ns will report the syntax error.
                    continue

                # Load the Spork module at compile-time to get its macros. A
                # check-only compilation evaluates macro declarations but not
                # ordinary top-level forms from required modules.
                if not namespace_loaded(req_ns):
                    try:
                        from spork.compiler.context import get_compile_context

                        if resolve_type == "python":
                            __spork_require__(req_ns, current_file)
                        elif get_compile_context().check_only:
                            _load_namespace_macros_only(req_ns, current_file)
                        else:
                            __spork_require__(req_ns, current_file)
                    except Exception:
                        # Loading failed - the required file's own compilation
                        # or compile_ns resolution will report the error.
                        continue

                ns_info = get_namespace(req_ns)
                if ns_info is None:
                    continue

                macros_dict = ns_info.macros

                # Handle :as alias - register all macros under qualified names
                if alias and macros_dict:
                    for macro_name, macro_fn in macros_dict.items():
                        # Register as alias.macro-name
                        macro_env[f"{alias}.{macro_name}"] = macro_fn

                # Handle :refer
                if refer:
                    if refer == ":all":
                        # Import all macros
                        for macro_name, macro_fn in macros_dict.items():
                            macro_env[macro_name] = macro_fn
                    else:
                        # Import specific symbols - check if each is a macro
                        for sym in refer:
                            if sym in macros_dict:
                                macro_env[sym] = macros_dict[sym]

    # Return forms unchanged - compile_ns handles runtime imports
    return forms


# =============================================================================
# Initialization
# =============================================================================


def init_macro_exec_env():
    """Initialize the shared macro execution environment."""
    global MACRO_EXEC_ENV
    MACRO_EXEC_ENV = {
        "Symbol": Symbol,
        "Keyword": Keyword,
        "VectorLiteral": VectorLiteral,
        "Decorated": Decorated,
        "MapLiteral": MapLiteral,
        "SetLiteral": SetLiteral,
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
        # Normalized operator names for #= read-time eval
        "_plus_": add,
        "_minus_": sub,
        "_star_": mul,
        "_slash_": div,
        "apply": lambda f, args: f(*args),
    }


def init_stdlib_macros():
    """Install the Python-backed prelude macros supplied by spork-runtime."""
    from spork.std.prelude import install_macros

    install_macros(MACRO_ENV)


# Initialize the base execution environment on module load
init_macro_exec_env()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Environments
    "MACRO_ENV",
    "MACRO_EXEC_ENV",
    # Expansion functions
    "is_symbol",
    "is_macro_call",
    "macroexpand_1",
    "macroexpand",
    "macroexpand_all",
    # Processing functions
    "process_defmacros",
    "process_ns_macros",
    # Initialization
    "init_macro_exec_env",
    "init_stdlib_macros",
]
