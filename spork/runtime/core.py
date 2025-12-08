"""
spork.runtime.core - Core runtime functions (Standard Library)

This module contains the core runtime functions that implement Spork's
standard library. These are the functions that compiled Spork code calls
at runtime.

Categories:
- Protocol system: protocol dispatch and registration
- Sequence operations: first, rest, seq, nth, conj, assoc, etc.
- Transient operations: transient, persistent!, conj!, etc.
- Lazy sequences: map, filter, take, drop, etc.
- Reducers: reduce, reductions, some, every, etc.
- Collection utilities: into, empty, count, etc.
- Math operations: inc, dec, +, -, *, /, etc.
- Bitwise operations: bit-and, bit-or, bit-xor, etc.
"""

from abc import ABC
from typing import Any, Iterator, Optional

from spork.runtime.pds import (
    EMPTY_MAP,
    EMPTY_SET,
    EMPTY_VECTOR,
    Cons,
    DoubleVector,
    IntVector,
    Map,
    Set,
    TransientDoubleVector,
    TransientIntVector,
    TransientMap,
    TransientSet,
    TransientVector,
    Vector,
    hash_map,
    vec,
)
from spork.runtime.types import _MISSING, Keyword

# =============================================================================
# Protocol System
# =============================================================================

# Global registries for protocols
_PROTOCOLS: dict[str, dict[str, Any]] = {
    # proto_name: {
    #   "abc": <ABC subclass>,
    #   "methods": ["first", "rest", "cons"],
    #   "structural": bool,
    #   "doc": str or None,
    # }
}

_PROTOCOL_IMPLS: dict[str, dict[type, dict[str, Any]]] = {
    # proto_name: {
    #   py_type: {
    #     "first": callable,
    #     "rest": callable,
    #   },
    # }
}


def runtime_register_protocol(
    name: str, doc: Optional[str], methods: list[str], structural: bool
) -> type:
    """
    Register a protocol and create its ABC.

    Args:
        name: Protocol name (e.g., "ISeq")
        doc: Optional docstring
        methods: List of method names
        structural: Whether to enable duck-typing fallback

    Returns:
        The ABC class for this protocol
    """
    # Create or fetch ABC
    abc_class = type(name, (ABC,), {"__doc__": doc or f"Protocol {name}"})
    _PROTOCOLS[name] = {
        "abc": abc_class,
        "methods": list(methods),
        "structural": structural,
        "doc": doc,
    }
    _PROTOCOL_IMPLS.setdefault(name, {})
    return abc_class


def get_protocol_abc(proto_name: str) -> Optional[type]:
    """Get the ABC class for a protocol by name."""
    proto = _PROTOCOLS.get(proto_name)
    if proto is None:
        return None
    return proto["abc"]


def register_protocol_impl(
    proto_name: str, py_type: type, methods_dict: dict[str, Any]
) -> None:
    """
    Register implementations of protocol methods for a type.

    Args:
        proto_name: Name of the protocol
        py_type: The Python type being extended
        methods_dict: Dict mapping method names to callables
    """
    if proto_name not in _PROTOCOLS:
        raise TypeError(f"Unknown protocol: {proto_name}")

    impls_for_proto = _PROTOCOL_IMPLS.setdefault(proto_name, {})
    # Convert keyword keys to string keys if needed
    normalized_dict = {}
    for k, v in methods_dict.items():
        if isinstance(k, str):
            key = k
        elif isinstance(k, Keyword):
            key = k.name  # Extract the name without the colon
        else:
            key = str(k)
        normalized_dict[key] = v
    impls_for_proto[py_type] = normalized_dict


def protocol_register_virtual_subclass(proto_name: str, py_type: type) -> None:
    """
    Register a type as a virtual subclass of a protocol's ABC.
    This enables isinstance checks.
    """
    if proto_name not in _PROTOCOLS:
        raise TypeError(f"Unknown protocol: {proto_name}")

    abc_class = _PROTOCOLS[proto_name]["abc"]
    abc_class.register(py_type)


