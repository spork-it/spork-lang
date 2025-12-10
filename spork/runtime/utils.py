"""
spork.runtime.utils - Runtime utility functions

This module contains utility functions that are called by generated Spork code
at runtime. These include:

- spork_try: Runtime helper for try expressions
- spork_raise: Runtime helper for throw expressions
- spork_setattr: Runtime helper for set! on attributes
- setup_runtime_env: Populates an environment dict with all runtime bindings
- Namespace helpers: __spork_require__, __spork_ns_env__, etc.
"""

import os
from typing import Any, Optional

# Import runtime components
from spork.runtime.core import (
    _PROTOCOL_IMPLS,
    _PROTOCOLS,
    add,
    assoc,
    assoc_bang,
    bit_and,
    bit_and_not,
    bit_not,
    bit_or,
    bit_shift_left,
    bit_shift_right,
    bit_xor,
    concat,
    conj,
    conj_bang,
    contains_q,
    count,
    cycle,
    dec,
    dedupe,
    disj,
    disj_bang,
    dissoc,
    dissoc_bang,
    distinct,
    div,
    doall,
    dorun,
    drop,
    drop_while,
    empty,
    even_q,
    every,
    first,
    flatten,
    frequencies,
    get,
    get_protocol_abc,
    group_by,
    inc,
    interleave,
    interpose,
    into,
    iterate,
    keep,
    keep_indexed,
    last,
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
    persistent_bang,
    pop_bang,
    pos_q,
    protocol_dispatch,
    protocol_register_virtual_subclass,
    quot,
    realized_q,
    reduce,
    reductions,
    register_protocol_impl,
    rest,
    reverse,
    runtime_register_protocol,
    satisfies_protocol,
    seq,
    some,
    sort,
    sort_by,
    split_at,
    split_with,
    spork_abs,
    spork_filter,
    spork_map,
    spork_max,
    spork_min,
    spork_range,
    spork_repeat,
    sub,
    take,
    take_while,
    transient,
    zero_q,
    zipmap,
)
from spork.runtime.pds import (  # pyright: ignore[reportMissingModuleSource]
    EMPTY_DOUBLE_VECTOR,
    EMPTY_LONG_VECTOR,
    EMPTY_MAP,
    EMPTY_SET,
    EMPTY_SORTED_VECTOR,
    EMPTY_VECTOR,
    Cons,
    DoubleVector,
    IntVector,
    Map,
    Set,
    SortedVector,
    TransientDoubleVector,
    TransientIntVector,
    TransientMap,
    TransientSet,
    TransientSortedVector,
    TransientVector,
    Vector,
    cons,
    hash_map,
    hash_set,
    sorted_vec,
    vec,
    vec_f64,
    vec_i64,
)
from spork.runtime.types import (
    _MISSING,
    Decorated,
    Keyword,
    MapLiteral,
    MatchError,
    SetLiteral,
    Symbol,
    VectorLiteral,
    normalize_name,
)

# =============================================================================
# Runtime Helpers for Expression Forms
# =============================================================================


def spork_try(body_fn, handlers, finally_fn=None):
    """
    Runtime helper for try as expression.

    Args:
        body_fn: A callable that executes the try body
        handlers: list of (exc_type, handler_fn) tuples.
                  exc_type can be None for bare except.
        finally_fn: optional callable for cleanup.

    Returns:
        Result of body_fn or the matching handler
    """
    try:
        return body_fn()
    except Exception as e:
        for exc_type, handler_fn in handlers:
            if exc_type is None or isinstance(e, exc_type):
                return handler_fn(e)
        raise
    finally:
        if finally_fn is not None:
            finally_fn()


def spork_raise(exception):
    """Runtime helper for throw as expression. Raises the exception."""
    raise exception


def spork_setattr(obj, attr, value):
    """Runtime helper for set! as expression on attributes. Returns the value."""
    setattr(obj, attr, value)
    return value


def spork_kwargs_map(d):
    """
    Convert a Python kwargs dict to a Spork Map with Keyword keys.

    When defining a function with ** kwargs, Python passes a dict with string keys.
    This function converts it to a Spork Map with Keyword keys for consistency
    with Spork's idioms.

    Args:
        d: A Python dict (from **kwargs)

    Returns:
        A Spork Map with Keyword keys
    """

    # TODO: Add support in pds.c hash_map() for this operation
    items = []
    for k, v in d.items():
        key_name = k.replace("_", "-")
        items.append(Keyword(key_name))
        items.append(v)
    return hash_map(*items)


