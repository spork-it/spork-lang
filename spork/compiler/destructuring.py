"""Lower destructuring binding patterns to Python assignments."""

import ast

from spork.compiler.generated_names import gensym
from spork.compiler.reader import copy_location, get_source_location, set_location
from spork.runtime import Keyword, MapLiteral, Symbol, VectorLiteral
from spork.runtime.types import normalize_name


def compile_destructure(pattern, value_expr, form_loc=None):
    """
    Compile destructuring assignment.

    pattern: Symbol, Vector, or dict representing the destructuring pattern
    value_expr: ast.expr representing the value being destructured
    form_loc: Optional source location for the generated statements

    Returns: List of ast.stmt (assignment statements)

    Supports:
    - Simple binding: symbol -> single assignment
    - Vector destructuring: [a b c] -> sequential element access
    - Vector with rest: [a b & rest] -> first N elements + rest
    - Dict with :keys: {:keys [x y]} -> extract named keys
    - Dict with key-value: {a :x b :y} -> bind 'a' to map[:x], 'b' to map[:y]
    - Nested patterns: [[a b] c] -> recursive destructuring
    """
    # Get location from pattern if form_loc not provided
    loc = form_loc or get_source_location(pattern)

    if isinstance(pattern, Symbol):
        # Simple binding
        target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
        copy_location(target, pattern)
        stmt = ast.Assign(targets=[target], value=value_expr)
        set_location(stmt, loc)
        return [stmt]

    if isinstance(pattern, VectorLiteral):
        # Sequence destructuring: [a b c] or [a b & rest]
        stmts = []
        items = pattern.items

        if not items:
            # Empty pattern, just evaluate the expression for side effects
            stmt = ast.Expr(value=value_expr)
            set_location(stmt, loc)
            return [stmt]

        # Check for & rest
        rest_idx = -1
        for i, item in enumerate(items):
            if isinstance(item, Symbol) and item.name == "&":
                rest_idx = i
                break
        has_rest = rest_idx >= 0

        # Use a temp var for the value to avoid re-evaluation
        temp = gensym("__destructure_")
        temp_name = ast.Name(id=temp, ctx=ast.Store())
        assign_stmt = ast.Assign(targets=[temp_name], value=value_expr)
        set_location(assign_stmt, loc)
        stmts.append(assign_stmt)
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        if has_rest:
            # Generate: first N bindings from value[:N], rest binding from value[N:]
            pre_rest = items[:rest_idx]
            if rest_idx + 1 >= len(items):
                raise SyntaxError("& must be followed by a binding pattern")
            rest_pattern = items[rest_idx + 1]

            # Bind pre-rest elements using nth for persistent structure support
            for i, sub_pattern in enumerate(pre_rest):
                elem = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(compile_destructure(sub_pattern, elem, loc))

            # Bind rest using drop for persistent structure support
            # Note: drop signature is (drop n coll), and we realize it with vec
            # to get a persistent vector instead of a lazy generator
            drop_call = ast.Call(
                func=ast.Name(id="drop", ctx=ast.Load()),
                args=[ast.Constant(value=len(pre_rest)), temp_load],
                keywords=[],
            )
            rest_val = ast.Call(
                func=ast.Name(id="vec", ctx=ast.Load()),
                args=[drop_call],
                keywords=[],
            )
            stmts.extend(compile_destructure(rest_pattern, rest_val, loc))
        else:
            # Simple sequence destructuring using nth
            for i, sub_pattern in enumerate(items):
                elem = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(compile_destructure(sub_pattern, elem, loc))

        return stmts

    if isinstance(pattern, MapLiteral):
        # Dict destructuring with Clojure-style syntax
        # MapLiteral preserves the original key-value pairs
        stmts = []

        if not pattern.pairs:
            # Empty pattern, just evaluate the expression for side effects
            stmt = ast.Expr(value=value_expr)
            set_location(stmt, loc)
            return [stmt]

        # Use a temp var for the value to avoid re-evaluation
        temp = gensym("__destructure_")
        temp_name = ast.Name(id=temp, ctx=ast.Store())
        assign_stmt = ast.Assign(targets=[temp_name], value=value_expr)
        set_location(assign_stmt, loc)
        stmts.append(assign_stmt)
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        # Check for :keys syntax: {:keys [x y]} means bind x to map["x"], y to map["y"]
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys":
                # :keys [x y z] syntax - look up by keyword
                if isinstance(value, VectorLiteral):
                    for sym in value.items:
                        if not isinstance(sym, Symbol):
                            raise SyntaxError(":keys must contain symbols")
                        # Create Keyword object for lookup
                        key_expr = ast.Call(
                            func=ast.Name(id="Keyword", ctx=ast.Load()),
                            args=[ast.Constant(value=sym.name)],
                            keywords=[],
                        )
                        elem = ast.Call(
                            func=ast.Name(id="get", ctx=ast.Load()),
                            args=[temp_load, key_expr],
                            keywords=[],
                        )
                        stmts.extend(compile_destructure(sym, elem, loc))
                else:
                    raise SyntaxError(":keys value must be a vector of symbols")
            elif isinstance(key, Symbol):
                # Clojure-style: {a :x b :y} means bind 'a' to value at key :x
                # key is the binding pattern, value is the lookup key
                if isinstance(value, Keyword):
                    # Create Keyword object for lookup
                    lookup_expr = ast.Call(
                        func=ast.Name(id="Keyword", ctx=ast.Load()),
                        args=[ast.Constant(value=value.name)],
                        keywords=[],
                    )
                elif isinstance(value, str):
                    lookup_expr = ast.Constant(value=value)
                else:
                    raise SyntaxError(
                        f"Dict destructuring key must be a keyword or string, got {type(value)}"
                    )
                elem = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, lookup_expr],
                    keywords=[],
                )
                stmts.extend(compile_destructure(key, elem, loc))
            else:
                raise SyntaxError(
                    f"Invalid dict destructuring pattern: {key!r} -> {value!r}"
                )

        return stmts

    raise SyntaxError(f"Invalid destructuring pattern: {pattern!r}")


def is_destructuring_pattern(form):
    """Check if a form is a destructuring pattern (VectorLiteral or MapLiteral, not Symbol)."""
    return isinstance(form, (VectorLiteral, MapLiteral))