def protocol_dispatch(proto_name: str, method_name: str, *args):
    """
    Dispatch a protocol method call.

    Args:
        proto_name: Name of the protocol
        method_name: Name of the method to call
        *args: Arguments to the method (first arg is dispatch target)

    Returns:
        Result of calling the implementation

    Raises:
        TypeError: If no implementation found
    """
    if not args:
        raise TypeError(f"{proto_name}.{method_name} called with no arguments")

    target = args[0]
    t = type(target)

    if proto_name not in _PROTOCOLS:
        raise TypeError(f"Unknown protocol: {proto_name}")

    proto = _PROTOCOLS[proto_name]
    impls = _PROTOCOL_IMPLS.get(proto_name, {})
    structural = proto["structural"]

    # 1. Exact type match
    entry = impls.get(t)
    if entry is not None:
        fn = entry.get(method_name)
        if fn is not None:
            return fn(*args)

    # 2. Walk MRO for supertype implementations
    for base in t.__mro__[1:]:
        entry = impls.get(base)
        if entry is not None:
            fn = entry.get(method_name)
            if fn is not None:
                return fn(*args)

    # 3. Optional structural duck-typing
    if structural:
        # Check if target has the method as an attribute
        # Convert method_name from Clojure style (e.g., "read-all") to Python style ("read_all")
        py_method_name = method_name.replace("-", "_")
        if hasattr(target, py_method_name):
            fn = getattr(target, py_method_name)
            # Call without target since it's a bound method
            return fn(*args[1:])

    # No implementation found
    raise TypeError(
        f"No implementation of {proto_name}.{method_name} for type {t.__name__}"
    )


def satisfies_protocol(proto_name: str, obj: Any) -> bool:
    """
    Check if an object satisfies a protocol.

    This checks:
    1. If the object's type has registered implementations
    2. If structural, whether the object has all required methods
    """
    if proto_name not in _PROTOCOLS:
        return False

    proto = _PROTOCOLS[proto_name]
    t = type(obj)
    impls = _PROTOCOL_IMPLS.get(proto_name, {})

    # Check exact type
    if t in impls:
        return True

    # Check MRO
    for base in t.__mro__[1:]:
        if base in impls:
            return True

    # Check structural (duck typing)
    if proto["structural"]:
        methods = proto["methods"]
        for method_name in methods:
            py_method_name = method_name.replace("-", "_")
            if not hasattr(obj, py_method_name):
                return False
        return True

    return False


# =============================================================================
# Sequence Operations (Core)
# =============================================================================


class LazySeq:
    """
    A lazy sequence wrapper that implements the seq abstraction without
    eagerly building Cons cells. Wraps an iterator and lazily materializes
    first/rest on demand.

    This is O(1) to create and only traverses the underlying iterator
    as elements are accessed.
    """

    __slots__ = ("_iterator", "_first", "_rest", "_realized")

    def __init__(self, iterator: Iterator):
        self._iterator = iterator
        self._first = None
        self._rest = None
        self._realized = False

    def _realize(self):
        """Realize the first element from the iterator."""
        if self._realized:
            return
        self._realized = True
        try:
            self._first = next(self._iterator)
        except StopIteration:
            # Empty iterator - mark as empty
            self._first = _MISSING
            self._rest = None

    @property
    def first(self):
        """Return the first element, realizing it if necessary."""
        self._realize()
        if self._first is _MISSING:
            return None
        return self._first

    @property
    def rest(self):
        """Return the rest as another LazySeq, or None if empty."""
        self._realize()
        if self._first is _MISSING:
            return None
        if self._rest is None:
            # Create a new LazySeq for the rest of the iterator
            self._rest = LazySeq(self._iterator)
            # Check if rest is empty
            self._rest._realize()
            if self._rest._first is _MISSING:
                self._rest = None
        return self._rest

    def __iter__(self):
        """Iterate through the lazy sequence."""
        current = self
        while current is not None:
            current._realize()
            if current._first is _MISSING:
                break
            yield current._first
            current = current.rest

    def __bool__(self):
        """LazySeq is truthy if it has at least one element."""
        self._realize()
        return self._first is not _MISSING

    def __repr__(self):
        # Collect elements for display (be careful with infinite seqs)
        items = []
        current = self
        limit = 10
        while current is not None and len(items) < limit:
            current._realize()
            if current._first is _MISSING:
                break
            items.append(repr(current._first))
            current = current.rest
        if current is not None and current._first is not _MISSING:
            items.append("...")
        return f"({' '.join(items)})"


def first(coll):
    """Return the first element of a collection."""
    if coll is None:
        return None
    if isinstance(coll, (Cons, LazySeq)):
        return coll.first
    if isinstance(coll, Vector):
        return coll.nth(0, None) if len(coll) > 0 else None
    # Fallback for Python sequences
    try:
        it = iter(coll)
        return next(it, None)
    except TypeError:
        return None


