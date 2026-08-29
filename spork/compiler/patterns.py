"""Pattern analysis and lowering for ``match`` expressions."""

import ast

from spork.compiler.annotations import compile_type_annotation
from spork.compiler.context import get_compile_context
from spork.compiler.generated_names import gensym
from spork.compiler.lowering import compile_expr
from spork.compiler.reader import get_source_location, set_location
from spork.runtime import Decorated, Keyword, MapLiteral, Symbol, VectorLiteral
from spork.runtime.types import normalize_name


def make_keyword_expr(name: str) -> ast.Call:
    """Create an AST expression that constructs a Keyword object."""
    return ast.Call(
        func=ast.Name(id="Keyword", ctx=ast.Load()),
        args=[ast.Constant(value=name)],
        keywords=[],
    )


def is_wildcard_pattern(pattern):
    """Check if pattern is the wildcard _."""
    return isinstance(pattern, Symbol) and pattern.name == "_"


def is_literal_pattern(pattern):
    """Check if pattern is a literal (nil, true, false, number, string, keyword)."""
    if pattern is None:
        return True
    if isinstance(pattern, bool):
        return True
    if isinstance(pattern, (int, float, str)):
        return True
    if isinstance(pattern, Keyword):
        return True
    if isinstance(pattern, Symbol) and pattern.name in ("nil", "true", "false"):
        return True
    return False


def is_type_pattern(pattern):
    """
    Check if pattern is a type pattern: (^Type pat) or (^Type pat :when guard).
    A type pattern is a list where the first element is a Decorated form.
    """
    if not isinstance(pattern, list) or len(pattern) < 1:
        return False
    first = pattern[0]
    return isinstance(first, Decorated)


def is_guarded_pattern(pattern):
    """
    Check if pattern has a guard: (pat :when guard-expr).
    Returns True if the pattern is a list with :when as second-to-last element.
    """
    if not isinstance(pattern, list) or len(pattern) < 3:
        return False
    # Check for :when keyword
    for item in pattern:
        if isinstance(item, Keyword) and item.name == "when":
            return True
    return False


def parse_guarded_pattern(pattern):
    """
    Parse a guarded pattern (pat :when guard-expr).
    Returns (inner_pattern, guard_expr).
    If not guarded, returns (pattern, None).
    """
    if not isinstance(pattern, list) or len(pattern) < 3:
        return pattern, None

    # Look for :when keyword
    for i, item in enumerate(pattern):
        if isinstance(item, Keyword) and item.name == "when":
            if i + 1 >= len(pattern):
                raise SyntaxError(":when must be followed by a guard expression")
            # Everything before :when is the pattern, after is the guard
            if i == 1:
                inner_pattern = pattern[0]
            else:
                inner_pattern = pattern[:i]
            guard_expr = pattern[i + 1]
            return inner_pattern, guard_expr

    return pattern, None


def parse_type_pattern(pattern):
    """
    Parse a type pattern (^Type pat) or (^Type pat :when guard).
    Returns (type_expr, inner_pattern, guard_expr).
    """
    if not isinstance(pattern, list) or len(pattern) < 1:
        raise SyntaxError(f"Invalid type pattern: {pattern}")

    first = pattern[0]
    if not isinstance(first, Decorated):
        raise SyntaxError(f"Type pattern must start with ^Type, got {first}")

    type_expr = first.expr

    # Rest of pattern after the type
    if len(pattern) == 1:
        # (^Type) alone - just type check, bind nothing (implicit wildcard)
        return type_expr, Symbol("_"), None
    elif len(pattern) == 2:
        # (^Type pat)
        return type_expr, pattern[1], None
    else:
        # (^Type pat :when guard) or (^Type pat1 pat2 ...)
        # Check for :when
        for i, item in enumerate(pattern[1:], start=1):
            if isinstance(item, Keyword) and item.name == "when":
                if i + 1 >= len(pattern):
                    raise SyntaxError(":when must be followed by a guard expression")
                inner_pattern = pattern[1] if i == 2 else pattern[1:i]
                guard_expr = pattern[i + 1]
                return type_expr, inner_pattern, guard_expr
        # No guard, pattern is everything after type
        if len(pattern) == 2:
            return type_expr, pattern[1], None
        else:
            return type_expr, pattern[1], None


