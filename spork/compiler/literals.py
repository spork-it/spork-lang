"""Lowering for reader-macro literal forms."""

import ast

from spork.compiler.ast_helpers import flatten_stmts
from spork.compiler.context import get_compile_context
from spork.compiler.control_flow import (
    compile_do_stmt_with_return,
    compile_let_stmt_with_return,
)
from spork.compiler.generated_names import gen_fn_name
from spork.compiler.lowering import compile_expr, compile_stmt
from spork.compiler.macros import is_symbol
from spork.compiler.reader import get_source_location, set_location
from spork.compiler.reader_macros import (
    AnonFnLiteral,
    FStringLiteral,
    InstLiteral,
    ReadTimeEval,
    extract_anon_fn_args,
    parse_inst,
    transform_anon_fn_args,
)


def compile_anon_fn_literal(form: AnonFnLiteral):
    """
    Compile #(...) anonymous function literal to a hoisted function definition.

    The function uses %, %1-%N, %& as argument placeholders which are
    transformed to actual parameter names.

    Example:
        #((print "processing" %) (+ % 1))
    Compiles to:
        def _anon_fn_N(_1):
            print("processing", _1)
            return _1 + 1
    """
    loc = get_source_location(form)
    body = form.body

    # Extract argument info from body
    max_arg, has_rest = extract_anon_fn_args(body)

    # Build parameter names and mapping
    arg_mapping = {}
    param_names = []

    # Always have at least 1 arg if % is used
    if max_arg > 0:
        for i in range(1, max_arg + 1):
            param_name = f"__{i}"
            param_names.append(param_name)
            if i == 1:
                arg_mapping["%"] = param_name
                arg_mapping["%1"] = param_name
            else:
                arg_mapping[f"%{i}"] = param_name

    # Handle rest args
    rest_param = None
    if has_rest:
        rest_param = "__rest"
        arg_mapping["%&"] = rest_param

    # Transform body to use actual param names
    transformed_body = [transform_anon_fn_args(f, arg_mapping) for f in body]

    # Generate function name
    fn_name = gen_fn_name()

    # Build Python AST args
    py_args = [ast.arg(arg=name, annotation=None) for name in param_names]

    if rest_param:
        args_node = ast.arguments(
            posonlyargs=[],
            args=py_args,
            vararg=ast.arg(arg=rest_param, annotation=None),
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
    else:
        args_node = ast.arguments(
            posonlyargs=[],
            args=py_args,
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )

    # Compile body
    body_nodes = []

    # Track nested functions
    before_count = len(get_compile_context().nested_functions)

    # Compile all but the last form as statements
    for f in transformed_body[:-1]:
        stmts = compile_stmt(f)
        body_nodes.extend(flatten_stmts([stmts]))

    # Last form: return it
    if transformed_body:
        last_form = transformed_body[-1]
        # Check if it's a statement-only form
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "let":
                let_stmts = compile_let_stmt_with_return(last_form[1:])
                body_nodes.extend(flatten_stmts([let_stmts]))
            elif head_name == "do":
                do_stmts = compile_do_stmt_with_return(last_form[1:])
                body_nodes.extend(flatten_stmts([do_stmts]))
            elif head_name in ("while", "set!"):
                stmts = compile_stmt(last_form)
                body_nodes.extend(flatten_stmts([stmts]))
                body_nodes.append(ast.Return(value=ast.Constant(value=None)))
            else:
                body_nodes.append(ast.Return(value=compile_expr(last_form)))
        else:
            body_nodes.append(ast.Return(value=compile_expr(last_form)))
    else:
        body_nodes.append(ast.Return(value=ast.Constant(value=None)))

    if not body_nodes:
        body_nodes.append(ast.Pass())

    # Inject nested functions
    ctx = get_compile_context()
    after_count = len(ctx.nested_functions)
    if after_count > before_count:
        nested_funcs = ctx.nested_functions[before_count:after_count]
        body_nodes = nested_funcs + body_nodes
        ctx.nested_functions = (
            ctx.nested_functions[:before_count] + ctx.nested_functions[after_count:]
        )

    # Create function definition
    func_def = ast.FunctionDef(
        name=fn_name,
        args=args_node,
        body=body_nodes,
        decorator_list=[],
    )
    # Set source location on function definition for proper tracebacks
    set_location(func_def, loc)

    # Add to context for hoisting
    get_compile_context().add_function(func_def)

    # Return reference to function with source location
    name_node = ast.Name(id=fn_name, ctx=ast.Load())
    return set_location(name_node, loc)


def compile_fstring_literal(form: FStringLiteral):
    """
    Compile #f"..." f-string literal to ast.JoinedStr.

    Example:
        #f"Hello {name}, 1+1 is {(+ 1 1)}"
    Compiles to:
        f"Hello {name}, 1+1 is {1 + 1}"
    """
    loc = get_source_location(form)
    values: list[ast.expr] = []

    for part in form.parts:
        if isinstance(part, str):
            # Text part
            values.append(ast.Constant(value=part))
        elif isinstance(part, tuple) and part[0] == "EXPR":
            # Expression part
            expr_form = part[1]
            expr_node = compile_expr(expr_form)
            # Wrap in FormattedValue
            values.append(
                ast.FormattedValue(
                    value=expr_node,
                    conversion=-1,  # No conversion
                    format_spec=None,
                )
            )

    node = ast.JoinedStr(values=values)
    return set_location(node, loc)


def compile_inst_literal(form: InstLiteral):
    """
    Compile #inst"..." ISO-8601 datetime literal.

    Example:
        #inst"2025-12-10T00:00:00Z"
    Compiles to:
        datetime.datetime(2025, 12, 10, 0, 0, 0, 0, tzinfo=datetime.timezone.utc)
    """
    loc = get_source_location(form)

    # Parse the datetime string
    year, month, day, hour, minute, second, microsecond, has_tz, tz_offset = parse_inst(
        form.value
    )

    args: list[ast.expr] = [
        ast.Constant(value=year),
        ast.Constant(value=month),
        ast.Constant(value=day),
        ast.Constant(value=hour),
        ast.Constant(value=minute),
        ast.Constant(value=second),
        ast.Constant(value=microsecond),
    ]

    keywords: list[ast.keyword] = []
    if has_tz:
        tz_expr: ast.expr
        if tz_offset == 0:
            # UTC timezone
            tz_expr = ast.Attribute(
                value=ast.Attribute(
                    value=ast.Name(id="datetime", ctx=ast.Load()),
                    attr="timezone",
                    ctx=ast.Load(),
                ),
                attr="utc",
                ctx=ast.Load(),
            )
        else:
            # Custom timezone offset
            tz_expr = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="datetime", ctx=ast.Load()),
                    attr="timezone",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="datetime", ctx=ast.Load()),
                            attr="timedelta",
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[
                            ast.keyword(
                                arg="minutes", value=ast.Constant(value=tz_offset)
                            )
                        ],
                    )
                ],
                keywords=[],
            )
        keywords.append(ast.keyword(arg="tzinfo", value=tz_expr))

    node = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="datetime", ctx=ast.Load()),
            attr="datetime",
            ctx=ast.Load(),
        ),
        args=args,
        keywords=keywords,
    )
    return set_location(node, loc)