def rest(coll):
    """Return the rest of a collection as a sequence."""
    if coll is None:
        return None
    if isinstance(coll, (Cons, LazySeq)):
        r = coll.rest
        return r if r is not None and r is not type(None) else None
    if isinstance(coll, Vector):
        if len(coll) <= 1:
            return None
        # Return a Cons chain for rest of vector
        return seq(coll.nth(i) for i in range(1, len(coll)))
    # Fallback for Python sequences
    try:
        it = iter(coll)
        next(it, None)  # skip first
        return seq(it)
    except TypeError:
        return None


def seq(iterable):
    """Convert an iterable to a Cons sequence."""
    if iterable is None:
        return None
    if isinstance(iterable, Cons):
        return iterable
    if isinstance(iterable, LazySeq):
        # Realize LazySeq to Cons if needed, or just return it
        return iterable if iterable else None
    # For Map, return [key value] pairs
    if isinstance(iterable, Map):
        result = None
        for k, v in reversed(list(iterable.items())):
            result = Cons(vec(k, v), result)
        return result
    # Build in reverse then flip
    result = None
    items = list(iterable)
    for item in reversed(items):
        result = Cons(item, result)
    return result


def lazy_seq(iterable):
    """Convert an iterable to a lazy sequence.

    Returns a LazySeq that wraps the iterator, only materializing
    elements as they are accessed. This is O(1) to create.

    Unlike `seq`, this does not eagerly realize the entire sequence.
    """
    if iterable is None:
        return None
    if isinstance(iterable, LazySeq):
        return iterable
    if isinstance(iterable, Cons):
        # Wrap Cons iteration in LazySeq
        def cons_iter():
            curr = iterable
            while curr is not None:
                yield curr.first
                curr = curr.rest

        return LazySeq(cons_iter())
    # For Map, return [key value] pairs lazily
    if isinstance(iterable, Map):

        def map_pairs():
            for k, v in iterable.items():
                yield vec(k, v)

        return LazySeq(map_pairs())
    # Wrap in LazySeq - O(1) creation
    try:
        it = iter(iterable)
        result = LazySeq(it)
        # Check if empty
        if not result:
            return None
        return result
    except TypeError:
        return None


def nth(coll, index, default=_MISSING):
    """Get the nth element from any collection."""
    if coll is None:
        if default is _MISSING:
            raise IndexError(f"Index {index} out of range on nil")
        return default

    if isinstance(coll, Vector):
        return coll.nth(index, default) if default is not _MISSING else coll.nth(index)

    if isinstance(coll, (Cons, LazySeq)):
        curr = coll
        for _ in range(index):
            if curr is None:
                if default is _MISSING:
                    raise IndexError(f"Index {index} out of range")
                return default
            curr = curr.rest
        if curr is None:
            if default is _MISSING:
                raise IndexError(f"Index {index} out of range")
            return default
        return curr.first

    # Python sequences
    try:
        return coll[index]
    except (IndexError, KeyError):
        if default is _MISSING:
            raise
        return default


def conj(coll, val):
    """Add an element to a collection."""
    if coll is None:
        return Cons(val, None)
    if isinstance(coll, Vector):
        return coll.conj(val)
    if isinstance(coll, Cons):
        return Cons(val, coll)
    if isinstance(coll, Set):
        return coll.conj(val)
    if isinstance(coll, Map):
        if isinstance(val, Vector) and len(val) == 2:
            return coll.assoc(val.nth(0), val.nth(1))
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            return coll.assoc(val[0], val[1])
        raise ValueError("conj on map requires a [key value] pair")
    # Fallback
    if hasattr(coll, "append"):
        new_coll = list(coll)
        new_coll.append(val)
        return new_coll
    raise TypeError(f"Don't know how to conj onto {type(coll)}")


def assoc(coll, key, val):
    """Associate a key with a value in a collection."""
    if coll is None:
        if isinstance(key, int):
            raise IndexError("Can't assoc on nil")
        return hash_map(key, val)
    if isinstance(coll, Vector):
        return coll.assoc(key, val)
    if isinstance(coll, Map):
        return coll.assoc(key, val)
    if isinstance(coll, dict):
        new_dict = dict(coll)
        new_dict[key] = val
        return new_dict
    raise TypeError(f"Don't know how to assoc onto {type(coll)}")