def spork_kwargs_dict(m):
    """
    Convert a Spork Map to a Python dict with string keys for kwargs splatting.

    When using *{variable} to splat a map as keyword arguments, the map's keys
    (which may be Keywords) need to be converted to strings for Python's ** operator.

    Args:
        m: A Spork Map, Python dict, or any mapping-like object

    Returns:
        A Python dict with string keys suitable for ** splatting
    """
    result = {}

    def get_key_str(k):
        if isinstance(k, Keyword):
            return normalize_name(k.name)
        elif isinstance(k, str):
            return normalize_name(k)
        else:
            return normalize_name(str(k))

    if isinstance(m, Map):
        for k, v in m.items():
            result[get_key_str(k)] = v
    elif isinstance(m, dict):
        for k, v in m.items():
            result[get_key_str(k)] = v
    else:
        try:
            for k, v in m.items():
                result[get_key_str(k)] = v
        except (AttributeError, TypeError):
            raise TypeError(f"Cannot splat {type(m).__name__} as keyword arguments")
    return result


# =============================================================================
# Namespace System Runtime Helpers
# =============================================================================


def __spork_require__(ns_name: str, current_file: Optional[str] = None) -> None:
    """
    Load a Spork namespace (if not already loaded).

    This is called by generated code for (require ...) forms.
    """
    from spork.runtime.ns import (
        namespace_loaded,
        register_namespace,
        resolve_require,
    )

    if namespace_loaded(ns_name):
        return

    try:
        kind, path = resolve_require(ns_name, current_file)
    except FileNotFoundError:
        # Try as Python module
        import importlib

        try:
            importlib.import_module(ns_name)
            return
        except ImportError as err:
            raise ImportError(f"Cannot find namespace or module: {ns_name}") from err

    if kind == "python":
        import importlib

        importlib.import_module(ns_name)
        return

    # It's a Spork file - load it
    # At this point, path is guaranteed to be a string (not None) for "spork" kind
    assert path is not None, "Spork file path should not be None"

    # Import here to avoid circular imports
    from spork.compiler.codegen import compile_forms_to_code, get_compile_context

    with open(path) as f:
        src = f.read()

    env: dict[str, Any] = {
        "__name__": ns_name,
        "__file__": path,
    }
    setup_runtime_env(env)

    # Set up compilation context
    ctx = get_compile_context()
    ctx.current_file = path

    code, macro_env = compile_forms_to_code(src, path)
    env["__spork_macros__"] = macro_env
    exec(code, env, env)

    # Register the namespace
    register_namespace(
        name=ns_name,
        file=os.path.abspath(path),
        env=env,
        macros=macro_env,
        refers=ctx.ns_refers,
        aliases=ctx.ns_aliases,
    )


def __spork_ns_env__(ns_name: str):
    """
    Get a NamespaceProxy for a namespace.
    Used for :as aliases to access namespace via attribute syntax.
    """
    from spork.runtime.ns import NamespaceProxy, get_namespace

    ns_info = get_namespace(ns_name)
    if ns_info is None:
        # Try to load it
        __spork_require__(ns_name)
        ns_info = get_namespace(ns_name)

    if ns_info is None:
        raise ImportError(f"Namespace not found: {ns_name}")

    return NamespaceProxy(ns_info.env, ns_name)


def __spork_ns_get__(ns_name: str, symbol: str) -> Any:
    """
    Get a symbol's value from a namespace.
    Used for :refer to bind individual symbols.
    """
    from spork.runtime.ns import get_namespace

    # Normalize name (hyphen to underscore)
    def normalize_name(name: str) -> str:
        return name.replace("-", "_")

    ns_info = get_namespace(ns_name)
    if ns_info is None:
        __spork_require__(ns_name)
        ns_info = get_namespace(ns_name)

    if ns_info is None:
        raise ImportError(f"Namespace not found: {ns_name}")

    env = ns_info.env
    normalized = normalize_name(symbol)
    if normalized in env:
        return env[normalized]
    if symbol in env:
        return env[symbol]
    raise ImportError(f"Symbol '{symbol}' not found in namespace '{ns_name}'")


def __spork_refer_all__(ns_name: str, target_env: dict[str, Any]) -> None:
    """
    Import all public symbols from a namespace into target environment.
    Used for :refer :all.
    """
    from spork.runtime.ns import get_namespace

    ns_info = get_namespace(ns_name)
    if ns_info is None:
        __spork_require__(ns_name)
        ns_info = get_namespace(ns_name)

    if ns_info is None:
        raise ImportError(f"Namespace not found: {ns_name}")

    env = ns_info.env
    for key, value in env.items():
        # Skip private/special names
        if not key.startswith("_"):
            target_env[key] = value