def compile_read_time_eval(form: ReadTimeEval):
    """
    Compile #= form by evaluating at compile time and injecting result.

    Example:
        (def build-date #=(str (datetime.now)))
    The expression is evaluated during compilation and its result
    is injected as a constant into the AST.
    """
    from spork.compiler.macros import MACRO_EXEC_ENV

    loc = get_source_location(form)

    # Compile and evaluate the form
    expr_ast = compile_expr(form.form)

    # Wrap in expression module
    mod = ast.Expression(body=expr_ast)
    ast.fix_missing_locations(mod)

    # Compile to code object
    code = compile(mod, "<read-time-eval>", "eval")

    # Execute in macro environment (has access to imports etc)
    try:
        result = eval(code, MACRO_EXEC_ENV)
    except Exception as e:
        raise SyntaxError(
            f"Error evaluating #= expression at line {form.line}: {e}"
        ) from e

    # Convert result back to AST constant
    # For simple types, just use Constant
    if isinstance(result, (int, float, str, bool, type(None), bytes)):
        node = ast.Constant(value=result)
        return set_location(node, loc)

    # For other types, try to create appropriate construction
    # For now, just use repr and hope it's valid Python
    try:
        repr_str = repr(result)
        # Try to parse and compile the repr
        parsed = ast.parse(repr_str, mode="eval")
        return set_location(parsed.body, loc)
    except Exception:
        # Fall back to storing as constant (may not work for all types)
        node = ast.Constant(value=result)
        return set_location(node, loc)