def dissoc(coll, key):
    """Remove a key from a map."""
    if coll is None:
        return None
    if isinstance(coll, Map):
        return coll.dissoc(key)
    if isinstance(coll, dict):
        new_dict = dict(coll)
        new_dict.pop(key, None)
        return new_dict
    raise TypeError(f"Don't know how to dissoc from {type(coll)}")


def disj(coll, val):
    """Remove an element from a set."""
    if coll is None:
        return None
    if isinstance(coll, Set):
        return coll.disj(val)
    if isinstance(coll, set):
        new_set = set(coll)
        new_set.discard(val)
        return new_set
    raise TypeError(f"Don't know how to disj from {type(coll)}")


def get(coll, key, default=None):
    """Get a value from a collection by key."""
    if coll is None:
        return default
    if isinstance(coll, Map):
        return coll.get(key, default)
    if isinstance(coll, Vector):
        if isinstance(key, int):
            return coll.nth(key, default)
        return default
    if isinstance(coll, dict):
        return coll.get(key, default)
    # Try indexing
    try:
        return coll[key]
    except (IndexError, KeyError, TypeError):
        return default


def count(coll):
    """Return the count of items in a collection."""
    if coll is None:
        return 0
    return len(coll)


def contains_q(coll, key):
    """Check if a collection contains a key/element.

    For maps: checks if key is present.
    For sets: checks if element is present.
    For vectors/lists: checks if index is valid (not value!).
    """
    if coll is None:
        return False
    if isinstance(coll, Set):
        return key in coll
    if isinstance(coll, Map):
        return key in coll
    if isinstance(coll, set):
        return key in coll
    if isinstance(coll, dict):
        return key in coll
    if isinstance(coll, (Vector, list, tuple)):
        # For indexed collections, contains? checks if index is valid
        if isinstance(key, int):
            return 0 <= key < len(coll)
        return False
    # Fallback: use 'in' operator
    return key in coll


def empty(coll):
    """Return an empty collection of the same type."""
    if coll is None:
        return None
    if isinstance(coll, Vector):
        return EMPTY_VECTOR
    if isinstance(coll, Map):
        return EMPTY_MAP
    if isinstance(coll, Set):
        return EMPTY_SET
    if isinstance(coll, Cons):
        return None
    if isinstance(coll, list):
        return []
    if isinstance(coll, dict):
        return {}
    if isinstance(coll, set):
        return set()
    return None


def into(to_coll, from_coll):
    """Add all items from from_coll into to_coll."""
    if to_coll is None:
        return seq(from_coll)
    if isinstance(to_coll, Vector):
        t = to_coll.transient()
        for item in from_coll:
            t.conj_mut(item)
        return t.persistent()
    if isinstance(to_coll, Map):
        t = to_coll.transient()
        for item in from_coll:
            if isinstance(item, Vector) and len(item) == 2:
                t.assoc_mut(item.nth(0), item.nth(1))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                t.assoc_mut(item[0], item[1])
            else:
                raise ValueError("into map requires [key value] pairs")
        return t.persistent()
    if isinstance(to_coll, Set):
        t = to_coll.transient()
        for item in from_coll:
            t.conj_mut(item)
        return t.persistent()
    if isinstance(to_coll, Cons):
        result = to_coll
        for item in from_coll:
            result = Cons(item, result)
        return result
    raise TypeError(f"Don't know how to into {type(to_coll)}")


# =============================================================================
# Transient Operations
# =============================================================================


def transient(coll):
    """Create a mutable (transient) version of a persistent collection.

    Transients allow efficient batch mutations. Use conj!, assoc!, dissoc!
    to mutate, then call persistent! to get back an immutable collection.
    """
    if isinstance(coll, Vector):
        return coll.transient()
    if isinstance(coll, DoubleVector):
        return coll.transient()
    if isinstance(coll, IntVector):
        return coll.transient()
    if isinstance(coll, Map):
        return coll.transient()
    if isinstance(coll, Set):
        return coll.transient()
    raise TypeError(f"Don't know how to create transient from {type(coll)}")


def persistent_bang(coll):
    """Convert a transient collection back to a persistent (immutable) one.

    After calling persistent!, the transient can no longer be used.
    """
    if isinstance(coll, TransientVector):
        return coll.persistent()
    if isinstance(coll, TransientDoubleVector):
        return coll.persistent()
    if isinstance(coll, TransientIntVector):
        return coll.persistent()
    if isinstance(coll, TransientMap):
        return coll.persistent()
    if isinstance(coll, TransientSet):
        return coll.persistent()
    raise TypeError(f"Don't know how to make persistent from {type(coll)}")