def compile_pattern_check(
    pattern, value_expr, ok_var, bindings_list, type_annotation=None
):
    """
    Compile pattern matching checks and bindings.

    Args:
        pattern: The pattern to match
        value_expr: AST expression for the value being matched
        ok_var: Name of the boolean flag variable (e.g., "__match_ok__")
        bindings_list: List to append (name, value_expr, type_annotation) tuples for bindings
        type_annotation: Optional compiled type AST to attach to symbol bindings

    Returns:
        List of AST statements that:
        1. Check if pattern matches (setting ok_var to False if not)
        2. Bind variables if pattern matches (with type annotations when present)
    """
    stmts = []
    loc = get_source_location(pattern)

    # Wildcard: always matches, binds nothing
    if is_wildcard_pattern(pattern):
        return stmts

    # Literal patterns: match by value equality
    if is_literal_pattern(pattern):
        # Convert pattern to its Python value
        if pattern is None:
            literal_val = ast.Constant(value=None)
        elif isinstance(pattern, bool):
            literal_val = ast.Constant(value=pattern)
        elif isinstance(pattern, Symbol):
            if pattern.name == "nil":
                literal_val = ast.Constant(value=None)
            elif pattern.name == "true":
                literal_val = ast.Constant(value=True)
            elif pattern.name == "false":
                literal_val = ast.Constant(value=False)
            else:
                raise SyntaxError(f"Unknown literal symbol: {pattern.name}")
        elif isinstance(pattern, Keyword):
            literal_val = make_keyword_expr(pattern.name)
        else:
            literal_val = ast.Constant(value=pattern)

        # if ok_var and value != literal: ok_var = False
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.Compare(
                        left=value_expr,
                        ops=[ast.NotEq()],
                        comparators=[literal_val],
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)
        return stmts

    # Symbol pattern: bind the value (with type annotation if present)
    if isinstance(pattern, Symbol):
        bindings_list.append((pattern.name, value_expr, type_annotation))
        return stmts

    # Type pattern: (^Type pat)
    if is_type_pattern(pattern):
        type_expr, inner_pattern, guard = parse_type_pattern(pattern)

        # Compile the type expression
        type_ast = compile_expr(type_expr)

        # if ok_var and not isinstance(value, type): ok_var = False
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.UnaryOp(
                        op=ast.Not(),
                        operand=ast.Call(
                            func=ast.Name(id="isinstance", ctx=ast.Load()),
                            args=[value_expr, type_ast],
                            keywords=[],
                        ),
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)

        # Recursively match inner pattern against the same value
        # Pass the type annotation from this type pattern to inner bindings
        inner_type_annotation = compile_type_annotation(type_expr)
        stmts.extend(
            compile_pattern_check(
                inner_pattern, value_expr, ok_var, bindings_list, inner_type_annotation
            )
        )

        # Handle guard if present (for type patterns with inline guards)
        if guard is not None:
            # The guard will be handled at the outer level
            pass

        return stmts

    # VectorLiteral pattern: [p1 p2 ... pn] or [p1 p2 ... pk & rest]
    if isinstance(pattern, VectorLiteral):
        items = pattern.items
        if not items:
            # Empty vector: check length == 0
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            value_expr,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[value_expr],
                                            keywords=[],
                                        ),
                                        ops=[ast.Eq()],
                                        comparators=[ast.Constant(value=0)],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)
            return stmts

        # Check for & rest
        rest_idx = -1
        for i, item in enumerate(items):
            if isinstance(item, Symbol) and item.name == "&":
                rest_idx = i
                break
        has_rest = rest_idx >= 0

        # Create a temp variable to hold the value
        temp = gensym("__match_seq_")
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id=temp, ctx=ast.Store())],
                value=value_expr,
            )
        )
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        if has_rest:
            # [p1 p2 ... pk & rest]: check len >= k
            pre_rest_count = rest_idx
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            temp_load,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[temp_load],
                                            keywords=[],
                                        ),
                                        ops=[ast.GtE()],
                                        comparators=[
                                            ast.Constant(value=pre_rest_count)
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)

            # Match pre-rest patterns
            for i in range(pre_rest_count):
                elem_expr = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(items[i], elem_expr, ok_var, bindings_list)
                )

            # Match rest pattern
            if rest_idx + 1 < len(items):
                rest_pattern = items[rest_idx + 1]
                # Note: drop signature is (drop n coll), realize with vec
                drop_call = ast.Call(
                    func=ast.Name(id="drop", ctx=ast.Load()),
                    args=[ast.Constant(value=pre_rest_count), temp_load],
                    keywords=[],
                )
                rest_expr = ast.Call(
                    func=ast.Name(id="vec", ctx=ast.Load()),
                    args=[drop_call],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(
                        rest_pattern, rest_expr, ok_var, bindings_list
                    )
                )
        else:
            # [p1 p2 ... pn]: check len == n
            n = len(items)
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            temp_load,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[temp_load],
                                            keywords=[],
                                        ),
                                        ops=[ast.Eq()],
                                        comparators=[ast.Constant(value=n)],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)

            # Match each sub-pattern
            for i, sub_pattern in enumerate(items):
                elem_expr = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(sub_pattern, elem_expr, ok_var, bindings_list)
                )

        return stmts

    # Map pattern: {:keys [k1 k2]} or {local :key}
    if isinstance(pattern, MapLiteral):
        # Create a temp variable to hold the value
        temp = gensym("__match_map_")
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id=temp, ctx=ast.Store())],
                value=value_expr,
            )
        )
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        # Check that value is map-like (has __getitem__ or is dict/Map)
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.UnaryOp(
                        op=ast.Not(),
                        operand=ast.Call(
                            func=ast.Name(id="hasattr", ctx=ast.Load()),
                            args=[temp_load, ast.Constant(value="__getitem__")],
                            keywords=[],
                        ),
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)

        # Process each key-value pair in the pattern
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys":
                # :keys [k1 k2 k3] syntax - look up by Keyword objects
                if isinstance(value, VectorLiteral):
                    for sym in value.items:
                        if not isinstance(sym, Symbol):
                            raise SyntaxError(":keys must contain symbols")
                        key_expr = make_keyword_expr(sym.name)
                        # Check key exists
                        key_check = ast.If(
                            test=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Name(id=ok_var, ctx=ast.Load()),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="get", ctx=ast.Load()),
                                            args=[
                                                temp_load,
                                                key_expr,
                                                ast.Name(id="_MISSING", ctx=ast.Load()),
                                            ],
                                            keywords=[],
                                        ),
                                        ops=[ast.Is()],
                                        comparators=[
                                            ast.Name(id="_MISSING", ctx=ast.Load())
                                        ],
                                    ),
                                ],
                            ),
                            body=[
                                ast.Assign(
                                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                                    value=ast.Constant(value=False),
                                )
                            ],
                            orelse=[],
                        )
                        set_location(key_check, loc)
                        stmts.append(key_check)
                        # Bind the value
                        bindings_list.append(
                            (
                                sym.name,
                                ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[temp_load, make_keyword_expr(sym.name)],
                                    keywords=[],
                                ),
                            )
                        )
                else:
                    raise SyntaxError(":keys value must be a vector of symbols")
            elif isinstance(key, Symbol):
                # Clojure-style: {a :x} means bind 'a' to value at key :x
                if isinstance(value, Keyword):
                    lookup_expr = make_keyword_expr(value.name)
                elif isinstance(value, str):
                    lookup_expr = ast.Constant(value=value)
                else:
                    raise SyntaxError(
                        f"Map pattern key must be a keyword or string, got {type(value)}"
                    )
                # Check key exists
                key_check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.Compare(
                                left=ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[
                                        temp_load,
                                        lookup_expr,
                                        ast.Name(id="_MISSING", ctx=ast.Load()),
                                    ],
                                    keywords=[],
                                ),
                                ops=[ast.Is()],
                                comparators=[ast.Name(id="_MISSING", ctx=ast.Load())],
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                set_location(key_check, loc)
                stmts.append(key_check)
                # Bind or match the value pattern
                if isinstance(value, Keyword):
                    lookup_expr2 = make_keyword_expr(value.name)
                elif isinstance(value, str):
                    lookup_expr2 = ast.Constant(value=value)
                else:
                    lookup_expr2 = lookup_expr
                elem_expr = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, lookup_expr2],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(key, elem_expr, ok_var, bindings_list)
                )
            elif isinstance(key, Keyword):
                # Reverse syntax: {:x a} means bind 'a' to value at key :x
                lookup_expr = make_keyword_expr(key.name)
                # Check key exists
                key_check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.Compare(
                                left=ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[
                                        temp_load,
                                        lookup_expr,
                                        ast.Name(id="_MISSING", ctx=ast.Load()),
                                    ],
                                    keywords=[],
                                ),
                                ops=[ast.Is()],
                                comparators=[ast.Name(id="_MISSING", ctx=ast.Load())],
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                set_location(key_check, loc)
                stmts.append(key_check)
                # Bind or match the value pattern
                elem_expr = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, make_keyword_expr(key.name)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(value, elem_expr, ok_var, bindings_list)
                )
            else:
                raise SyntaxError(f"Invalid map pattern key: {key!r}")

        return stmts

    # Guarded pattern at top level: (pat :when guard)
    if is_guarded_pattern(pattern):
        inner_pattern, guard = parse_guarded_pattern(pattern)
        # Just match the inner pattern; guard is handled by caller
        stmts.extend(
            compile_pattern_check(inner_pattern, value_expr, ok_var, bindings_list)
        )
        return stmts

    raise SyntaxError(f"Invalid pattern: {pattern!r}")


