"""Lowering for try/catch/finally forms."""

import ast

from spork.compiler.ast_helpers import flatten_stmts
from spork.compiler.lowering import (
    compile_do_expr,
    compile_expr,
    compile_stmt,
    compile_symbol_expr,
)
from spork.compiler.macros import is_symbol
from spork.compiler.reader import set_location
from spork.runtime import Symbol
from spork.runtime.types import normalize_name


def compile_try_stmt_with_return(args):
    """
    Compile (try body... (catch ...) (finally ...)) in tail position of function.
    The last body form is returned.
    """
    if len(args) == 0:
        raise SyntaxError("try requires at least a body")

    body_forms = []
    catch_finally_forms = []

    i = 0
    while i < len(args):
        form = args[i]
        if isinstance(form, list) and len(form) > 0:
            head = form[0]
            if is_symbol(head, "catch") or is_symbol(head, "finally"):
                break
        body_forms.append(form)
        i += 1

    catch_finally_forms = args[i:]

    if not body_forms:
        raise SyntaxError("try requires at least one body form")

    # Separate body, catch clauses, and finally clause
    handlers = []
    finalbody = []

    for form in catch_finally_forms:
        if not isinstance(form, list) or len(form) < 1:
            raise SyntaxError("Expected catch or finally clause in try")

        head = form[0]

        if is_symbol(head, "catch"):
            if len(form) < 3:
                raise SyntaxError(
                    "catch requires exception type, variable name, and at least one handler form"
                )

            exc_type_form = form[1]
            var_form = form[2]
            handler_forms = form[3:]

            if exc_type_form is None:
                exc_type = None
            elif isinstance(exc_type_form, Symbol):
                exc_type = ast.Name(id=exc_type_form.name, ctx=ast.Load())
            else:
                raise SyntaxError("catch exception type must be a symbol or nil")

            if not isinstance(var_form, Symbol):
                raise SyntaxError("catch variable must be a symbol")
            var_name = normalize_name(var_form.name)

            # Compile handler body with last form as return
            if not handler_forms:
                handler_body: list[ast.stmt] = [
                    ast.Return(value=ast.Constant(value=None))
                ]
            else:
                handler_body = []
                for j, hf in enumerate(handler_forms):
                    if j == len(handler_forms) - 1:
                        # Last handler form: return it
                        if isinstance(hf, list) and hf and is_symbol(hf[0]):
                            h_name = hf[0].name
                            if h_name == "return":
                                s = compile_stmt(hf)
                                handler_body.extend(flatten_stmts([s]))
                            else:
                                handler_body.append(ast.Return(value=compile_expr(hf)))
                        else:
                            handler_body.append(ast.Return(value=compile_expr(hf)))
                    else:
                        s = compile_stmt(hf)
                        handler_body.extend(flatten_stmts([s]))

            handlers.append(
                ast.ExceptHandler(type=exc_type, name=var_name, body=handler_body)
            )

        elif is_symbol(head, "finally"):
            if len(form) < 2:
                raise SyntaxError("finally requires at least one form")

            if finalbody:
                raise SyntaxError("try can only have one finally clause")

            cleanup_forms = form[1:]
            for cf in cleanup_forms:
                s = compile_stmt(cf)
                finalbody.extend(flatten_stmts([s]))

        else:
            raise SyntaxError(f"Expected catch or finally, got {head}")

    # Compile body with last form as return
    body: list[ast.stmt] = []
    for j, bf in enumerate(body_forms):
        if j == len(body_forms) - 1:
            # Last body form: return it
            if isinstance(bf, list) and bf and is_symbol(bf[0]):
                b_name = bf[0].name
                if b_name == "return":
                    s = compile_stmt(bf)
                    body.extend(flatten_stmts([s]))
                else:
                    body.append(ast.Return(value=compile_expr(bf)))
            else:
                body.append(ast.Return(value=compile_expr(bf)))
        else:
            s = compile_stmt(bf)
            body.extend(flatten_stmts([s]))

    if not body:
        body = [ast.Return(value=ast.Constant(value=None))]

    return ast.Try(
        body=body,
        handlers=handlers,
        orelse=[],
        finalbody=finalbody,
    )