def conj_bang(coll, val):
    """Mutably add an element to a transient collection.

    Returns the same transient (mutated in place).
    """
    if isinstance(coll, TransientVector):
        return coll.conj_mut(val)
    if isinstance(coll, TransientDoubleVector):
        return coll.conj_mut(val)
    if isinstance(coll, TransientIntVector):
        return coll.conj_mut(val)
    if isinstance(coll, TransientMap):
        if isinstance(val, Vector) and len(val) == 2:
            return coll.assoc_mut(val.nth(0), val.nth(1))
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            return coll.assoc_mut(val[0], val[1])
        raise ValueError("conj! on transient map requires a [key value] pair")
    if isinstance(coll, TransientSet):
        return coll.conj_mut(val)
    raise TypeError(f"Don't know how to conj! onto {type(coll)}")


def assoc_bang(coll, key, val):
    """Mutably associate a key with a value in a transient collection.

    Returns the same transient (mutated in place).
    """
    if isinstance(coll, TransientVector):
        return coll.assoc_mut(key, val)
    if isinstance(coll, TransientMap):
        return coll.assoc_mut(key, val)
    raise TypeError(f"Don't know how to assoc! onto {type(coll)}")


def dissoc_bang(coll, key):
    """Mutably remove a key from a transient map.

    Returns the same transient (mutated in place).
    """
    if isinstance(coll, TransientMap):
        return coll.dissoc_mut(key)
    raise TypeError(f"Don't know how to dissoc! from {type(coll)}")


def disj_bang(coll, val):
    """Mutably remove an element from a transient set.

    Returns the same transient (mutated in place).
    """
    if isinstance(coll, TransientSet):
        return coll.disj_mut(val)
    raise TypeError(f"Don't know how to disj! from {type(coll)}")


def pop_bang(coll):
    """Mutably remove the last element from a transient vector.

    Returns the same transient (mutated in place).
    """
    if isinstance(coll, TransientVector):
        return coll.pop_mut()
    raise TypeError(f"Don't know how to pop! from {type(coll)}")


# =============================================================================
# Lazy Sequence Functions (Generators)
# =============================================================================


def spork_map(f, *colls):
    """Lazily map a function over one or more collections (generator).

    With one collection: (map f coll) yields (f x) for each x in coll.
    With multiple collections: (map f c1 c2 ...) yields (f x1 x2 ...)
    where x1, x2, ... are from c1, c2, ... respectively.
    Stops when the shortest collection is exhausted.
    """
    if not colls:
        return
    if len(colls) == 1:
        for x in colls[0]:
            yield f(x)
    else:
        iterators = [iter(c) for c in colls]
        while True:
            try:
                args = [next(it) for it in iterators]
                yield f(*args)
            except StopIteration:
                return


def spork_filter(pred, coll):
    """Lazily filter a collection by a predicate (generator)."""
    if coll is None:
        return
    for x in coll:
        if pred(x):
            yield x


def take(n, coll):
    """Lazily take the first n elements from a collection (generator)."""
    if coll is None or n <= 0:
        return
    count = 0
    for x in coll:
        if count >= n:
            return
        yield x
        count += 1


def take_while(pred, coll):
    """Lazily take elements while predicate is true (generator)."""
    if coll is None:
        return
    for x in coll:
        if pred(x):
            yield x
        else:
            return


def drop(n, coll):
    """Lazily drop the first n elements from a collection (generator)."""
    if coll is None:
        return
    it = iter(coll)
    # Skip n items
    for _ in range(n):
        try:
            next(it)
        except StopIteration:
            return
    # Yield the rest
    yield from it


def drop_while(pred, coll):
    """Lazily drop elements while predicate is true, then yield the rest (generator)."""
    if coll is None:
        return
    dropping = True
    for x in coll:
        if dropping:
            if pred(x):
                continue
            else:
                dropping = False
        yield x


def concat(*colls):
    """Lazily concatenate multiple collections (generator)."""
    for coll in colls:
        if coll is not None:
            yield from coll


def spork_repeat(x, n=None):
    """Lazily repeat x, n times or infinitely if n is None (generator)."""
    if n is None:
        while True:
            yield x
    else:
        for _ in range(n):
            yield x