# =============================================================================
# Environment Setup
# =============================================================================


def setup_runtime_env(env: dict[str, Any]) -> None:
    """Add runtime helpers and data types to environment."""
    # Import typing module for first-class type syntax
    import typing

    def setboth(name: str, value: Any) -> None:
        """Register value under both original name and normalized Python name."""
        env.setdefault(name, value)
        normalized = normalize_name(name)
        if normalized != name:
            env.setdefault(normalized, value)

    # Common typing constructs - available without import
    env.setdefault("Any", typing.Any)
    env.setdefault("Optional", typing.Optional)
    env.setdefault("Union", typing.Union)
    env.setdefault("List", list)
    env.setdefault("Dict", dict)
    env.setdefault("Set", set)
    env.setdefault("Tuple", tuple)
    env.setdefault("Callable", typing.Callable)
    env.setdefault("Iterable", typing.Iterable)
    env.setdefault("Iterator", typing.Iterator)
    env.setdefault("Sequence", typing.Sequence)
    env.setdefault("Mapping", typing.Mapping)
    env.setdefault("Generator", typing.Generator)
    env.setdefault("Type", type)

    # Reader/AST types (for macros and quote)
    env.setdefault("Symbol", Symbol)
    env.setdefault("Keyword", Keyword)
    env.setdefault("VectorLiteral", VectorLiteral)
    env.setdefault("MapLiteral", MapLiteral)
    env.setdefault("SetLiteral", SetLiteral)
    env.setdefault("Decorated", Decorated)

    # Runtime persistent data structure types
    env.setdefault("Vector", Vector)
    env.setdefault("Map", Map)
    env.setdefault("Set", Set)
    env.setdefault("DoubleVector", DoubleVector)
    env.setdefault("IntVector", IntVector)

    # Protocol system
    env.setdefault("runtime_register_protocol", runtime_register_protocol)
    env.setdefault("get_protocol_abc", get_protocol_abc)
    env.setdefault("register_protocol_impl", register_protocol_impl)
    env.setdefault(
        "protocol_register_virtual_subclass", protocol_register_virtual_subclass
    )
    env.setdefault("protocol_dispatch", protocol_dispatch)
    env.setdefault("satisfies_protocol", satisfies_protocol)
    env.setdefault("_PROTOCOLS", _PROTOCOLS)
    env.setdefault("_PROTOCOL_IMPLS", _PROTOCOL_IMPLS)

    # Builtins
    env.setdefault("inc", inc)
    env.setdefault("dec", dec)
    setboth("even?", even_q)
    setboth("odd?", odd_q)
    setboth("pos?", pos_q)
    setboth("neg?", neg_q)
    setboth("zero?", zero_q)

    # Arithmetic operators as functions
    setboth("+", add)
    setboth("-", sub)
    setboth("*", mul)
    setboth("/", div)
    env.setdefault("mod", mod)
    env.setdefault("quot", quot)
    env.setdefault("max", spork_max)
    env.setdefault("min", spork_min)
    env.setdefault("abs", spork_abs)

    # Bitwise operators (also work for set operations)
    # Users write bit-or, bit-and, etc. which normalize to bit_or, bit_and
    env.setdefault("bit_or", bit_or)
    env.setdefault("bit_and", bit_and)
    env.setdefault("bit_xor", bit_xor)
    env.setdefault("bit_not", bit_not)
    env.setdefault("bit_shift_left", bit_shift_left)
    env.setdefault("bit_shift_right", bit_shift_right)

    # Symbol aliases for bitwise operators (lisp-style)
    env.setdefault("|", bit_or)
    env.setdefault("&", bit_and)
    env.setdefault("^", bit_xor)
    env.setdefault("~", bit_not)
    env.setdefault("<<", bit_shift_left)
    env.setdefault(">>", bit_shift_right)

    # Set operations using bitwise functions
    env.setdefault("union", bit_or)
    env.setdefault("intersection", bit_and)
    env.setdefault("difference", bit_and_not)

    # Persistent data structures (internal types and transients)
    env.setdefault("Cons", Cons)
    env.setdefault("TransientVector", TransientVector)
    env.setdefault("TransientDoubleVector", TransientDoubleVector)
    env.setdefault("TransientIntVector", TransientIntVector)
    env.setdefault("TransientMap", TransientMap)
    env.setdefault("TransientSet", TransientSet)
    env.setdefault("EMPTY_VECTOR", EMPTY_VECTOR)
    env.setdefault("EMPTY_DOUBLE_VECTOR", EMPTY_DOUBLE_VECTOR)
    env.setdefault("EMPTY_LONG_VECTOR", EMPTY_LONG_VECTOR)
    env.setdefault("EMPTY_MAP", EMPTY_MAP)
    env.setdefault("EMPTY_SET", EMPTY_SET)

    # Constructors for persistent structures
    env.setdefault("cons", cons)
    env.setdefault("vec", vec)
    env.setdefault("vec_f64", vec_f64)
    env.setdefault("vec_i64", vec_i64)
    env.setdefault("hash_map", hash_map)
    env.setdefault("hash_set", hash_set)
    env.setdefault("sorted_vec", sorted_vec)

    # SortedVector types
    env.setdefault("SortedVector", SortedVector)
    env.setdefault("TransientSortedVector", TransientSortedVector)
    env.setdefault("EMPTY_SORTED_VECTOR", EMPTY_SORTED_VECTOR)

    # Transient operations for batch mutations
    env.setdefault("transient", transient)
    setboth("persistent!", persistent_bang)
    setboth("conj!", conj_bang)
    setboth("assoc!", assoc_bang)
    setboth("dissoc!", dissoc_bang)
    setboth("disj!", disj_bang)
    setboth("pop!", pop_bang)

    # Sequence operations (core)
    env.setdefault("first", first)
    env.setdefault("last", last)
    env.setdefault("rest", rest)
    env.setdefault("seq", seq)
    env.setdefault("nth", nth)
    env.setdefault("conj", conj)
    env.setdefault("assoc", assoc)
    env.setdefault("dissoc", dissoc)
    env.setdefault("disj", disj)
    env.setdefault("get", get)
    env.setdefault("count", count)
    setboth("contains?", contains_q)
    env.setdefault("empty", empty)
    env.setdefault("into", into)

    # Lazy sequence operations (generators)
    env.setdefault("map", spork_map)
    env.setdefault("filter", spork_filter)
    env.setdefault("take", take)
    env.setdefault("drop", drop)
    env.setdefault("take_while", take_while)
    env.setdefault("drop_while", drop_while)
    env.setdefault("concat", concat)
    env.setdefault("repeat", spork_repeat)
    env.setdefault("cycle", cycle)
    env.setdefault("iterate", iterate)
    env.setdefault("range", spork_range)
    env.setdefault("interleave", interleave)
    env.setdefault("interpose", interpose)
    env.setdefault("partition", partition)
    env.setdefault("partition_all", partition_all)
    env.setdefault("keep", keep)
    env.setdefault("keep_indexed", keep_indexed)
    env.setdefault("map_indexed", map_indexed)
    env.setdefault("dedupe", dedupe)
    env.setdefault("distinct", distinct)
    env.setdefault("flatten", flatten)
    env.setdefault("mapcat", mapcat)

    # Sequence predicates and reducers
    env.setdefault("some", some)
    env.setdefault("every", every)
    env.setdefault("not_every", not_every)
    env.setdefault("not_any", not_any)
    env.setdefault("reduce", reduce)
    env.setdefault("reductions", reductions)

    # Sequence utilities
    env.setdefault("zipmap", zipmap)
    env.setdefault("group_by", group_by)
    env.setdefault("frequencies", frequencies)
    env.setdefault("reverse", reverse)
    env.setdefault("sort", sort)
    env.setdefault("sort_by", sort_by)
    env.setdefault("split_at", split_at)
    env.setdefault("split_with", split_with)
    env.setdefault("doall", doall)
    env.setdefault("dorun", dorun)
    setboth("realized?", realized_q)

    # Runtime helpers
    env.setdefault("spork_try", spork_try)
    env.setdefault("spork_raise", spork_raise)
    env.setdefault("spork_setattr", spork_setattr)
    env.setdefault("spork_kwargs_dict", spork_kwargs_dict)
    env.setdefault("spork_kwargs_map", spork_kwargs_map)

    # Pattern matching
    env.setdefault("MatchError", MatchError)
    env.setdefault("_MISSING", _MISSING)

    # Namespace system runtime helpers
    env.setdefault("__spork_require__", __spork_require__)
    env.setdefault("__spork_ns_env__", __spork_ns_env__)
    env.setdefault("__spork_ns_get__", __spork_ns_get__)
    env.setdefault("__spork_refer_all__", __spork_refer_all__)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Runtime helpers
    "spork_try",
    "spork_raise",
    "spork_setattr",
    # Environment setup
    "setup_runtime_env",
    # Namespace helpers
    "__spork_require__",
    "__spork_ns_env__",
    "__spork_ns_get__",
    "__spork_refer_all__",
]
