"""
spork.compiler.reader - Tokenizer and Reader for Spork source code

This module handles Phase 1 of compilation: reading source text and
converting it into Spork forms (S-expressions with source location tracking).

Components:
- SourceLocation: Holds line/column information for error messages
- Token: A token with its source location
- SourceList: A list that carries source location information
- tokenize(): Converts source text to tokens
- Reader: Converts tokens to forms (S-expressions)
- read_str(): Convenience function to read source string to forms

The reader produces forms using types from spork.runtime.types:
- Symbol: Variable/function names
- Keyword: Self-evaluating interned symbols (:keyword)
- VectorLiteral: [...] syntax
- MapLiteral: {...} syntax
- SetLiteral: #{...} syntax
- Decorated: ^decorator syntax
- SourceList: (...) lists with location info
"""

import ast
from dataclasses import dataclass
from typing import Any, Optional, TypeVar

from spork.runtime.types import (
    Decorated,
    Keyword,
    KwargsLiteral,
    MapLiteral,
    SetLiteral,
    Symbol,
    VectorLiteral,
)

# =============================================================================
# Source Location Tracking
# =============================================================================


@dataclass
class SourceLocation:
    """Holds source location information for debugging and error messages."""

    line: int = 0  # 1-based line number
    col: int = 0  # 0-based column offset
    end_line: int = 0
    end_col: int = 0

    def __repr__(self):
        return f"SourceLocation({self.line}:{self.col})"


@dataclass
class Token:
    """A token with its source location."""

    value: Any  # The token value (string, tuple for STRING, etc.)
    line: int  # 1-based line number
    col: int  # 0-based column offset

    def __repr__(self):
        return f"Token({self.value!r}, {self.line}:{self.col})"


class SourceList(list):
    """A list subclass that carries source location information.

    Used to represent S-expressions (parenthesized lists) while
    preserving source location for error messages.
    """

    __slots__ = ("line", "col", "end_line", "end_col")

    def __init__(self, items=None, line=0, col=0, end_line=0, end_col=0):
        super().__init__(items if items is not None else [])
        self.line = line
        self.col = col
        self.end_line = end_line
        self.end_col = end_col

    def get_location(self) -> SourceLocation:
        return SourceLocation(self.line, self.col, self.end_line, self.end_col)


# =============================================================================
# Source Location Utilities
# =============================================================================


def get_source_location(form) -> Optional[SourceLocation]:
    """Extract source location from a form if available."""
    if isinstance(form, SourceList):
        return form.get_location()
    if hasattr(form, "line") and hasattr(form, "col"):
        end_line = getattr(form, "end_line", form.line)
        end_col = getattr(form, "end_col", form.col)
        return SourceLocation(form.line, form.col, end_line, end_col)
    return None


_T = TypeVar("_T", bound=ast.AST)


def set_location(node: _T, loc: Optional[SourceLocation]) -> _T:
    """Set the source location on an AST node."""
    if loc is not None and loc.line > 0:
        node.lineno = loc.line  # type: ignore[attr-defined]
        node.col_offset = loc.col  # type: ignore[attr-defined]
        if loc.end_line > 0:
            node.end_lineno = loc.end_line  # type: ignore[attr-defined]
            node.end_col_offset = loc.end_col  # type: ignore[attr-defined]
    return node


def copy_location(node: _T, form) -> _T:
    """Copy source location from a form to an AST node."""
    loc = get_source_location(form)
    return set_location(node, loc)


# =============================================================================
# Tokenizer
# =============================================================================