def cycle(coll):
    """Lazily cycle through a collection infinitely (generator).

    Note: Materializes the collection on first pass to enable cycling.
    """
    if coll is None:
        return
    items = list(coll)
    if not items:
        return
    while True:
        yield from items


def iterate(f, x):
    """Lazily generate x, f(x), f(f(x)), ... infinitely (generator)."""
    current = x
    while True:
        yield current
        current = f(current)


def spork_range(*args):
    """Lazily generate a range of numbers (generator).

    (range) -> 0, 1, 2, ... (infinite)
    (range end) -> 0, 1, ..., end-1
    (range start end) -> start, start+1, ..., end-1
    (range start end step) -> start, start+step, ..., up to end
    """
    if len(args) == 0:
        # Infinite range starting from 0
        n = 0
        while True:
            yield n
            n += 1
    elif len(args) == 1:
        yield from range(args[0])
    elif len(args) == 2:
        yield from range(args[0], args[1])
    elif len(args) == 3:
        yield from range(args[0], args[1], args[2])
    else:
        raise TypeError(f"range takes 0-3 arguments, got {len(args)}")


def interleave(*colls):
    """Lazily interleave multiple collections (generator).

    Stops when any collection is exhausted.
    """
    if not colls:
        return
    iterators = [iter(c) for c in colls]
    while True:
        try:
            for it in iterators:
                yield next(it)
        except StopIteration:
            return


def interpose(sep, coll):
    """Lazily interpose a separator between elements (generator)."""
    if coll is None:
        return
    first_elem = True
    for x in coll:
        if not first_elem:
            yield sep
        first_elem = False
        yield x


def partition(n, coll, step=None, pad=None):
    """Lazily partition a collection into chunks of n items (generator).

    step: how many items to advance (default: n)
    pad: collection to use to pad the last chunk if incomplete (default: None, drop incomplete)
    """
    if coll is None or n <= 0:
        return
    if step is None:
        step = n
    items = list(coll)
    i = 0
    while i < len(items):
        chunk = items[i : i + n]
        if len(chunk) == n:
            yield vec(*chunk)
        elif pad is not None:
            # Pad the last chunk
            pad_iter = iter(pad)
            while len(chunk) < n:
                try:
                    chunk.append(next(pad_iter))
                except StopIteration:
                    break
            if len(chunk) == n:
                yield vec(*chunk)
        # else: drop incomplete chunk
        i += step


def partition_all(n, coll, step=None):
    """Lazily partition a collection, including incomplete final chunk (generator)."""
    if coll is None or n <= 0:
        return
    if step is None:
        step = n
    items = list(coll)
    i = 0
    while i < len(items):
        chunk = items[i : i + n]
        yield vec(*chunk)
        i += step


def keep(f, coll):
    """Lazily keep non-nil results of f applied to coll (generator)."""
    if coll is None:
        return
    for x in coll:
        result = f(x)
        if result is not None:
            yield result


def keep_indexed(f, coll):
    """Lazily keep non-nil results of f(index, item) applied to coll (generator)."""
    if coll is None:
        return
    for i, x in enumerate(coll):
        result = f(i, x)
        if result is not None:
            yield result


def map_indexed(f, coll):
    """Lazily map f(index, item) over a collection (generator)."""
    if coll is None:
        return
    for i, x in enumerate(coll):
        yield f(i, x)


def dedupe(coll):
    """Lazily remove consecutive duplicates (generator)."""
    if coll is None:
        return
    prev = object()  # Unique sentinel
    for x in coll:
        if x != prev:
            yield x
            prev = x


def distinct(coll):
    """Lazily remove all duplicates, keeping first occurrence (generator)."""
    if coll is None:
        return
    seen = set()
    for x in coll:
        # Use id for unhashable types
        try:
            key = x
            if key not in seen:
                seen.add(key)
                yield x
        except TypeError:
            # Unhashable, use identity
            key = id(x)
            if key not in seen:
                seen.add(key)
                yield x


def flatten(coll):
    """Lazily flatten nested collections (generator).

    Flattens any iterable except strings.
    """
    if coll is None:
        return
    for x in coll:
        if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        else:
            yield x


def mapcat(f, *colls):
    """Lazily map f over colls and concatenate results (generator).

    Equivalent to (concat (map f colls...)).
    """
    for result in spork_map(f, *colls):
        if result is not None:
            yield from result


