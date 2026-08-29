"""Lowering for assignment and control-effect forms."""

import ast

from spork.compiler.context import get_compile_context
from spork.compiler.lowering import compile_expr
from spork.compiler.macros import is_symbol
from spork.compiler.reader import set_location
from spork.runtime import Symbol
from spork.runtime.types import normalize_name


def compile_set_expr(args):
    """
    Compile (set! target value) as expression using walrus operator.
    Returns the value being set.
    """
    if len(args) != 2:
        raise SyntaxError("set! requires target and value")

    target_form = args[0]
    value_form = args[1]
    value = compile_expr(value_form)

    if isinstance(target_form, Symbol):
        name = target_form.name
        # Handle dotted symbols like self.x -> attribute assignment
        if "." in name:
            parts = name.split(".")
            node: ast.expr = ast.Name(id=normalize_name(parts[0]), ctx=ast.Load())
            for attr in parts[1:-1]:
                node = ast.Attribute(
                    value=node, attr=normalize_name(attr), ctx=ast.Load()
                )
            attr_name = normalize_name(parts[-1])
            # Use spork_setattr helper which returns the value
            return ast.Call(
                func=ast.Name(id="spork_setattr", ctx=ast.Load()),
                args=[node, ast.Constant(value=attr_name), value],
                keywords=[],
            )
        else:
            return ast.NamedExpr(
                target=ast.Name(id=normalize_name(name), ctx=ast.Store()),
                value=value,
            )

    # Handle (set! (. obj attr) value) as expression
    elif isinstance(target_form, list) and target_form:
        head = target_form[0]

        if is_symbol(head, "."):
            if len(target_form) != 3:
                raise SyntaxError(
                    "set! expression with . requires exactly base and one attribute"
                )
            base_form = target_form[1]
            attr_form = target_form[2]

            if not isinstance(attr_form, Symbol):
                raise SyntaxError("attribute name must be a symbol")

            base_expr = compile_expr(base_form)
            attr_name = normalize_name(attr_form.name)

            # Use spork_setattr helper which returns the value
            return ast.Call(
                func=ast.Name(id="spork_setattr", ctx=ast.Load()),
                args=[base_expr, ast.Constant(value=attr_name), value],
                keywords=[],
            )

    raise SyntaxError("set! expression requires simple symbol or (. obj attr) target")


def compile_return(args, form_loc=None):
    """Compile (return expr) to ast.Return."""
    if len(args) == 0:
        node = ast.Return(value=ast.Constant(value=None))
    elif len(args) == 1:
        node = ast.Return(value=compile_expr(args[0]))
    else:
        raise SyntaxError("return takes 0 or 1 argument")
    set_location(node, form_loc)
    return node


def compile_throw(args, form_loc=None):
    """Compile (throw expr) to ast.Raise."""
    if len(args) == 0:
        raise SyntaxError("throw requires an exception expression")
    elif len(args) == 1:
        node = ast.Raise(exc=compile_expr(args[0]), cause=None)
    else:
        raise SyntaxError("throw takes exactly 1 argument")
    set_location(node, form_loc)
    return node


def compile_yield(args, form_loc=None):
    """Compile (yield) or (yield expr) to ast.Expr(ast.Yield(...))."""
    if len(args) == 0:
        node = ast.Expr(value=ast.Yield(value=None))
    elif len(args) == 1:
        node = ast.Expr(value=ast.Yield(value=compile_expr(args[0])))
    else:
        raise SyntaxError("yield takes 0 or 1 argument")
    set_location(node, form_loc)
    return node


def compile_yield_expr(args):
    """Compile (yield) or (yield expr) as an expression."""
    if len(args) == 0:
        return ast.Yield(value=None)
    elif len(args) == 1:
        return ast.Yield(value=compile_expr(args[0]))
    else:
        raise SyntaxError("yield takes 0 or 1 argument")


def compile_yield_from(args, form_loc=None):
    """Compile (yield-from expr) to ast.Expr(ast.YieldFrom(...))."""
    if len(args) != 1:
        raise SyntaxError("yield-from requires exactly 1 argument")
    node = ast.Expr(value=ast.YieldFrom(value=compile_expr(args[0])))
    set_location(node, form_loc)
    return node


def compile_yield_from_expr(args):
    """Compile (yield-from expr) as an expression."""
    if len(args) != 1:
        raise SyntaxError("yield-from requires exactly 1 argument")
    return ast.YieldFrom(value=compile_expr(args[0]))


def compile_await(args, form_loc=None):
    """Compile (await expr) to ast.Expr(ast.Await(...))."""
    if len(args) != 1:
        raise SyntaxError("await requires exactly 1 argument")
    node = ast.Expr(value=ast.Await(value=compile_expr(args[0])))
    set_location(node, form_loc)
    return node


def compile_await_expr(args):
    """Compile (await expr) as an expression."""
    if len(args) != 1:
        raise SyntaxError("await requires exactly 1 argument")
    return ast.Await(value=compile_expr(args[0]))


def compile_throw_expr(args):
    """
    Compile (throw expr) as an expression.
    Uses an immediately-invoked lambda that raises.
    """
    if len(args) != 1:
        raise SyntaxError("throw requires exactly 1 argument")

    return ast.Call(
        func=ast.Lambda(
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[],
            ),
            body=ast.IfExp(
                test=ast.Constant(value=True),
                body=ast.Call(
                    func=ast.Name(id="spork_raise", ctx=ast.Load()),
                    args=[compile_expr(args[0])],
                    keywords=[],
                ),
                orelse=ast.Constant(value=None),
            ),
        ),
        args=[],
        keywords=[],
    )


def compile_set(args, form_loc=None):
    """
    Compile (set! target value) to assignment.
    Handles: (set! x val), (set! self.x val), (set! (. obj attr) val),
             and (set! (nth coll idx) val) for mutable collection indexing.
    """
    if len(args) != 2:
        raise SyntaxError("set! requires target and value")

    target_form = args[0]
    value_form = args[1]
    value = compile_expr(value_form)

    if isinstance(target_form, Symbol):
        name = target_form.name
        # Handle dotted symbols like self.x -> attribute assignment
        if "." in name:
            parts = name.split(".")
            node: ast.expr = ast.Name(id=normalize_name(parts[0]), ctx=ast.Load())
            for attr in parts[1:-1]:
                node = ast.Attribute(
                    value=node, attr=normalize_name(attr), ctx=ast.Load()
                )
            target = ast.Attribute(
                value=node, attr=normalize_name(parts[-1]), ctx=ast.Store()
            )
            stmt = ast.Assign(targets=[target], value=value)
            set_location(stmt, form_loc)
            return stmt
        else:
            normalized_name = normalize_name(name)
            # Check if this variable is from an outer scope and mark for nonlocal
            ctx = get_compile_context()
            if ctx.nonlocal_stack and ctx.scope_stack:
                # Variable is from outer scope if it's in any scope but not the current one
                if ctx.is_in_any_scope(normalized_name) and not ctx.is_in_current_scope(
                    normalized_name
                ):
                    ctx.mark_nonlocal(normalized_name)
            target = ast.Name(id=normalized_name, ctx=ast.Store())
            stmt = ast.Assign(targets=[target], value=value)
            set_location(stmt, form_loc)
            return stmt

    elif isinstance(target_form, list) and target_form:
        head = target_form[0]

        if is_symbol(head, "."):
            if len(target_form) < 3:
                raise SyntaxError(
                    "set! with . requires base and at least one attribute"
                )
            base_form = target_form[1]
            attrs = target_form[2:]

            base_expr = compile_expr(base_form)
            node = base_expr
            for attr_form in attrs[:-1]:
                if not isinstance(attr_form, Symbol):
                    raise SyntaxError("attribute names must be symbols")
                node = ast.Attribute(
                    value=node, attr=normalize_name(attr_form.name), ctx=ast.Load()
                )

            if not isinstance(attrs[-1], Symbol):
                raise SyntaxError("attribute names must be symbols")
            target = ast.Attribute(
                value=node, attr=normalize_name(attrs[-1].name), ctx=ast.Store()
            )
            stmt = ast.Assign(targets=[target], value=value)
            set_location(stmt, form_loc)
            return stmt

        # Handle (set! (nth coll idx) val) -> coll[idx] = val
        if is_symbol(head, "nth"):
            if len(target_form) != 3:
                raise SyntaxError("set! with nth requires collection and index")
            coll_form = target_form[1]
            idx_form = target_form[2]

            coll_expr = compile_expr(coll_form)
            idx_expr = compile_expr(idx_form)

            target = ast.Subscript(value=coll_expr, slice=idx_expr, ctx=ast.Store())
            stmt = ast.Assign(targets=[target], value=value)
            set_location(stmt, form_loc)
            return stmt

    raise SyntaxError(
        f"set! target must be symbol, (. obj attr), or (nth coll idx): {target_form}"
    )
