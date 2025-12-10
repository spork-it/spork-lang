"""
spork.runtime - The Spork Runtime Library

This package contains everything needed to run compiled Spork programs.
It is designed to be lightweight and independent of the compiler.

Submodules:
- types: Core type definitions (Symbol, Keyword, VectorLiteral, etc.)
- pds: C extension persistent data structures
- core: Standard library functions (first, rest, map, filter, etc.)
- utils: Runtime utilities (spork_try, setup_runtime_env, etc.)
- ns: Namespace management (loading, registering, finding namespaces)

The runtime is what gets installed into user project environments.
The compiler (spork.compiler) depends on runtime.types for AST nodes,
but the runtime has no dependencies on the compiler.
"""

from typing import Any, TypeVar, Union

# Re-export core functions
from spork.runtime.core import (
    _PROTOCOL_IMPLS,
    _PROTOCOLS,
    LazySeq,
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
    lazy_seq,
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

# Re-export JSON utilities
from spork.runtime.json import (
    SporkJSONEncoder,
)
from spork.runtime.json import (
    dump as json_dump,
)
from spork.runtime.json import (
    dumps as json_dumps,
)
from spork.runtime.json import (
    load as json_load,
)
from spork.runtime.json import (
    load_spork as json_load_spork,
)
from spork.runtime.json import (
    loads as json_loads,
)
from spork.runtime.json import (
    loads_spork as json_loads_spork,
)

# Re-export PDS (persistent data structures)
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

# Re-export types
from spork.runtime.types import (
    _MISSING,
    Decorated,
    Keyword,
    KwargsLiteral,
    MapLiteral,
    MatchError,
    SetLiteral,
    Symbol,
    VectorLiteral,
)

# Re-export utils
from spork.runtime.utils import (
    __spork_ns_env__,
    __spork_ns_get__,
    __spork_refer_all__,
    __spork_require__,
    setup_runtime_env,
    spork_kwargs_dict,
    spork_kwargs_map,
    spork_raise,
    spork_setattr,
    spork_try,
)

# Type variables for generic types
T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")
T_co = TypeVar("T_co", covariant=True)
V_co = TypeVar("V_co", covariant=True)

# Type aliases for common patterns
List = Vector
Vec = Vector
Dict = Map
ConsCell = Cons


def is_typed_collection(obj: Any) -> bool:
    """Check if an object is one of Spork's typed persistent collections."""
    return isinstance(obj, (Vector, Map, Cons))


def get_collection_type(obj: Any) -> Union[type, None]:
    """Get the collection type of a Spork persistent data structure."""
    if isinstance(obj, Vector):
        return Vector
    elif isinstance(obj, Map):
        return Map
    elif isinstance(obj, Cons):
        return Cons
    return None


__all__ = [
    # Types
    "Symbol",
    "Keyword",
    "VectorLiteral",
    "MapLiteral",
    "SetLiteral",
    "KwargsLiteral",
    "Decorated",
    "MatchError",
    "_MISSING",
    # Persistent data structures
    "Vector",
    "Map",
    "Set",
    "Cons",
    "DoubleVector",
    "IntVector",
    "TransientVector",
    "TransientDoubleVector",
    "TransientIntVector",
    "TransientMap",
    "TransientSet",
    "EMPTY_VECTOR",
    "EMPTY_DOUBLE_VECTOR",
    "EMPTY_LONG_VECTOR",
    "EMPTY_MAP",
    "EMPTY_SET",
    "EMPTY_SORTED_VECTOR",
    "vec",
    "vec_f64",
    "vec_i64",
    "hash_map",
    "hash_set",
    "sorted_vec",
    "cons",
    "SortedVector",
    "TransientSortedVector",
    # JSON
    "SporkJSONEncoder",
    "json_dump",
    "json_dumps",
    "json_load",
    "json_loads",
    "json_load_spork",
    "json_loads_spork",
    # Protocol system
    "_PROTOCOLS",
    "_PROTOCOL_IMPLS",
    "runtime_register_protocol",
    "get_protocol_abc",
    "register_protocol_impl",
    "protocol_register_virtual_subclass",
    "protocol_dispatch",
    "satisfies_protocol",
    # Sequence operations
    "first",
    "rest",
    "seq",
    "nth",
    "conj",
    "assoc",
    "dissoc",
    "disj",
    "get",
    "count",
    "contains_q",
    "empty",
    "into",
    # Transients
    "transient",
    "persistent_bang",
    "conj_bang",
    "assoc_bang",
    "dissoc_bang",
    "disj_bang",
    "pop_bang",
    # Lazy sequences
    "spork_map",
    "spork_filter",
    "take",
    "take_while",
    "drop",
    "drop_while",
    "concat",
    "spork_repeat",
    "cycle",
    "iterate",
    "spork_range",
    "interleave",
    "interpose",
    "partition",
    "partition_all",
    "keep",
    "keep_indexed",
    "map_indexed",
    "dedupe",
    "distinct",
    "flatten",
    "mapcat",
    # Predicates and reducers
    "some",
    "every",
    "not_every",
    "not_any",
    "reduce",
    "reductions",
    # Collection utilities
    "zipmap",
    "group_by",
    "frequencies",
    "reverse",
    "sort",
    "sort_by",
    "split_at",
    "split_with",
    "doall",
    "dorun",
    "realized_q",
    # Math
    "inc",
    "dec",
    "even_q",
    "odd_q",
    "pos_q",
    "neg_q",
    "zero_q",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "quot",
    "spork_max",
    "spork_min",
    "spork_abs",
    # Bitwise
    "bit_or",
    "bit_and",
    "bit_and_not",
    "bit_xor",
    "bit_not",
    "bit_shift_left",
    "bit_shift_right",
    # Utils
    "spork_try",
    "spork_raise",
    "spork_setattr",
    "spork_kwargs_dict",
    "spork_kwargs_map",
    "setup_runtime_env",
    "__spork_require__",
    "__spork_ns_env__",
    "__spork_ns_get__",
    "__spork_refer_all__",
    # Type variables
    "T",
    "T_co",
    "K",
    "V",
    "V_co",
    # Type aliases
    "List",
    "Vec",
    "Dict",
    "ConsCell",
    # Utilities
    "is_typed_collection",
    "get_collection_type",
]
