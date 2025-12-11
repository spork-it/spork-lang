"""
spork.compiler.reader_macros - Reader Macro Types and Utilities

This module defines AST types for Spork's reader macros:

Core Syntax Extensions:
- AnonFnLiteral: #(...) hoisted lambda with %, %1-%N, %& args
- SliceLiteral: #[start stop step] with _ for None
- Discard: #_ form (read and discard)

Python Ecosystem:
- FStringLiteral: #f"..." with embedded Spork expressions
- PathLiteral: #p"..." for pathlib.Path
- RegexLiteral: #r"..." for re.compile (validated at compile time)

Data Integrity:
- UUIDLiteral: #uuid"..." for uuid.UUID
- InstLiteral: #inst"..." for ISO-8601 datetime

Meta:
- ReadTimeEval: #= form (evaluate at read/compile time)
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from spork.runtime.types import (
    MapLiteral,
    SetLiteral,
    Symbol,
    VectorLiteral,
)


@dataclass
class AnonFnLiteral:
    """
    AST node for #(...) anonymous function literal.

    Uses special arg placeholders:
    - % or %1: first argument
    - %2, %3, etc.: positional arguments
    - %&: rest args (variadic)

    Example:
        #((print "processing" %) (+ % 1))

    Compiles to a hoisted function definition that supports multiple statements.
    """

    body: list[Any]  # List of forms in the function body
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"AnonFnLiteral({self.body!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "AnonFnLiteral":
        return AnonFnLiteral(self.body, line, col, end_line or line, end_col)


@dataclass
class SliceLiteral:
    """
    AST node for #[start stop step] slice literal.

    Uses _ as placeholder for None.

    Examples:
        #[_ _ -1]  -> slice(None, None, -1)  ; reverse
        #[2 10]    -> slice(2, 10)           ; items 2-9
        #[0 _ 2]   -> slice(0, None, 2)      ; every other item
    """

    start: Any  # None or expression
    stop: Any  # None or expression
    step: Any  # None or expression
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"SliceLiteral({self.start!r}, {self.stop!r}, {self.step!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "SliceLiteral":
        return SliceLiteral(
            self.start, self.stop, self.step, line, col, end_line or line, end_col
        )


@dataclass
class FStringLiteral:
    """
    AST node for #f"..." f-string literal with embedded Spork expressions.

    The parts list alternates between string literals and embedded expressions.

    Example:
        #f"Hello {name}, 1+1 is {(+ 1 1)}"

    Compiles to Python's ast.JoinedStr (f-string).
    """

    parts: list[Any]  # Alternating strings and expressions
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"FStringLiteral({self.parts!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "FStringLiteral":
        return FStringLiteral(self.parts, line, col, end_line or line, end_col)


@dataclass
class PathLiteral:
    """
    AST node for #p"..." pathlib.Path literal.

    Example:
        #p"src/main.spork"

    Compiles to: pathlib.Path("src/main.spork")
    """

    path: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"PathLiteral({self.path!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "PathLiteral":
        return PathLiteral(self.path, line, col, end_line or line, end_col)


@dataclass
class RegexLiteral:
    """
    AST node for #r"..." regex literal.

    The regex pattern is validated at compile time.

    Example:
        #r"\\d{3}-\\d{2}"

    Compiles to: re.compile(r"\\d{3}-\\d{2}")
    """

    pattern: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"RegexLiteral({self.pattern!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "RegexLiteral":
        return RegexLiteral(self.pattern, line, col, end_line or line, end_col)


@dataclass
class UUIDLiteral:
    """
    AST node for #uuid"..." UUID literal.

    The UUID is validated at compile time.

    Example:
        #uuid"550e8400-e29b-41d4-a716-446655440000"

    Compiles to: uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    """

    value: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"UUIDLiteral({self.value!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "UUIDLiteral":
        return UUIDLiteral(self.value, line, col, end_line or line, end_col)


@dataclass
class InstLiteral:
    """
    AST node for #inst"..." ISO-8601 datetime literal.

    The datetime string is validated at compile time.

    Example:
        #inst"2025-12-10T00:00:00Z"

    Compiles to: datetime.datetime(2025, 12, 10, 0, 0, tzinfo=datetime.timezone.utc)
    """

    value: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"InstLiteral({self.value!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "InstLiteral":
        return InstLiteral(self.value, line, col, end_line or line, end_col)


@dataclass
class ReadTimeEval:
    """
    AST node for #= form read-time evaluation.

    The form is evaluated during compilation and the result is injected into the AST.

    Example:
        (def build-date #=(str (datetime.now)))

    Compiles to: the result of evaluating the expression at compile time.
    """

    form: Any
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"ReadTimeEval({self.form!r})"

    def with_location(
        self, line: int, col: int, end_line: int = 0, end_col: int = 0
    ) -> "ReadTimeEval":
        return ReadTimeEval(self.form, line, col, end_line or line, end_col)


# =============================================================================
# Discard Sentinel
# =============================================================================


class _DiscardSentinel:
    """Sentinel value indicating a discarded form (#_)."""

    __slots__ = ()
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "<DISCARD>"


DISCARD = _DiscardSentinel()


def is_discard(x) -> bool:
    """Check if x is the discard sentinel."""
    return x is DISCARD


# =============================================================================
# Argument Extraction for AnonFnLiteral
# =============================================================================


def extract_anon_fn_args(body: list[Any]) -> tuple[int, bool]:
    """
    Extract argument information from an anonymous function body.

    Scans the body for %, %1-%N, and %& placeholders and returns:
    - max_arg: The highest numbered argument used (0 if only % is used means 1 arg)
    - has_rest: Whether %& is used

    Returns:
        (max_arg, has_rest) where max_arg is the count of positional args needed
    """
    max_arg = 0
    has_rest = False

    def scan(form):
        nonlocal max_arg, has_rest

        if isinstance(form, Symbol):
            name = form.name
            if name == "%" or name == "%1":
                max_arg = max(max_arg, 1)
            elif name == "%&":
                has_rest = True
            elif name.startswith("%") and len(name) > 1:
                # %2, %3, etc.
                try:
                    n = int(name[1:])
                    max_arg = max(max_arg, n)
                except ValueError:
                    pass  # Not a valid arg placeholder
        elif isinstance(form, (list, tuple)):
            for item in form:
                scan(item)
        elif isinstance(form, VectorLiteral):
            for item in form.items:
                scan(item)
        elif isinstance(form, MapLiteral):
            for k, v in form.pairs:
                scan(k)
                scan(v)
        elif isinstance(form, SetLiteral):
            for item in form.items:
                scan(item)
        elif isinstance(form, AnonFnLiteral):
            # Don't scan nested anonymous functions - they have their own args
            pass

    for form in body:
        scan(form)

    return (max_arg, has_rest)


def transform_anon_fn_args(form, arg_mapping: dict[str, str]):
    """
    Transform argument placeholders in a form to actual parameter names.

    arg_mapping maps placeholder names to generated parameter names:
        {'%': '_1', '%1': '_1', '%2': '_2', '%&': '_rest'}
    """
    # Import here to avoid circular import - SourceList is in reader.py
    # which imports from this module
    from spork.compiler.reader import SourceList

    if isinstance(form, Symbol):
        name = form.name
        if name in arg_mapping:
            return Symbol(
                arg_mapping[name], form.line, form.col, form.end_line, form.end_col
            )
        return form
    elif isinstance(form, SourceList):
        transformed = [transform_anon_fn_args(item, arg_mapping) for item in form]
        return SourceList(transformed, form.line, form.col, form.end_line, form.end_col)
    elif isinstance(form, list):
        return [transform_anon_fn_args(item, arg_mapping) for item in form]
    elif isinstance(form, VectorLiteral):
        transformed = [transform_anon_fn_args(item, arg_mapping) for item in form.items]
        return VectorLiteral(
            transformed, form.line, form.col, form.end_line, form.end_col
        )
    elif isinstance(form, MapLiteral):
        transformed = [
            (
                transform_anon_fn_args(k, arg_mapping),
                transform_anon_fn_args(v, arg_mapping),
            )
            for k, v in form.pairs
        ]
        return MapLiteral(transformed, form.line, form.col, form.end_line, form.end_col)
    elif isinstance(form, SetLiteral):
        transformed = [transform_anon_fn_args(item, arg_mapping) for item in form.items]
        return SetLiteral(transformed, form.line, form.col, form.end_line, form.end_col)
    elif isinstance(form, AnonFnLiteral):
        # Don't transform nested anonymous functions
        return form
    else:
        return form


# =============================================================================
# Validation utilities
# =============================================================================


def validate_uuid(value: str, line: int = 0, col: int = 0) -> None:
    """Validate a UUID string at compile time."""
    try:
        uuid.UUID(value)
    except ValueError as e:
        raise SyntaxError(f"Invalid UUID literal at line {line}: {e}")


def validate_regex(pattern: str, line: int = 0, col: int = 0) -> None:
    """Validate a regex pattern at compile time."""
    try:
        re.compile(pattern)
    except re.error as e:
        raise SyntaxError(f"Invalid regex pattern at line {line}: {e}")


def validate_inst(value: str, line: int = 0, col: int = 0) -> None:
    """Validate an ISO-8601 datetime string at compile time."""
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            datetime.strptime(
                value.replace("+00:00", "Z").rstrip("Z") + "Z"
                if "Z" not in value and "+" not in value
                else value,
                fmt,
            )
            return
        except ValueError:
            continue

    try:
        test_value = value.replace("Z", "+00:00")
        datetime.fromisoformat(test_value)
        return
    except ValueError:
        pass

    raise SyntaxError(f"Invalid ISO-8601 datetime literal at line {line}: {value}")


def parse_inst(value: str) -> tuple:
    """
    Parse an ISO-8601 datetime string and return components for datetime constructor.

    Returns: (year, month, day, hour, minute, second, microsecond, has_tz, tz_offset_minutes)
    """
    # Normalize Z to +00:00
    normalized = value.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(normalized)
        has_tz = dt.tzinfo is not None
        tz_offset = 0
        if has_tz and dt.utcoffset():
            tz_offset = int(dt.utcoffset().total_seconds() // 60)
        return (
            dt.year,
            dt.month,
            dt.day,
            dt.hour,
            dt.minute,
            dt.second,
            dt.microsecond,
            has_tz,
            tz_offset,
        )
    except ValueError:
        pass

    raise ValueError(f"Cannot parse datetime: {value}")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AnonFnLiteral",
    "SliceLiteral",
    "FStringLiteral",
    "PathLiteral",
    "RegexLiteral",
    "UUIDLiteral",
    "InstLiteral",
    "ReadTimeEval",
    "DISCARD",
    "is_discard",
    "extract_anon_fn_args",
    "transform_anon_fn_args",
    "validate_uuid",
    "validate_regex",
    "validate_inst",
    "parse_inst",
]