# =============================================================================
# Sequence Predicates and Reducers
# =============================================================================


def some(pred, coll):
    """Return the first truthy value of pred(x) for x in coll, or None."""
    if coll is None:
        return None
    for x in coll:
        result = pred(x)
        if result:
            return result
    return None


def every(pred, coll):
    """Return True if pred(x) is truthy for all x in coll."""
    if coll is None:
        return True
    for x in coll:
        if not pred(x):
            return False
    return True


def not_every(pred, coll):
    """Return True if pred(x) is falsy for at least one x in coll."""
    return not every(pred, coll)


def not_any(pred, coll):
    """Return True if pred(x) is falsy for all x in coll."""
    if coll is None:
        return True
    for x in coll:
        if pred(x):
            return False
    return True


def reduce(f, *args):
    """Reduce a collection with a function.

    (reduce f coll) - reduces with no initial value
    (reduce f init coll) - reduces with initial value
    """
    if len(args) == 1:
        coll = args[0]
        it = iter(coll)
        try:
            acc = next(it)
        except StopIteration:
            return f()  # f with no args for empty collection
        for x in it:
            acc = f(acc, x)
        return acc
    elif len(args) == 2:
        init, coll = args
        acc = init
        for x in coll:
            acc = f(acc, x)
        return acc
    else:
        raise TypeError(f"reduce takes 2-3 arguments, got {len(args) + 1}")


def reductions(f, *args):
    """Lazily yield intermediate reduce values (generator).

    (reductions f coll) - with no initial value
    (reductions f init coll) - with initial value
    """
    if len(args) == 1:
        coll = args[0]
        it = iter(coll)
        try:
            acc = next(it)
        except StopIteration:
            return
        yield acc
        for x in it:
            acc = f(acc, x)
            yield acc
    elif len(args) == 2:
        init, coll = args
        acc = init
        yield acc
        for x in coll:
            acc = f(acc, x)
            yield acc
    else:
        raise TypeError(f"reductions takes 2-3 arguments, got {len(args) + 1}")


# =============================================================================
# Collection Utilities
# =============================================================================


def zipmap(keys, vals):
    """Return a Map with keys mapped to corresponding vals."""
    result = EMPTY_MAP
    if result is None:
        # pds not initialized yet, return dict
        return dict(zip(keys, vals))
    t = result.transient()
    for k, v in zip(keys, vals):
        t.assoc_mut(k, v)
    return t.persistent()


def group_by(f, coll):
    """Return a Map of elements grouped by the result of f."""
    result = {}
    for x in coll:
        key = f(x)
        if key not in result:
            result[key] = []
        result[key].append(x)
    # Convert to Map with Vector values
    if EMPTY_MAP is not None:
        t = EMPTY_MAP.transient()
        for k, v in result.items():
            t.assoc_mut(k, vec(*v))
        return t.persistent()
    return result


def frequencies(coll):
    """Return a Map of elements to their counts."""
    result = {}
    for x in coll:
        result[x] = result.get(x, 0) + 1
    if EMPTY_MAP is not None:
        t = EMPTY_MAP.transient()
        for k, v in result.items():
            t.assoc_mut(k, v)
        return t.persistent()
    return result


def reverse(coll):
    """Return a lazy reversed sequence (realizes collection first)."""
    if coll is None:
        return
    items = list(coll)
    for i in range(len(items) - 1, -1, -1):
        yield items[i]


def sort(coll, key=None, reverse_order=False):
    """Return a sorted sequence (realizes collection)."""
    if coll is None:
        return EMPTY_VECTOR if EMPTY_VECTOR is not None else []
    items = sorted(coll, key=key, reverse=reverse_order)
    return vec(*items) if vec is not None else items


def sort_by(keyfn, coll):
    """Return a sequence sorted by keyfn (realizes collection)."""
    return sort(coll, key=keyfn)


def split_at(n, coll):
    """Return a tuple of (take n coll, drop n coll)."""
    if coll is None:
        return (vec(), vec()) if vec else ([], [])
    items = list(coll)
    return (vec(*items[:n]), vec(*items[n:])) if vec else (items[:n], items[n:])


def split_with(pred, coll):
    """Return a tuple of (take-while pred coll, drop-while pred coll)."""
    if coll is None:
        return (vec(), vec()) if vec else ([], [])
    items = list(coll)
    i = 0
    for x in items:
        if pred(x):
            i += 1
        else:
            break
    return (vec(*items[:i]), vec(*items[i:])) if vec else (items[:i], items[i:])


