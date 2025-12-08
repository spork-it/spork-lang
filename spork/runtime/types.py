"""
spork.runtime.types - Core type definitions for Spork

This module contains the fundamental types used by both the runtime and compiler:
- Symbol: Represents symbolic identifiers in Spork code
- Keyword: Interned symbols that evaluate to themselves (like Clojure keywords)
- VectorLiteral: AST representation of vector literals [...]
- MapLiteral: AST representation of map literals {...}
- SetLiteral: AST representation of set literals #{...}
- Decorated: Represents decorator expressions (^decorator or ^(decorator args))
- MatchError: Exception raised when pattern matching fails
- normalize_name: Converts Lisp-style names to valid Python identifiers

These types are used by the reader/parser to represent Spork forms,
and by the runtime for values that exist at execution time.
"""

from dataclasses import dataclass
from typing import Any

# Sentinel for missing values
_MISSING = object()


class MatchError(Exception):
    """Raised when no pattern matches in a match expression or multi-dispatch function."""

    pass


def normalize_name(name: str) -> str:
    """
    Normalize a Lisp-style identifier to a valid Python identifier.

    Converts hyphens to underscores and special characters to safe suffixes.
    This is the single source of truth used by both the compiler (codegen)
    and the runtime (setup_runtime_env).
    """
    # Handle special operator names that are valid Spork symbols
    # but not valid Python identifiers
    SPECIAL_NAMES = {
        "+": "_plus_",
        "-": "_minus_",
        "*": "_star_",
        "/": "_slash_",
        "=": "_eq_",
        "<": "_lt_",
        ">": "_gt_",
        "<=": "_lte_",
        ">=": "_gte_",
        "!=": "_neq_",
        "==": "_eqeq_",
    }

    # Check for exact match first (operators used as values)
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]

    # Replace hyphens with underscores
    result = name.replace("-", "_")

    # Replace trailing ? with _q (predicates like even?, nil?)
    if result.endswith("?"):
        result = result[:-1] + "_q"

    # Replace trailing ! with _bang (mutating functions like set!, swap!)
    if result.endswith("!"):
        result = result[:-1] + "_bang"

    # Replace other special characters that might appear mid-name
    result = result.replace("?", "_q_")
    result = result.replace("!", "_bang_")
    result = result.replace("*", "_star_")
    result = result.replace("+", "_plus_")
    result = result.replace("'", "_prime_")
    result = result.replace("$", "_S_")

    return result


@dataclass
class Symbol:
    """
    Represents a symbolic identifier in Spork code.

    Symbols are the fundamental naming construct in Spork. They represent
    variable names, function names, and other identifiers.

    Attributes:
        name: The string name of the symbol
        line: Source line number (1-based)
        col: Source column number (0-based)
        end_line: Ending line number
        end_col: Ending column number
    """

    name: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return self.name

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "Symbol":
        """Return a new Symbol with the given location."""
        return Symbol(
            self.name, line, col, end_line or line, end_col or col + len(self.name)
        )


@dataclass(eq=False)
class Keyword:
    """
    Keyword type - like Clojure keywords, these are interned symbols that
    evaluate to themselves and can be used as map keys.

    Keywords compare equal by name only (source location is ignored).
    They are hashable and can be used as dictionary keys.
    Keywords are also callable - calling a keyword with a map returns the value
    at that key: (:foo {:foo 1}) => 1

    Attributes:
        name: The string name of the keyword (without the leading colon)
        line: Source line number (1-based)
        col: Source column number (0-based)
        end_line: Ending line number
        end_col: Ending column number
    """

    name: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f":{self.name}"

    def __str__(self):
        return f":{self.name}"

    def __eq__(self, other):
        if isinstance(other, Keyword):
            return self.name == other.name
        return False

    def __hash__(self):
        return hash(("Keyword", self.name))

    def __call__(self, coll, default=None):
        """
        Make keywords callable for map lookup.
        (:name {:name "Alice"}) => "Alice"
        (:missing {:name "Alice"} "default") => "default"
        """
        try:
            # Try direct key access first (works for Map and dict)
            if hasattr(coll, "get"):
                return coll.get(self, default)
            # Fallback to indexing
            return coll[self] if self in coll else default
        except (KeyError, TypeError):
            return default

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "Keyword":
        """Return a new Keyword with the given location."""
        return Keyword(
            self.name, line, col, end_line or line, end_col or col + len(self.name) + 1
        )


@dataclass
class Decorated:
    """
    Represents a decorator expression (^decorator or ^(decorator args)).

    Used in Spork for type annotations and metadata on definitions.

    Attributes:
        expr: The decorator expression (could be a Symbol, list, etc.)
        line: Source line number
        col: Source column number
        end_line: Ending line number
        end_col: Ending column number
    """

    expr: Any
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"Decorated({self.expr!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "Decorated":
        """Return a new Decorated with the given location."""
        return Decorated(self.expr, line, col, end_line or line, end_col)


@dataclass
class VectorLiteral:
    """
    AST node representing a vector literal [...] in source code.

    This is distinct from the runtime Vector type (pds.Vector).
    VectorLiteral is used during parsing and compilation, while Vector
    is the persistent data structure used at runtime.

    Attributes:
        items: List of elements in the vector
        line: Source line number
        col: Source column number
        end_line: Ending line number
        end_col: Ending column number
    """

    items: list[Any]
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"VectorLiteral({self.items!r})"

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "VectorLiteral":
        """Return a new VectorLiteral with the given location."""
        return VectorLiteral(self.items, line, col, end_line or line, end_col)


@dataclass
class MapLiteral:
    """
    Represents a map/dict literal that preserves the order and structure of key-value pairs.

    This is used instead of Python dict to support Clojure-style destructuring patterns
    like {a :x b :y} where the binding symbol comes before the key.

    Attributes:
        pairs: List of (key, value) tuples in the order they appeared
        line: Source line number
        col: Source column number
        end_line: Ending line number
        end_col: Ending column number
    """

    pairs: list[tuple[Any, Any]]
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"MapLiteral({self.pairs!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "MapLiteral":
        """Return a new MapLiteral with the given location."""
        return MapLiteral(self.pairs, line, col, end_line or line, end_col)


@dataclass
class SetLiteral:
    """
    AST node representing a set literal #{...} in source code.

    This is distinct from the runtime Set type (pds.Set).

    Attributes:
        items: List of elements in the set
        line: Source line number
        col: Source column number
        end_line: Ending line number
        end_col: Ending column number
    """

    items: list[Any]
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"SetLiteral({self.items!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "SetLiteral":
        """Return a new SetLiteral with the given location."""
        return SetLiteral(self.items, line, col, end_line or line, end_col)


@dataclass
class KwargsLiteral:
    """
    AST node representing a keyword arguments splat *{...} in source code.

    This is used in function calls to pass keyword arguments:
        (f 1 2 *{:name "Alice" :age 30})  => f(1, 2, name="Alice", age=30)

    Attributes:
        pairs: List of (key, value) tuples in the order they appeared
        line: Source line number
        col: Source column number
        end_line: Ending line number
        end_col: Ending column number
    """

    pairs: list[tuple[Any, Any]]
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"KwargsLiteral({self.pairs!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "KwargsLiteral":
        """Return a new KwargsLiteral with the given location."""
        return KwargsLiteral(self.pairs, line, col, end_line or line, end_col)


# Type exports
__all__ = [
    "Symbol",
    "Keyword",
    "Decorated",
    "VectorLiteral",
    "MapLiteral",
    "SetLiteral",
    "KwargsLiteral",
    "MatchError",
    "_MISSING",
]
