"""
spork.runtime.json - JSON serialization support for Spork types.

This module provides a custom JSON encoder that can serialize Spork's
persistent data structures (Map, Vector, Set, Cons) and other Spork types
(Keyword, Symbol) to JSON.

Usage:
    import json
    from spork.runtime.json import SporkJSONEncoder, dumps

    # Using the encoder class directly
    data = hash_map("name", "Spork", "version", 1.0)
    json.dumps(data, cls=SporkJSONEncoder)

    # Using the convenience function
    dumps(data)  # Equivalent to above
"""

import json
from typing import Any, TextIO

from spork.runtime.pds import (
    Cons,
    DoubleVector,
    IntVector,
    Map,
    Set,
    TransientMap,
    TransientSet,
    TransientVector,
    Vector,
    hash_map,
    vec,
)
from spork.runtime.types import Keyword, Symbol


class SporkJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that handles Spork's persistent data structures.

    Supported types:
    - Map -> dict
    - Vector, DoubleVector, IntVector -> list
    - Set -> list (JSON has no set type)
    - Cons -> list
    - Keyword -> string (with leading colon, e.g., ":name")
    - Symbol -> string
    - Transient types -> their persistent equivalents

    Example:
        >>> from spork.runtime import hash_map, vec
        >>> from spork.runtime.json import SporkJSONEncoder
        >>> import json
        >>> data = hash_map("items", vec(1, 2, 3))
        >>> json.dumps(data, cls=SporkJSONEncoder)
        '{"items": [1, 2, 3]}'
    """

    def default(self, o: Any) -> Any:
        """
        Convert Spork types to JSON-serializable Python types.

        Args:
            obj: The object to serialize.

        Returns:
            A JSON-serializable representation of the object.

        Raises:
            TypeError: If the object is not JSON serializable.
        """
        # Map types -> dict
        if isinstance(o, Map):
            return {self._convert_key(k): v for k, v in o.items()}

        if isinstance(o, TransientMap):
            return {self._convert_key(k): v for k, v in o.items()}

        # Vector types -> list
        if isinstance(o, (Vector, DoubleVector, IntVector, TransientVector)):
            return list(o)

        # Set types -> list (JSON has no native set)
        if isinstance(o, (Set, TransientSet)):
            return list(o)

        # Cons (linked list) -> list
        if isinstance(o, Cons):
            return list(o)

        # Keyword -> string with colon prefix
        if isinstance(o, Keyword):
            return f":{o.name}"

        # Symbol -> string
        if isinstance(o, Symbol):
            return o.name

        # Fall back to default behavior (will raise TypeError)
        return super().default(o)

    def _convert_key(self, key: Any) -> str:
        """
        Convert a map key to a string suitable for JSON object keys.

        Args:
            key: The key to convert.

        Returns:
            A string representation of the key.
        """
        if isinstance(key, Keyword):
            # For keywords, use the name without the colon for cleaner JSON
            return key.name
        if isinstance(key, Symbol):
            return key.name
        if isinstance(key, str):
            return key
        # For other types, convert to string
        return str(key)


def dumps(
    obj: Any,
    *,
    skipkeys: bool = False,
    ensure_ascii: bool = True,
    check_circular: bool = True,
    allow_nan: bool = True,
    indent: int | str | None = None,
    separators: tuple[str, str] | None = None,
    default: Any = None,
    sort_keys: bool = False,
    **kwargs: Any,
) -> str:
    """
    Serialize a Spork object to a JSON formatted string.

    This is a convenience wrapper around json.dumps that uses SporkJSONEncoder
    by default.

    Args:
        obj: The object to serialize.
        skipkeys: If True, skip keys that are not basic types.
        ensure_ascii: If True, escape non-ASCII characters.
        check_circular: If True, check for circular references.
        allow_nan: If True, allow NaN, Infinity, -Infinity.
        indent: Indentation level for pretty printing.
        separators: Tuple of (item_separator, key_separator).
        default: A function for objects that can't be serialized.
        sort_keys: If True, sort dictionary keys.
        **kwargs: Additional arguments passed to json.dumps.

    Returns:
        A JSON formatted string.

    Example:
        >>> from spork.runtime import hash_map
        >>> from spork.runtime.json import dumps
        >>> dumps(hash_map("name", "Spork"))
        '{"name": "Spork"}'
    """
    return json.dumps(
        obj,
        cls=SporkJSONEncoder,
        skipkeys=skipkeys,
        ensure_ascii=ensure_ascii,
        check_circular=check_circular,
        allow_nan=allow_nan,
        indent=indent,
        separators=separators,
        default=default,
        sort_keys=sort_keys,
        **kwargs,
    )


def dump(
    obj: Any,
    fp: Any,
    *,
    skipkeys: bool = False,
    ensure_ascii: bool = True,
    check_circular: bool = True,
    allow_nan: bool = True,
    indent: int | str | None = None,
    separators: tuple[str, str] | None = None,
    default: Any = None,
    sort_keys: bool = False,
    **kwargs: Any,
) -> None:
    """
    Serialize a Spork object to a JSON formatted stream.

    This is a convenience wrapper around json.dump that uses SporkJSONEncoder
    by default.

    Args:
        obj: The object to serialize.
        fp: A file-like object with a write() method.
        skipkeys: If True, skip keys that are not basic types.
        ensure_ascii: If True, escape non-ASCII characters.
        check_circular: If True, check for circular references.
        allow_nan: If True, allow NaN, Infinity, -Infinity.
        indent: Indentation level for pretty printing.
        separators: Tuple of (item_separator, key_separator).
        default: A function for objects that can't be serialized.
        sort_keys: If True, sort dictionary keys.
        **kwargs: Additional arguments passed to json.dump.

    Example:
        >>> from spork.runtime import hash_map
        >>> from spork.runtime.json import dump
        >>> with open("data.json", "w") as f:
        ...     dump(hash_map("name", "Spork"), f)
    """
    json.dump(
        obj,
        fp,
        cls=SporkJSONEncoder,
        skipkeys=skipkeys,
        ensure_ascii=ensure_ascii,
        check_circular=check_circular,
        allow_nan=allow_nan,
        indent=indent,
        separators=separators,
        default=default,
        sort_keys=sort_keys,
        **kwargs,
    )


# Re-export loads and load from json module for convenience
# These don't need special handling since they produce Python types
loads = json.loads
load = json.load


def _to_spork(obj: Any, keywordize_keys: bool = False) -> Any:
    """
    Recursively convert Python dicts/lists to Spork Maps/Vectors.

    Args:
        obj: The object to convert.
        keywordize_keys: If True, convert string keys to Keywords.

    Returns:
        The converted object with dicts->Maps and lists->Vectors.
    """
    if isinstance(obj, dict):
        # Build a Map from the dict
        items: list[Any] = []
        for k, v in obj.items():
            if keywordize_keys and isinstance(k, str):
                items.append(Keyword(k))
            else:
                items.append(k)
            items.append(_to_spork(v, keywordize_keys))
        return hash_map(*items)

    if isinstance(obj, list):
        # Build a Vector from the list
        return vec(*[_to_spork(item, keywordize_keys) for item in obj])

    # Primitives (str, int, float, bool, None) pass through unchanged
    return obj


def loads_spork(
    s: str | bytes | bytearray,
    *,
    keywordize_keys: bool = False,
    **kwargs: Any,
) -> Any:
    """
    Parse a JSON string and convert to Spork persistent data structures.

    This parses the JSON and then converts:
    - dict -> Map
    - list -> Vector

    Args:
        s: The JSON string to parse.
        keywordize_keys: If True, convert string keys to Keywords.
        **kwargs: Additional arguments passed to json.loads.

    Returns:
        Parsed data using Spork's Map and Vector types.

    Example:
        >>> from spork.runtime.json import loads_spork
        >>> loads_spork('{"name": "Alice", "items": [1, 2, 3]}')
        {:name "Alice" :items [1 2 3]}
        >>> loads_spork('{"x": 1}', keywordize_keys=True)
        {:x 1}
    """
    parsed = json.loads(s, **kwargs)
    return _to_spork(parsed, keywordize_keys)


def load_spork(
    fp: TextIO,
    *,
    keywordize_keys: bool = False,
    **kwargs: Any,
) -> Any:
    """
    Parse JSON from a file and convert to Spork persistent data structures.

    This parses the JSON and then converts:
    - dict -> Map
    - list -> Vector

    Args:
        fp: A file-like object with a read() method.
        keywordize_keys: If True, convert string keys to Keywords.
        **kwargs: Additional arguments passed to json.load.

    Returns:
        Parsed data using Spork's Map and Vector types.

    Example:
        >>> from spork.runtime.json import load_spork
        >>> with open("data.json") as f:
        ...     data = load_spork(f, keywordize_keys=True)
    """
    parsed = json.load(fp, **kwargs)
    return _to_spork(parsed, keywordize_keys)


__all__ = [
    "SporkJSONEncoder",
    "dumps",
    "dump",
    "loads",
    "load",
    "loads_spork",
    "load_spork",
]