def compile_match_case(pattern, result_expr, target_var, result_var, matched_var):
    """
    Compile a single match case.

    Returns a list of AST statements that:
    1. Check if pattern matches target_var
    2. If match succeeds (and guard passes), evaluate result_expr and set result_var, matched_var
    """
    stmts = []
    ok_var = gensym("__match_ok_")
    bindings_list = []

    # Parse guard if present
    inner_pattern, guard_expr = parse_guarded_pattern(pattern)

    # Initialize match ok flag
    stmts.append(
        ast.Assign(
            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
            value=ast.Constant(value=True),
        )
    )

    # Compile pattern checks
    target_load = ast.Name(id=target_var, ctx=ast.Load())
    stmts.extend(
        compile_pattern_check(inner_pattern, target_load, ok_var, bindings_list)
    )

    # Build the body that runs when pattern matches
    match_body = []

    # Add bindings - handle both 2-tuple and 3-tuple formats
    for binding in bindings_list:
        if len(binding) == 3:
            name, val_expr, type_annotation = binding
        else:
            # Backward compatibility with 2-tuple format
            name, val_expr = binding
            type_annotation = None

        if type_annotation is not None:
            # Emit annotated assignment: x: int = value
            match_body.append(
                ast.AnnAssign(
                    target=ast.Name(id=normalize_name(name), ctx=ast.Store()),
                    annotation=type_annotation,
                    value=val_expr,
                    simple=1,
                )
            )
        else:
            match_body.append(
                ast.Assign(
                    targets=[ast.Name(id=normalize_name(name), ctx=ast.Store())],
                    value=val_expr,
                )
            )

    # Save nested functions count before compiling result/guard
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)

    # Compile guard check and result
    if guard_expr is not None:
        # if guard_expr: result_var = result_expr; matched_var = True
        guard_compiled = compile_expr(guard_expr)
        result_compiled = compile_expr(result_expr)

        # Extract nested functions generated during compilation
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

        # Add nested function definitions before the guard check
        match_body.extend(nested_funcs)

        guard_if = ast.If(
            test=guard_compiled,
            body=[
                ast.Assign(
                    targets=[ast.Name(id=result_var, ctx=ast.Store())],
                    value=result_compiled,
                ),
                ast.Assign(
                    targets=[ast.Name(id=matched_var, ctx=ast.Store())],
                    value=ast.Constant(value=True),
                ),
            ],
            orelse=[],
        )
        match_body.append(guard_if)
    else:
        # No guard: result_var = result_expr; matched_var = True
        result_compiled = compile_expr(result_expr)

        # Extract nested functions generated during compilation
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

        # Add nested function definitions before the result assignment
        match_body.extend(nested_funcs)

        match_body.append(
            ast.Assign(
                targets=[ast.Name(id=result_var, ctx=ast.Store())],
                value=result_compiled,
            )
        )
        match_body.append(
            ast.Assign(
                targets=[ast.Name(id=matched_var, ctx=ast.Store())],
                value=ast.Constant(value=True),
            )
        )

    # Wrap in: if not matched_var: if ok_var: <match_body>
    inner_if = ast.If(
        test=ast.Name(id=ok_var, ctx=ast.Load()),
        body=match_body if match_body else [ast.Pass()],
        orelse=[],
    )

    outer_if = ast.If(
        test=ast.UnaryOp(
            op=ast.Not(),
            operand=ast.Name(id=matched_var, ctx=ast.Load()),
        ),
        body=stmts + [inner_if],
        orelse=[],
    )

    return [outer_if]