def compile_try(args, form_loc=None):
    """
    Compile (try body... (catch ExceptionType e handler...) (finally cleanup...))
    to ast.Try statement.

    Syntax:
      (try
        body...
        (catch ValueError e handler...)
        (catch Exception e handler...)
        (finally cleanup...))

    - Multiple catch clauses are allowed
    - finally clause is optional
    - Exception type can be a symbol (e.g., Exception) or nil for bare except
    - Variable name is required in catch clauses
    """
    if len(args) == 0:
        raise SyntaxError("try requires at least a body")

    # Separate body, catch clauses, and finally clause
    body_forms = []
    handlers = []
    finalbody = []

    i = 0
    # Parse body (everything before catch/finally)
    while i < len(args):
        form = args[i]
        if isinstance(form, list) and len(form) > 0:
            head = form[0]
            if is_symbol(head, "catch") or is_symbol(head, "finally"):
                break
        body_forms.append(form)
        i += 1

    # Parse catch and finally clauses
    while i < len(args):
        form = args[i]
        if not isinstance(form, list) or len(form) < 1:
            raise SyntaxError("Expected catch or finally clause in try")

        head = form[0]

        if is_symbol(head, "catch"):
            # (catch ExceptionType var handler...)
            if len(form) < 3:
                raise SyntaxError(
                    "catch requires exception type, variable name, and at least one handler form"
                )

            exc_type_form = form[1]
            var_form = form[2]
            handler_forms = form[3:]

            # Exception type: can be a symbol (Exception) or nil for bare except
            if exc_type_form is None:
                exc_type = None
            elif isinstance(exc_type_form, Symbol):
                exc_type = ast.Name(id=exc_type_form.name, ctx=ast.Load())
            else:
                raise SyntaxError("catch exception type must be a symbol or nil")

            # Variable name
            if not isinstance(var_form, Symbol):
                raise SyntaxError("catch variable must be a symbol")
            var_name = normalize_name(var_form.name)

            # Handler body
            handler_body: list[ast.stmt]
            if not handler_forms:
                handler_body = [ast.Pass()]
            else:
                handler_body = []
                for hf in handler_forms:
                    s = compile_stmt(hf)
                    handler_body.extend(flatten_stmts([s]))

            handlers.append(
                ast.ExceptHandler(type=exc_type, name=var_name, body=handler_body)
            )

        elif is_symbol(head, "finally"):
            # (finally cleanup...)
            if len(form) < 2:
                raise SyntaxError("finally requires at least one form")

            if finalbody:
                raise SyntaxError("try can only have one finally clause")

            cleanup_forms = form[1:]
            for cf in cleanup_forms:
                s = compile_stmt(cf)
                finalbody.extend(flatten_stmts([s]))

        else:
            raise SyntaxError(f"Expected catch or finally, got {head}")

        i += 1

    # Compile body
    compiled_body: list[ast.stmt]
    if not body_forms:
        compiled_body = [ast.Pass()]
    else:
        compiled_body = []
        for bf in body_forms:
            s = compile_stmt(bf)
            compiled_body.extend(flatten_stmts([s]))

    # Create Try node
    node = ast.Try(
        body=compiled_body,
        handlers=handlers,
        orelse=[],  # we don't support else clause for now
        finalbody=finalbody,
    )
    set_location(node, form_loc)
    return node


def compile_try_expr(args):
    """
    Compile (try body... (catch ...) (finally ...)) as an expression.
    Returns body value or handler value using spork_try helper.
    """
    if len(args) == 0:
        raise SyntaxError("try requires body")

    body_forms = []
    catch_finally_forms = []

    i = 0
    while i < len(args):
        form = args[i]
        if isinstance(form, list) and form:
            head = form[0]
            if is_symbol(head, "catch") or is_symbol(head, "finally"):
                break
        body_forms.append(form)
        i += 1

    catch_finally_forms = args[i:]

    if not body_forms:
        raise SyntaxError("try requires at least one body form")

    # Build body lambda: () -> value
    body_lambda = ast.Lambda(
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=compile_do_expr(body_forms),
    )

    # Build handlers list expression
    handler_elts = []
    finally_lambda = None

    for form in catch_finally_forms:
        if not isinstance(form, list) or not form:
            raise SyntaxError("Expected catch or finally in try")
        head = form[0]

        if is_symbol(head, "catch"):
            if len(form) < 3:
                raise SyntaxError("catch needs (ExceptionType var body...)")
            exc_type_form = form[1]
            var_form = form[2]
            handler_body_forms = form[3:] or [None]

            # Exception type
            if exc_type_form is None:
                exc_type_expr = ast.Constant(value=None)
            elif isinstance(exc_type_form, Symbol):
                exc_type_expr = compile_symbol_expr(exc_type_form)
            else:
                raise SyntaxError("catch exception type must be symbol or nil")

            if not isinstance(var_form, Symbol):
                raise SyntaxError("catch var must be symbol")
            var_name = normalize_name(var_form.name)

            # Compile handler body - for single form, compile directly
            if len(handler_body_forms) == 1:
                handler_body_expr = compile_expr(handler_body_forms[0])
            else:
                form_exprs = [compile_expr(f) for f in handler_body_forms]
                handler_body_expr = ast.Subscript(
                    value=ast.Tuple(elts=form_exprs, ctx=ast.Load()),
                    slice=ast.Constant(value=-1),
                    ctx=ast.Load(),
                )

            # Build handler lambda: (e) -> value
            handler_lambda = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg=var_name, annotation=None)],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=None,
                    defaults=[],
                ),
                body=handler_body_expr,
            )

            # Create tuple (exc_type, handler_lambda)
            handler_elts.append(
                ast.Tuple(elts=[exc_type_expr, handler_lambda], ctx=ast.Load())
            )

        elif is_symbol(head, "finally"):
            if finally_lambda is not None:
                raise SyntaxError("multiple finally clauses not allowed")
            cleanup_forms = form[1:] or [None]
            finally_lambda = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[],
                    args=[],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=None,
                    defaults=[],
                ),
                body=compile_do_expr(cleanup_forms),
            )
        else:
            raise SyntaxError("Expected catch or finally in try")

    handlers_list = ast.List(elts=handler_elts, ctx=ast.Load())

    args_exprs = [body_lambda, handlers_list]
    if finally_lambda is not None:
        args_exprs.append(finally_lambda)

    return ast.Call(
        func=ast.Name(id="spork_try", ctx=ast.Load()),
        args=args_exprs,
        keywords=[],
    )