def tokenize(src: str) -> list[Token]:
    """
    Tokenize source code into a list of Tokens with source locations.
    Each Token contains the token value and its line/column position.
    """
    tokens = []
    i = 0
    n = len(src)
    line = 1  # 1-based line number
    line_start = 0  # Index of the start of the current line

    WHITESPACE = " \t\r\n"
    # Note: # is NOT in delimiters because it can appear at end of symbols (gensym)
    # Set literal #{ is handled specially before the delimiter check
    delimiters = set("()[]{}")

    def current_col():
        return i - line_start

    while i < n:
        c = src[i]
        if c == "\n":
            i += 1
            line += 1
            line_start = i
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == ";":
            # comment to end of line
            while i < n and src[i] != "\n":
                i += 1
            continue

        tok_line = line
        tok_col = current_col()

        # Reader macros
        if c == "'":
            tokens.append(Token("'", tok_line, tok_col))
            i += 1
            continue
        if c == "^":
            # Check if this is a decorator (^ followed by something that starts an expression)
            # or a standalone symbol (^ followed by whitespace, closing delimiter, or EOF)
            # Opening delimiters like ( [ { start expressions, so ^(List int) is a decorator
            next_i = i + 1
            closing_delims = set(")]}")
            if (
                next_i >= n
                or src[next_i] in WHITESPACE
                or src[next_i] in closing_delims
                or src[next_i] == ";"
            ):
                # ^ is a standalone symbol - fall through to symbol parsing
                pass
            else:
                # Decorator: ^Type or ^(List int) - use tuple to distinguish from ^ symbol
                tokens.append(Token(("DECORATOR", "^"), tok_line, tok_col))
                i += 1
                continue
            # Fall through to symbol parsing (^ as a symbol)
        if c == "`":
            tokens.append(Token("`", tok_line, tok_col))
            i += 1
            continue
        if c == "~":
            if i + 1 < n and src[i + 1] == "@":
                tokens.append(Token(("UNQUOTE_SPLICING", "~@"), tok_line, tok_col))
                i += 2
                continue
            # Check if this is unquote (~ followed by something that starts an expression)
            # or a standalone symbol (~ followed by whitespace, closing delimiter, or EOF)
            next_i = i + 1
            closing_delims = set(")]}")
            if (
                next_i >= n
                or src[next_i] in WHITESPACE
                or src[next_i] in closing_delims
                or src[next_i] == ";"
            ):
                # ~ is a standalone symbol - fall through to symbol parsing
                pass
            else:
                # Unquote: ~expr - use tuple to distinguish from ~ symbol
                tokens.append(Token(("UNQUOTE", "~"), tok_line, tok_col))
                i += 1
                continue
            # Fall through to symbol parsing (~ as a symbol)
        if c == "#":
            # Check for set literal #{
            if i + 1 < n and src[i + 1] == "{":
                tokens.append(Token("#{", tok_line, tok_col))
                i += 2
                continue
            # Standalone # is the keyword-only marker
            tokens.append(Token("#", tok_line, tok_col))
            i += 1
            continue
        if c == "*":
            # Check for kwargs literal *{
            if i + 1 < n and src[i + 1] == "{":
                tokens.append(Token("*{", tok_line, tok_col))
                i += 2
                continue
            # Check for standalone * (keyword-only marker in defn, or kwargs separator in calls)
            # Standalone means followed by whitespace, delimiter, or EOF
            if i + 1 >= n or src[i + 1] in WHITESPACE or src[i + 1] in delimiters:
                tokens.append(Token("*", tok_line, tok_col))
                i += 1
                continue
            # Otherwise fall through to symbol parsing (e.g., *args in Python interop)
        if c in delimiters:
            tokens.append(Token(c, tok_line, tok_col))
            i += 1
            continue
        if c == '"':
            # string literal
            string_start_col = tok_col
            i += 1
            buf = []
            while i < n:
                if src[i] == "\\":
                    if i + 1 < n:
                        esc = src[i + 1]
                        if esc == "n":
                            buf.append("\n")
                        elif esc == "t":
                            buf.append("\t")
                        elif esc == "\n":
                            # Line continuation - skip the backslash and newline
                            i += 2
                            line += 1
                            line_start = i
                            continue
                        else:
                            buf.append(esc)
                        i += 2
                    else:
                        raise SyntaxError(f"unterminated string escape at line {line}")
                elif src[i] == "\n":
                    # Multi-line string
                    buf.append("\n")
                    i += 1
                    line += 1
                    line_start = i
                elif src[i] == '"':
                    i += 1
                    break
                else:
                    buf.append(src[i])
                    i += 1
            else:
                raise SyntaxError(f"unterminated string starting at line {tok_line}")
            tokens.append(Token(("STRING", "".join(buf)), tok_line, string_start_col))
            continue
        # symbol / number / keyword
        start = i
        while (
            i < n
            and src[i] not in WHITESPACE
            and src[i] not in delimiters
            and src[i] != ";"
        ):
            i += 1
        tok = src[start:i]
        tokens.append(Token(tok, tok_line, tok_col))
    return tokens