def compile_match_expr(args, form_loc=None):
    """
    Compile (match expr pattern1 result1 pattern2 result2 ...).

    Returns an AST expression using IIFE pattern.
    """
    if len(args) < 1:
        raise SyntaxError("match requires at least an expression")
    if len(args) < 3:
        raise SyntaxError("match requires at least one pattern-result pair")
    if (len(args) - 1) % 2 != 0:
        raise SyntaxError("match requires pairs of patterns and results")

    target_expr = args[0]
    cases = []
    for i in range(1, len(args), 2):
        pattern = args[i]
        result = args[i + 1]
        cases.append((pattern, result))

    # Generate variable names
    target_var = gensym("__match_target_")
    result_var = gensym("__match_result_")
    matched_var = gensym("__match_matched_")
    fn_name = gensym("__match_fn_")

    # Build function body
    body_stmts = []

    # target_var = expr
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=target_var, ctx=ast.Store())],
            value=compile_expr(target_expr),
        )
    )

    # matched_var = False
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=matched_var, ctx=ast.Store())],
            value=ast.Constant(value=False),
        )
    )

    # result_var = None (placeholder)
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=result_var, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )

    # Compile each case
    for pattern, result in cases:
        case_stmts = compile_match_case(
            pattern, result, target_var, result_var, matched_var
        )
        body_stmts.extend(case_stmts)

    # if not matched_var: raise MatchError(...)
    body_stmts.append(
        ast.If(
            test=ast.UnaryOp(
                op=ast.Not(),
                operand=ast.Name(id=matched_var, ctx=ast.Load()),
            ),
            body=[
                ast.Raise(
                    exc=ast.Call(
                        func=ast.Name(id="MatchError", ctx=ast.Load()),
                        args=[
                            ast.Constant(value="No pattern matched in match expression")
                        ],
                        keywords=[],
                    ),
                    cause=None,
                )
            ],
            orelse=[],
        )
    )

    # return result_var
    body_stmts.append(ast.Return(value=ast.Name(id=result_var, ctx=ast.Load())))

    # Create the wrapper function
    fn_def = ast.FunctionDef(
        name=fn_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=body_stmts,
        decorator_list=[],
    )

    # Register the function
    get_compile_context().add_function(fn_def)

    # Return call to the function
    return ast.Call(
        func=ast.Name(id=fn_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )
