"""Lowering for quote and quasiquote forms."""

import ast

from spork.compiler.lowering import compile_expr
from spork.compiler.macros import is_symbol
from spork.runtime import Keyword, MapLiteral, SetLiteral, Symbol, VectorLiteral

_auto_gensym_counter = 0


def compile_quote(form):
    """
    Compile a quoted form into an AST expression that constructs the data structure.
    (quote x) returns x as data, not evaluated.
    Uses persistent data structures: Cons for lists, Vector for vectors, Map for maps.
    """
    # Literals return themselves
    if form is None or isinstance(form, (bool, int, float, str)):
        return ast.Constant(value=form)

    # Symbols become Symbol(...) constructor calls
    if isinstance(form, Symbol):
        return ast.Call(
            func=ast.Name(id="Symbol", ctx=ast.Load()),
            args=[ast.Constant(value=form.name)],
            keywords=[],
        )

    # Keywords become Keyword(...) constructor calls
    if isinstance(form, Keyword):
        return ast.Call(
            func=ast.Name(id="Keyword", ctx=ast.Load()),
            args=[ast.Constant(value=form.name)],
            keywords=[],
        )

    # Lists become Cons chains: (1 2 3) -> cons(1, cons(2, cons(3, None)))
    if isinstance(form, list):
        if len(form) == 0:
            return ast.Constant(value=None)
        # Build cons chain from right to left
        result = ast.Constant(value=None)
        for item in reversed(form):
            result = ast.Call(
                func=ast.Name(id="cons", ctx=ast.Load()),
                args=[compile_quote(item), result],
                keywords=[],
            )
        return result

    # VectorLiterals become vec(...) calls for Vector
    if isinstance(form, VectorLiteral):
        elements = [compile_quote(item) for item in form.items]
        return ast.Call(
            func=ast.Name(id="vec", ctx=ast.Load()),
            args=elements,
            keywords=[],
        )

    # MapLiterals become hash_map(...) calls for Map
    if isinstance(form, MapLiteral):
        args = []
        for k, v in form.pairs:
            # For map literals, keys are typically keywords - extract the name
            if isinstance(k, Keyword):
                args.append(ast.Constant(value=k.name))
            else:
                args.append(compile_quote(k))
            args.append(compile_quote(v))
        return ast.Call(
            func=ast.Name(id="hash_map", ctx=ast.Load()),
            args=args,
            keywords=[],
        )

    # SetLiterals become hash_set(...) calls for PSet
    if isinstance(form, SetLiteral):
        elements = [compile_quote(item) for item in form.items]
        list_node = ast.List(elts=elements, ctx=ast.Load())
        return ast.Call(
            func=ast.Name(id="hash_set", ctx=ast.Load()),
            args=[list_node],
            keywords=[],
        )

    raise TypeError(f"Cannot quote form: {form!r}")


def compile_quasiquote(form, gensym_map=None):
    """
    Compile a quasiquoted form.
    Like quote, but unquote (~) and unquote-splicing (~@) are evaluated.

    Supports auto-gensym: symbols ending in # (like temp#) are automatically
    replaced with unique generated symbols within the same quasiquote.
    """
    global _auto_gensym_counter

    # Initialize gensym_map for top-level call
    if gensym_map is None:
        gensym_map = {}

    # Check for unquote: ~x or (unquote x)
    if isinstance(form, list) and len(form) > 0:
        head = form[0]
        if is_symbol(head, "unquote"):
            if len(form) != 2:
                raise SyntaxError("unquote requires exactly 1 argument")
            # Evaluate the unquoted expression
            return compile_expr(form[1])

    # Literals return themselves
    if form is None or isinstance(form, (bool, int, float, str)):
        return ast.Constant(value=form)

    # Symbols and keywords get quoted
    if isinstance(form, Symbol):
        name = form.name
        # Check for auto-gensym suffix
        if name.endswith("#"):
            # Get or create a unique name for this gensym
            if name not in gensym_map:
                _auto_gensym_counter += 1
                base = name[:-1]  # Remove the #
                gensym_map[name] = f"__{base}_{_auto_gensym_counter}__"
            name = gensym_map[name]
        return ast.Call(
            func=ast.Name(id="Symbol", ctx=ast.Load()),
            args=[ast.Constant(value=name)],
            keywords=[],
        )

    if isinstance(form, Keyword):
        return ast.Call(
            func=ast.Name(id="Keyword", ctx=ast.Load()),
            args=[ast.Constant(value=form.name)],
            keywords=[],
        )

    # Lists: need to handle unquote-splicing
    if isinstance(form, list):
        result_parts = []
        for item in form:
            # Check for unquote-splicing: ~@x or (unquote-splicing x)
            if (
                isinstance(item, list)
                and len(item) > 0
                and is_symbol(item[0], "unquote-splicing")
            ):
                if len(item) != 2:
                    raise SyntaxError("unquote-splicing requires exactly 1 argument")
                # Mark this as a splicing operation
                result_parts.append(("splice", compile_expr(item[1])))
            else:
                # Regular item (may contain nested quasiquotes)
                result_parts.append(("item", compile_quasiquote(item, gensym_map)))

        # Build the result list
        if not result_parts:
            return ast.List(elts=[], ctx=ast.Load())

        # If no splicing, just return a list
        if all(kind == "item" for kind, _ in result_parts):
            return ast.List(elts=[expr for _, expr in result_parts], ctx=ast.Load())

        # If there's splicing, we need to concatenate lists
        # Start with an empty list and extend/append as needed
        list_parts = []
        current_items = []

        for kind, expr in result_parts:
            if kind == "item":
                current_items.append(expr)
            else:  # splice
                if current_items:
                    list_parts.append(ast.List(elts=current_items, ctx=ast.Load()))
                    current_items = []
                # Convert the spliced expression to a list if needed
                list_parts.append(
                    ast.Call(
                        func=ast.Name(id="list", ctx=ast.Load()),
                        args=[expr],
                        keywords=[],
                    )
                )

        if current_items:
            list_parts.append(ast.List(elts=current_items, ctx=ast.Load()))

        # Sum all the list parts together
        if len(list_parts) == 1:
            return list_parts[0]

        result = list_parts[0]
        for part in list_parts[1:]:
            result = ast.BinOp(left=result, op=ast.Add(), right=part)
        return result

    # VectorLiterals
    if isinstance(form, VectorLiteral):
        # Recursively quasiquote the items
        items_expr = compile_quasiquote(form.items, gensym_map)
        return ast.Call(
            func=ast.Name(id="VectorLiteral", ctx=ast.Load()),
            args=[items_expr],
            keywords=[],
        )

    # MapLiterals stay as MapLiterals (not Python dicts)
    if isinstance(form, MapLiteral):
        pairs = []
        for k, v in form.pairs:
            key_expr = compile_quasiquote(k, gensym_map)
            val_expr = compile_quasiquote(v, gensym_map)
            pairs.append(ast.Tuple(elts=[key_expr, val_expr], ctx=ast.Load()))
        pairs_list = ast.List(elts=pairs, ctx=ast.Load())
        return ast.Call(
            func=ast.Name(id="MapLiteral", ctx=ast.Load()),
            args=[pairs_list],
            keywords=[],
        )

    # SetLiterals become hash_set(...) calls
    if isinstance(form, SetLiteral):
        elements = [compile_quasiquote(item, gensym_map) for item in form.items]
        list_node = ast.List(elts=elements, ctx=ast.Load())
        return ast.Call(
            func=ast.Name(id="hash_set", ctx=ast.Load()),
            args=[list_node],
            keywords=[],
        )

    raise TypeError(f"Cannot quasiquote form: {form!r}")
