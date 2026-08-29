"""Analysis of single-, multi-, and pattern-arity function forms."""

from spork.compiler.macros import is_symbol
from spork.runtime import Decorated, Keyword, VectorLiteral


def is_multi_arity(args):
    """
    Check if defn/fn args represent multi-arity syntax.

    Multi-arity: (defn name ([x] x) ([x y] (+ x y)))
    Single-arity: (defn name [x y] (+ x y))

    For defn: args[0] is name, args[1] is either Vector (single) or list (multi)
    For fn: args[0] is either Vector (single) or list (multi)
    """
    if not args:
        return False
    # Check if first arg is a list starting with a VectorLiteral (arity clause)
    first = args[0]
    return isinstance(first, list) and first and isinstance(first[0], VectorLiteral)


def parse_arity(arity_form):
    """
    Parse a single arity clause like ([x y] (+ x y)).

    Returns: (params_vector, body_forms, min_args, has_vararg, has_kwargs)
    """
    if not isinstance(arity_form, list) or not arity_form:
        raise SyntaxError(f"Arity clause must be a list, got {type(arity_form)}")

    params = arity_form[0]
    if not isinstance(params, VectorLiteral):
        raise SyntaxError(f"Arity params must be a vector, got {type(params)}")

    body_forms = arity_form[1:] or [None]

    # Count positional args and check for varargs/kwargs
    min_args = 0
    has_vararg = False
    has_kwargs = False

    i = 0
    items = params.items
    while i < len(items):
        item = items[i]
        if is_symbol(item, "&"):
            has_vararg = True
            i += 2  # Skip & and vararg name
        elif is_symbol(item, "**"):
            has_kwargs = True
            i += 2  # Skip ** and kwargs name
        elif is_symbol(item, "*"):
            # Keyword-only marker - everything after is keyword-only
            i += 1
        else:
            # Regular positional arg (could have default)
            if not has_vararg and not is_symbol(item, "*"):
                min_args += 1
            i += 1

    return params, body_forms, min_args, has_vararg, has_kwargs


def parse_arity_with_patterns(arity_form):
    """
    Parse a single arity clause with pattern matching support.

    Syntax:
        ([pat1 pat2 ... patN] body...)
        ([pat1 pat2 ... patN :when guard] body...)

    Returns: (param_patterns, guard_expr, body_forms, arity, has_vararg, has_kwargs)

    Where param_patterns is a list of (pattern, type_expr) tuples.
    type_expr is None if no type annotation, otherwise the type expression.
    """
    if not isinstance(arity_form, list) or not arity_form:
        raise SyntaxError(f"Arity clause must be a list, got {type(arity_form)}")

    params = arity_form[0]
    if not isinstance(params, VectorLiteral):
        raise SyntaxError(f"Arity params must be a vector, got {type(params)}")

    body_forms = arity_form[1:] or [None]

    # Parse parameters and check for :when guard
    items = params.items
    guard_expr = None
    param_patterns = []
    arity = 0
    has_vararg = False
    has_kwargs = False

    i = 0
    while i < len(items):
        item = items[i]

        # Check for :when guard at end
        if isinstance(item, Keyword) and item.name == "when":
            if i + 1 >= len(items):
                raise SyntaxError(":when must be followed by a guard expression")
            guard_expr = items[i + 1]
            i += 2
            continue

        # Check for & vararg
        if is_symbol(item, "&"):
            has_vararg = True
            if i + 1 >= len(items):
                raise SyntaxError("& must be followed by a pattern")
            vararg_pattern = items[i + 1]
            # Check if next item is a type annotation
            if isinstance(vararg_pattern, Decorated):
                type_expr = vararg_pattern.expr
                if i + 2 >= len(items):
                    raise SyntaxError("Type annotation must be followed by a pattern")
                vararg_pattern = items[i + 2]
                param_patterns.append(("&", vararg_pattern, type_expr))
                i += 3
            else:
                param_patterns.append(("&", vararg_pattern, None))
                i += 2
            continue

        # Check for ** kwargs
        if is_symbol(item, "**"):
            has_kwargs = True
            if i + 1 >= len(items):
                raise SyntaxError("** must be followed by a pattern")
            kwargs_pattern = items[i + 1]
            param_patterns.append(("**", kwargs_pattern, None))
            i += 2
            continue

        # Check for * keyword-only marker
        if is_symbol(item, "*"):
            i += 1
            continue

        # Regular parameter - check for type annotation
        if isinstance(item, Decorated):
            type_expr = item.expr
            if i + 1 >= len(items):
                raise SyntaxError("Type annotation must be followed by a pattern")
            pattern = items[i + 1]
            # Skip :when if it appears right after type annotation
            if isinstance(pattern, Keyword) and pattern.name == "when":
                # This is a type-only pattern (implicit wildcard binding)
                # Actually, reparse - the :when applies to the whole clause
                param_patterns.append((item, None, type_expr))
                arity += 1
                i += 1
            else:
                param_patterns.append((pattern, None, type_expr))
                arity += 1
                i += 2
        else:
            # Simple pattern (symbol, vector, map, etc.)
            param_patterns.append((item, None, None))
            if not has_vararg:
                arity += 1
            i += 1

    return param_patterns, guard_expr, body_forms, arity, has_vararg, has_kwargs


def has_pattern_dispatch(arity_forms):
    """
    Check if any arity clause uses pattern matching features.
    This includes type patterns, guards, or non-simple destructuring.
    """
    for arity_form in arity_forms:
        if not isinstance(arity_form, list) or not arity_form:
            continue
        params = arity_form[0]
        if not isinstance(params, VectorLiteral):
            continue
        items = params.items
        for item in items:
            # Type annotation
            if isinstance(item, Decorated):
                return True
            # :when guard
            if isinstance(item, Keyword) and item.name == "when":
                return True
    return False