def doall(coll):
    """Force realization of a lazy sequence, return as Vector."""
    if coll is None:
        return EMPTY_VECTOR if EMPTY_VECTOR is not None else []
    return vec(*coll) if vec is not None else list(coll)


def dorun(coll):
    """Force realization of a lazy sequence for side effects only, return None."""
    if coll is None:
        return None
    for _ in coll:
        pass
    return None


def realized_q(coll):
    """Return True if the collection is fully realized (not a generator)."""
    import types

    return not isinstance(coll, types.GeneratorType)


# =============================================================================
# Math Operations
# =============================================================================


def inc(x):
    """Increment a number by 1."""
    return x + 1


def dec(x):
    """Decrement a number by 1."""
    return x - 1


def even_q(x):
    """Return True if x is even."""
    return x % 2 == 0


def odd_q(x):
    """Return True if x is odd."""
    return x % 2 == 1


def pos_q(x):
    """Return True if x is positive."""
    return x > 0


def neg_q(x):
    """Return True if x is negative."""
    return x < 0


def zero_q(x):
    """Return True if x is zero."""
    return x == 0


def add(*args):
    """Add numbers together."""
    if len(args) == 0:
        return 0
    result = args[0]
    for x in args[1:]:
        result = result + x
    return result


def sub(*args):
    """Subtract numbers."""
    if len(args) == 0:
        return 0
    if len(args) == 1:
        return -args[0]
    result = args[0]
    for x in args[1:]:
        result = result - x
    return result


def mul(*args):
    """Multiply numbers together."""
    if len(args) == 0:
        return 1
    result = args[0]
    for x in args[1:]:
        result = result * x
    return result


def div(*args):
    """Divide numbers."""
    if len(args) == 0:
        raise TypeError("div requires at least 1 argument")
    if len(args) == 1:
        return 1 / args[0]
    result = args[0]
    for x in args[1:]:
        result = result / x
    return result


def mod(a, b):
    """Modulo operation."""
    return a % b


def quot(a, b):
    """Integer division (quotient)."""
    return a // b


def spork_max(*args):
    """Return the maximum value."""
    if len(args) == 1 and hasattr(args[0], "__iter__"):
        return max(args[0])
    return max(args)


def spork_min(*args):
    """Return the minimum value."""
    if len(args) == 1 and hasattr(args[0], "__iter__"):
        return min(args[0])
    return min(args)


def spork_abs(x):
    """Return the absolute value."""
    return abs(x)


# =============================================================================
# Bitwise Operations
# =============================================================================


def bit_or(*args):
    """Bitwise OR. Also works as set union."""
    if len(args) == 0:
        return 0
    result = args[0]
    for x in args[1:]:
        result = result | x
    return result


def bit_and(*args):
    """Bitwise AND. Also works as set intersection."""
    if len(args) < 2:
        raise TypeError("bit-and requires at least 2 arguments")
    result = args[0]
    for x in args[1:]:
        result = result & x
    return result


def bit_and_not(*args):
    """Bitwise AND NOT. Also works as set difference."""
    if len(args) < 2:
        raise TypeError("bit-and-not requires at least 2 arguments")
    result = args[0]
    for x in args[1:]:
        result = result & (~x)
    return result


def bit_xor(*args):
    """Bitwise XOR. Also works as set symmetric difference."""
    if len(args) == 0:
        return 0
    result = args[0]
    for x in args[1:]:
        result = result ^ x
    return result


def bit_not(x):
    """Bitwise NOT (complement)."""
    return ~x


def bit_shift_left(x, n):
    """Bitwise left shift."""
    return x << n


def bit_shift_right(x, n):
    """Bitwise right shift."""
    return x >> n


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Protocol system
    "_PROTOCOLS",
    "_PROTOCOL_IMPLS",
    "runtime_register_protocol",
    "get_protocol_abc",
    "register_protocol_impl",
    "protocol_register_virtual_subclass",
    "protocol_dispatch",
    "satisfies_protocol",
    # Sequence operations (core)
    "LazySeq",
    "lazy_seq",
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
    # Transient operations
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
    # Math operations
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
    # Bitwise operations
    "bit_or",
    "bit_and",
    "bit_and_not",
    "bit_xor",
    "bit_not",
    "bit_shift_left",
    "bit_shift_right",
]