# =============================================================================
# Reader
# =============================================================================


class Reader:
    """
    Reader that parses tokens into forms with source location tracking.
    All produced forms carry line/column information for error reporting.
    """

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def eof(self):
        return self.i >= len(self.tokens)

    def peek(self) -> Optional[Token]:
        if self.eof():
            return None
        return self.tokens[self.i]

    def peek_value(self):
        """Get the value of the current token, or None if EOF."""
        tok = self.peek()
        return tok.value if tok else None

    def next(self) -> Optional[Token]:
        tok = self.peek()
        self.i += 1
        return tok

    def read(self):
        """Read all forms from the token stream."""
        forms = []
        while not self.eof():
            forms.append(self.read_form())
        return forms

    def read_form(self):
        """Read a single form from the token stream."""
        tok = self.peek()
        if tok is None:
            raise SyntaxError("Unexpected end of input")

        tok_value = tok.value
        tok_line = tok.line
        tok_col = tok.col

        # Reader macros
        if tok_value == "'":
            self.next()
            inner = self.read_form()
            inner_loc = get_source_location(inner)
            end_line = inner_loc.end_line if inner_loc else tok_line
            end_col = inner_loc.end_col if inner_loc else tok_col + 1
            return SourceList(
                [Symbol("quote", tok_line, tok_col, tok_line, tok_col + 1), inner],
                tok_line,
                tok_col,
                end_line,
                end_col,
            )
        if tok_value == "`":
            self.next()
            inner = self.read_form()
            inner_loc = get_source_location(inner)
            end_line = inner_loc.end_line if inner_loc else tok_line
            end_col = inner_loc.end_col if inner_loc else tok_col + 1
            return SourceList(
                [Symbol("quasiquote", tok_line, tok_col, tok_line, tok_col + 1), inner],
                tok_line,
                tok_col,
                end_line,
                end_col,
            )
        if isinstance(tok_value, tuple) and tok_value[0] == "UNQUOTE":
            self.next()
            inner = self.read_form()
            inner_loc = get_source_location(inner)
            end_line = inner_loc.end_line if inner_loc else tok_line
            end_col = inner_loc.end_col if inner_loc else tok_col + 1
            return SourceList(
                [Symbol("unquote", tok_line, tok_col, tok_line, tok_col + 1), inner],
                tok_line,
                tok_col,
                end_line,
                end_col,
            )
        if isinstance(tok_value, tuple) and tok_value[0] == "UNQUOTE_SPLICING":
            self.next()
            inner = self.read_form()
            inner_loc = get_source_location(inner)
            end_line = inner_loc.end_line if inner_loc else tok_line
            end_col = inner_loc.end_col if inner_loc else tok_col + 2
            return SourceList(
                [
                    Symbol(
                        "unquote-splicing", tok_line, tok_col, tok_line, tok_col + 2
                    ),
                    inner,
                ],
                tok_line,
                tok_col,
                end_line,
                end_col,
            )
        if isinstance(tok_value, tuple) and tok_value[0] == "DECORATOR":
            self.next()
            decorator_expr = self.read_form()
            dec_loc = get_source_location(decorator_expr)
            end_line = dec_loc.end_line if dec_loc else tok_line
            end_col = dec_loc.end_col if dec_loc else tok_col + 1
            return Decorated(decorator_expr, tok_line, tok_col, end_line, end_col)

        tok = self.next()
        assert tok is not None  # We already peeked and it was not None
        tok_value = tok.value
        tok_line = tok.line
        tok_col = tok.col

        if tok_value == "(":
            items, end_tok = self.read_list_with_end(")", tok_line, tok_col)
            end_line = end_tok.line if end_tok else tok_line
            end_col = end_tok.col + 1 if end_tok else tok_col + 1
            return SourceList(items, tok_line, tok_col, end_line, end_col)
        if tok_value == "[":
            items, end_tok = self.read_list_with_end("]", tok_line, tok_col)
            end_line = end_tok.line if end_tok else tok_line
            end_col = end_tok.col + 1 if end_tok else tok_col + 1
            return VectorLiteral(items, tok_line, tok_col, end_line, end_col)
        if tok_value == "{":
            items, end_tok = self.read_list_with_end("}", tok_line, tok_col)
            if len(items) % 2 != 0:
                raise SyntaxError(
                    f"Map literal must have even number of forms at line {tok_line}"
                )
            pairs = []
            for j in range(0, len(items), 2):
                k = items[j]
                v = items[j + 1]
                pairs.append((k, v))
            end_line = end_tok.line if end_tok else tok_line
            end_col = end_tok.col + 1 if end_tok else tok_col + 1
            return MapLiteral(pairs, tok_line, tok_col, end_line, end_col)
        if tok_value == "#{":
            items, end_tok = self.read_list_with_end("}", tok_line, tok_col)
            end_line = end_tok.line if end_tok else tok_line
            end_col = end_tok.col + 1 if end_tok else tok_col + 2
            return SetLiteral(items, tok_line, tok_col, end_line, end_col)
        if tok_value == "*{":
            items, end_tok = self.read_list_with_end("}", tok_line, tok_col)
            end_line = end_tok.line if end_tok else tok_line
            end_col = end_tok.col + 1 if end_tok else tok_col + 2
            # Parse mixed content: *{variable :key val :key2 val2 other_var}
            # - Symbols (non-keyword) are splat variables: (None, symbol)
            # - Keywords start key-value pairs: (keyword, value)
            pairs = []
            i = 0
            while i < len(items):
                item = items[i]
                if isinstance(item, Keyword):
                    # Keyword starts a key-value pair
                    if i + 1 >= len(items):
                        raise SyntaxError(
                            f"Keyword {item.name} must be followed by a value at line {tok_line}"
                        )
                    pairs.append((item, items[i + 1]))
                    i += 2
                elif isinstance(item, Symbol):
                    # Symbol is a splat variable: *{opts} -> **opts
                    pairs.append((None, item))
                    i += 1
                else:
                    raise SyntaxError(
                        f"Kwargs literal expects keywords or symbols, got {type(item).__name__} at line {tok_line}"
                    )
            return KwargsLiteral(pairs, tok_line, tok_col, end_line, end_col)
        if isinstance(tok_value, tuple) and tok_value[0] == "STRING":
            # Strings don't carry location info as they're Python primitives
            # We could wrap them, but for now just return the string value
            return tok_value[1]
        # atom
        return self.read_atom(tok)

    def read_list_with_end(
        self, end_delim, start_line: int = 0, start_col: int = 0
    ) -> tuple[list, Optional[Token]]:
        """Read a list and return both the items and the closing delimiter token."""
        items = []
        while True:
            if self.eof():
                raise SyntaxError(
                    f"unterminated list at line {start_line}, expected {end_delim}"
                )
            tok = self.peek()
            assert tok is not None  # We check for EOF above
            if tok.value == end_delim:
                end_tok = self.next()
                return items, end_tok
            items.append(self.read_form())

    def read_list(self, end_delim, start_line: int = 0, start_col: int = 0):
        """Read a list (for backward compatibility)."""
        items, _ = self.read_list_with_end(end_delim, start_line, start_col)
        return items

    def read_atom(self, tok: Token):
        """Read an atomic value (number, boolean, nil, keyword, or symbol)."""
        tok_value = tok.value
        tok_line = tok.line
        tok_col = tok.col

        # numbers
        try:
            if tok_value.startswith("0x") or tok_value.startswith("-0x"):
                return int(tok_value, 16)
            if "." in tok_value:
                return float(tok_value)
            return int(tok_value)
        except Exception:
            pass
        # booleans and nil (map to Python True/False/None)
        if tok_value == "true":
            return True
        if tok_value == "false":
            return False
        if tok_value == "nil":
            return None
        # keyword
        if tok_value.startswith(":") and len(tok_value) > 1:
            return Keyword(
                tok_value[1:], tok_line, tok_col, tok_line, tok_col + len(tok_value)
            )
        # symbol
        return Symbol(tok_value, tok_line, tok_col, tok_line, tok_col + len(tok_value))


# =============================================================================
# Convenience Functions
# =============================================================================


def read_str(src: str):
    """Phase 1: Read - tokenize and parse source into forms."""
    tokens = tokenize(src)
    rdr = Reader(tokens)
    return rdr.read()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Source location
    "SourceLocation",
    "Token",
    "SourceList",
    "get_source_location",
    "set_location",
    "copy_location",
    # Tokenizer
    "tokenize",
    # Reader
    "Reader",
    "read_str",
]
