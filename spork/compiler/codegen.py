"""Central dispatch for lowering Spork forms to Python AST."""

import ast

from spork.compiler.annotations import compile_type_annotation
from spork.compiler.ast_helpers import flatten_stmts
from spork.compiler.calls import (
    compile_apply,
    compile_call_args,
    compile_call_form,
    compile_dot_form,
    compile_method_call,
    compile_symbol_expr,
)
from spork.compiler.context import get_compile_context
from spork.compiler.control_flow import (
    compile_async_with,
    compile_async_with_expr,
    compile_do_expr,
    compile_if_expr,
    compile_if_stmt,
    compile_let_expr,
    compile_let_stmt,
    compile_with,
    compile_with_expr,
)
from spork.compiler.effects import (
    compile_await,
    compile_await_expr,
    compile_return,
    compile_set,
    compile_set_expr,
    compile_throw,
    compile_throw_expr,
    compile_yield,
    compile_yield_expr,
    compile_yield_from,
    compile_yield_from_expr,
)
from spork.compiler.exceptions import (
    compile_try,
    compile_try_expr,
    compile_try_stmt_with_return,
)
from spork.compiler.functions import (
    compile_def,
    compile_defclass,
    compile_defmacro,
    compile_defn,
    compile_fn_expr,
)
from spork.compiler.literals import (
    compile_anon_fn_literal,
    compile_fstring_literal,
    compile_inst_literal,
    compile_read_time_eval,
)
from spork.compiler.loops import (
    compile_async_for,
    compile_for,
    compile_loop,
    compile_loop_expr,
    compile_loop_stmt_with_return,
    compile_sorted_vector_comprehension,
    compile_vector_comprehension,
    compile_while,
)
from spork.compiler.lowering import install_lowerer
from spork.compiler.macros import is_symbol
from spork.compiler.namespaces import compile_ns
from spork.compiler.patterns import compile_match_expr
from spork.compiler.quoting import compile_quasiquote, compile_quote
from spork.compiler.reader import copy_location, get_source_location, set_location
from spork.compiler.reader_macros import (
    AnonFnLiteral,
    FStringLiteral,
    InstLiteral,
    PathLiteral,
    ReadTimeEval,
    RegexLiteral,
    SliceLiteral,
    UUIDLiteral,
)
from spork.runtime import (
    Cons,
    Decorated,
    Keyword,
    Map,
    MapLiteral,
    SetLiteral,
    Symbol,
    Vector,
    VectorLiteral,
)
from spork.runtime.types import normalize_name

BINARY_OPS = {
    "+": ast.Add(), "-": ast.Sub(), "*": ast.Mult(), "/": ast.Div(),
    "//": ast.FloorDiv(), "%": ast.Mod(), "**": ast.Pow(),
    "<<": ast.LShift(), ">>": ast.RShift(), "|": ast.BitOr(),
    "^": ast.BitXor(), "&": ast.BitAnd(),
}
COMPARE_OPS = {
    "=": ast.Eq(), "!=": ast.NotEq(), "not=": ast.NotEq(),
    "<": ast.Lt(), "<=": ast.LtE(), ">": ast.Gt(), ">=": ast.GtE(),
    "is": ast.Is(), "is-not": ast.IsNot(), "in": ast.In(),
    "not-in": ast.NotIn(),
}
BOOL_OPS = {"and": ast.And(), "or": ast.Or()}



def compile_module(forms, filename="<string>"):
    """
    Phase 3 & 4: Analyze and Lower
    Compile forms into a Python AST module.
    """
    # Reset per-module state without replacing the active context. Build and
    # namespace loaders use isolated contexts to carry the filename and target
    # mode safely across recursive macro loading.
    ctx = get_compile_context()
    ctx.nested_functions.clear()
    ctx.current_ns = None
    ctx.ns_aliases.clear()
    ctx.ns_refers.clear()
    ctx.require_stmts.clear()
    ctx.scope_stack.clear()
    ctx.nonlocal_stack.clear()
    ctx.test_names.clear()
    ctx.test_counter = 0

    body: list[ast.stmt] = []
    for form in forms:
        stmts = compile_toplevel(form)
        # Get any nested functions that were generated during this form's compilation
        nested = get_compile_context().get_and_clear_functions()
        # Add nested functions before the statements that reference them
        body.extend(nested)
        body.extend(flatten_stmts([stmts]))

    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)
    return mod


def compile_deftest(args, form_loc=None):
    """Compile a top-level ``deftest`` declaration.

    Test functions and descriptors are emitted during every compilation mode,
    but nothing invokes the function during normal module execution. The
    module-local registry is consumed only by the Spork test runner.
    """
    if not args:
        raise SyntaxError("deftest requires a name and body")

    decorated = []
    index = 0
    while index < len(args) and isinstance(args[index], Decorated):
        decorated.append(args[index])
        index += 1

    if decorated and (
        len(decorated) != 1
        or not isinstance(decorated[0].expr, Symbol)
        or decorated[0].expr.name != "async"
    ):
        raise SyntaxError("deftest only supports ^async metadata")

    if index >= len(args) or not isinstance(args[index], Symbol):
        raise SyntaxError("deftest name must be symbol")
    if index + 1 >= len(args):
        raise SyntaxError("deftest requires a body")

    name_sym = args[index]
    body_forms = args[index + 1 :]
    if len(body_forms) == 1 and isinstance(body_forms[0], str):
        raise SyntaxError("deftest requires a body after its docstring")
    normalized_name = normalize_name(name_sym.name)
    if not normalized_name.isidentifier():
        raise SyntaxError(f"invalid deftest name: {name_sym.name}")
    ctx = get_compile_context()

    if normalized_name in ctx.test_names:
        raise SyntaxError(f"duplicate deftest name: {name_sym.name}")
    ctx.test_names.add(normalized_name)
    ctx.test_counter += 1

    internal_name = f"__spork_test_{normalized_name}_{ctx.test_counter}"
    internal_sym = Symbol(
        internal_name,
        name_sym.line,
        name_sym.col,
        name_sym.end_line,
        name_sym.end_col,
    )
    params = VectorLiteral([], name_sym.line, name_sym.col)
    function = compile_defn(
        [*decorated, internal_sym, params, *body_forms], form_loc
    )

    filename = ctx.current_file or "<string>"
    line = form_loc.line if form_loc is not None else name_sym.line
    register = ast.Expr(
        value=ast.Call(
            func=ast.Name(id="__spork_register_test__", ctx=ast.Load()),
            args=[
                ast.Name(id="__spork_tests__", ctx=ast.Load()),
                ast.Constant(value=name_sym.name),
                ast.Name(id=internal_name, ctx=ast.Load()),
                ast.Constant(value=filename),
                ast.Constant(value=line),
                ast.Constant(value=ctx.current_ns),
            ],
            keywords=[],
        )
    )
    set_location(register, form_loc)
    return [function, register]


def compile_toplevel(form):
    """Compile a top-level form."""
    form_loc = get_source_location(form)
    if isinstance(form, list) and form:
        head = form[0]
        if is_symbol(head, "ns"):
            return compile_ns(form[1:], form_loc)
        if is_symbol(head, "import"):
            raise SyntaxError(
                "Standalone (import ...) is not allowed. "
                "Use (:import ...) inside (ns ...) instead."
            )
        if is_symbol(head, "def"):
            return compile_def(form[1:], form_loc)
        if is_symbol(head, "defn"):
            return compile_defn(form[1:], form_loc)
        if is_symbol(head, "deftest"):
            return compile_deftest(form[1:], form_loc)
        if is_symbol(head, "defclass"):
            return compile_defclass(form[1:], form_loc)
        if is_symbol(head, "defmacro"):
            return compile_defmacro(form[1:])
        if is_symbol(head, "for"):
            return compile_for(form[1:], form_loc)
        if is_symbol(head, "async-for"):
            return compile_async_for(form[1:], form_loc)
        if is_symbol(head, "while"):
            return compile_while(form[1:], form_loc)
        if is_symbol(head, "let"):
            return compile_let_stmt(form[1:], form_loc)
        if is_symbol(head, "with"):
            return compile_with(form[1:], form_loc)
        if is_symbol(head, "async-with"):
            return compile_async_with(form[1:], form_loc)
        if is_symbol(head, "set!"):
            return compile_set(form[1:], form_loc)
        if is_symbol(head, "do"):
            inner = form[1:]
            if not inner:
                node = ast.Pass()
                set_location(node, form_loc)
                return node
            stmts = []
            for f in inner:
                s = compile_stmt(f)
                stmts.extend(flatten_stmts([s]))
            return stmts
    # fallback: expression statement
    expr = compile_expr(form)
    node = ast.Expr(value=expr)
    set_location(node, form_loc)
    return node


def compile_stmt(form):
    """
    Compile a form in statement context.
    Returns a statement or list of statements.
    """
    form_loc = get_source_location(form)
    if isinstance(form, list) and form:
        head = form[0]
        if is_symbol(head, "if"):
            return compile_if_stmt(form[1:], form_loc)
        if is_symbol(head, "do"):
            # At statement level: (do s1 s2 s3) → emit multiple statements
            inner = form[1:]
            if not inner:
                node = ast.Pass()
                set_location(node, form_loc)
                return node
            stmts = []
            for f in inner:
                s = compile_stmt(f)
                stmts.extend(flatten_stmts([s]))
            return stmts
        if is_symbol(head, "def"):
            return compile_def(form[1:], form_loc)
        if is_symbol(head, "defn"):
            return compile_defn(form[1:], form_loc)
        if is_symbol(head, "deftest"):
            raise SyntaxError("deftest is only allowed at module top level")
        if is_symbol(head, "defclass"):
            return compile_defclass(form[1:], form_loc)
        if is_symbol(head, "let"):
            return compile_let_stmt(form[1:], form_loc)
        if is_symbol(head, "while"):
            return compile_while(form[1:], form_loc)
        if is_symbol(head, "for"):
            return compile_for(form[1:], form_loc)
        if is_symbol(head, "async-for"):
            return compile_async_for(form[1:], form_loc)
        if is_symbol(head, "await"):
            return compile_await(form[1:], form_loc)
        if is_symbol(head, "loop"):
            return compile_loop(form[1:], form_loc)
        if is_symbol(head, "with"):
            return compile_with(form[1:], form_loc)
        if is_symbol(head, "async-with"):
            return compile_async_with(form[1:], form_loc)
        if is_symbol(head, "yield"):
            return compile_yield(form[1:], form_loc)
        if is_symbol(head, "yield-from"):
            return compile_yield_from(form[1:], form_loc)
        if is_symbol(head, "try"):
            return compile_try(form[1:], form_loc)
        if is_symbol(head, "return"):
            return compile_return(form[1:], form_loc)
        if is_symbol(head, "throw"):
            return compile_throw(form[1:], form_loc)
        if is_symbol(head, "set!"):
            return compile_set(form[1:], form_loc)
        if is_symbol(head, "recur"):
            raise SyntaxError("recur can only be used in tail position within a loop")
    # Default: compile as an expression statement. Anonymous functions are
    # represented as nested definitions plus a name expression, so emit those
    # definitions immediately before the statement that first references them.
    ctx = get_compile_context()
    nested_start = len(ctx.nested_functions)
    node = ast.Expr(value=compile_expr(form))
    nested_funcs = ctx.nested_functions[nested_start:]
    ctx.nested_functions = ctx.nested_functions[:nested_start]
    set_location(node, form_loc)
    if nested_funcs:
        return [*nested_funcs, node]
    return node


def compile_expr(form):
    """
    Compile a form in expression context.
    Returns an ast.expr node with source location information when available.
    """
    # Get source location from form if available
    loc = get_source_location(form)

    # literals: booleans, nil, numbers, strings
    if isinstance(form, bool):
        # Must check bool before int since bool is subclass of int
        node = ast.Constant(value=form)
        return set_location(node, loc)
    if form is None:
        node = ast.Constant(value=None)
        return set_location(node, loc)
    if isinstance(form, (int, float, str)):
        node = ast.Constant(value=form)
        return set_location(node, loc)

    # Handle quote and quasiquote
    if isinstance(form, list) and len(form) > 0:
        head = form[0]

        # (quote form) - return the form as data
        if is_symbol(head, "quote"):
            if len(form) != 2:
                raise SyntaxError("quote requires exactly 1 argument")
            return compile_quote(form[1])

        # (quasiquote form) - like quote but with unquote/unquote-splicing
        if is_symbol(head, "quasiquote"):
            if len(form) != 2:
                raise SyntaxError("quasiquote requires exactly 1 argument")
            return compile_quasiquote(form[1])

    # MapLiteral -> Map via hash_map()
    if isinstance(form, MapLiteral):
        # Flatten key-value pairs into args for hash_map(k1, v1, k2, v2, ...)
        args = []
        for k, v in form.pairs:
            # Keywords are now preserved as Keyword objects
            keyexpr = compile_expr(k)
            args.append(keyexpr)
            args.append(compile_expr(v))
        node = ast.Call(
            func=ast.Name(id="hash_map", ctx=ast.Load()),
            args=args,
            keywords=[],
        )
        return copy_location(node, form)

    # SetLiteral -> PSet via hash_set()
    if isinstance(form, SetLiteral):
        # Create a list of elements and pass to hash_set
        elts = [compile_expr(x) for x in form.items]
        list_node = ast.List(elts=elts, ctx=ast.Load())
        node = ast.Call(
            func=ast.Name(id="hash_set", ctx=ast.Load()),
            args=[list_node],
            keywords=[],
        )
        return copy_location(node, form)

    # VectorLiteral -> Vector via vec()
    # Special case: [for [x coll] expr] -> vector comprehension using transients
    if isinstance(form, VectorLiteral):
        items = form.items
        if (
            len(items) == 3
            and is_symbol(items[0], "for")
            and isinstance(items[1], VectorLiteral)
        ):
            # Vector comprehension: [for [x coll] expr]
            # items[0] = 'for', items[1] = [x coll], items[2] = expr
            for_form = [items[0], items[1]]  # Reconstruct (for [x coll])
            body_expr = items[2]
            return compile_vector_comprehension(for_form, body_expr, form)

        # Check for sorted vector comprehension: [sorted-for [x coll] expr :key fn :reverse bool]
        if (
            len(items) >= 3
            and is_symbol(items[0], "sorted-for")
            and isinstance(items[1], VectorLiteral)
        ):
            # Sorted vector comprehension: [sorted-for [x coll] expr ...]
            # items[0] = 'sorted-for', items[1] = [x coll], items[2] = expr, items[3:] = options
            for_form = [items[0], items[1]]
            body_expr = items[2]
            options = items[3:]  # Remaining items are :key/:reverse options
            return compile_sorted_vector_comprehension(
                for_form, body_expr, options, form
            )

        elts = [compile_expr(x) for x in form.items]
        node = ast.Call(
            func=ast.Name(id="vec", ctx=ast.Load()),
            args=elts,
            keywords=[],
        )
        return copy_location(node, form)

    # Vector (runtime value from macro) -> vec() call
    if isinstance(form, Vector):
        elts = [compile_expr(form.nth(i)) for i in range(len(form))]  # type: ignore[attr-defined]
        node = ast.Call(
            func=ast.Name(id="vec", ctx=ast.Load()),
            args=elts,
            keywords=[],
        )
        return set_location(node, loc)

    # Map (runtime value from macro) -> hash_map() call
    if isinstance(form, Map):
        args = []
        for k, v in form.items():  # type: ignore[attr-defined]
            args.append(compile_expr(k))
            args.append(compile_expr(v))
        node = ast.Call(
            func=ast.Name(id="hash_map", ctx=ast.Load()),
            args=args,
            keywords=[],
        )
        return set_location(node, loc)

    # Cons (runtime value from macro) -> cons chain
    if isinstance(form, Cons):
        result = ast.Constant(value=None)
        # Collect items in a list first
        items = []
        curr = form
        while curr is not None:
            items.append(curr.first)  # type: ignore[attr-defined]
            curr = curr.rest  # type: ignore[attr-defined]
        # Build cons chain from right to left
        for item in reversed(items):
            result = ast.Call(
                func=ast.Name(id="cons", ctx=ast.Load()),
                args=[compile_expr(item), result],
                keywords=[],
            )
        return set_location(result, loc)

    # ==========================================================================
    # Reader Macro Literals
    # ==========================================================================

    # SliceLiteral -> slice(start, stop, step)
    if isinstance(form, SliceLiteral):
        start_expr = (
            ast.Constant(value=None) if form.start is None else compile_expr(form.start)
        )
        stop_expr = (
            ast.Constant(value=None) if form.stop is None else compile_expr(form.stop)
        )
        step_expr = (
            ast.Constant(value=None) if form.step is None else compile_expr(form.step)
        )
        node = ast.Call(
            func=ast.Name(id="slice", ctx=ast.Load()),
            args=[start_expr, stop_expr, step_expr],
            keywords=[],
        )
        return copy_location(node, form)

    # AnonFnLiteral -> hoisted function definition
    if isinstance(form, AnonFnLiteral):
        return compile_anon_fn_literal(form)

    # FStringLiteral -> ast.JoinedStr (f-string)
    if isinstance(form, FStringLiteral):
        return compile_fstring_literal(form)

    # PathLiteral -> pathlib.Path("...")
    if isinstance(form, PathLiteral):
        # Generate: pathlib.Path("path")
        node = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="pathlib", ctx=ast.Load()),
                attr="Path",
                ctx=ast.Load(),
            ),
            args=[ast.Constant(value=form.path)],
            keywords=[],
        )
        return copy_location(node, form)

    # RegexLiteral -> re.compile(r"...")
    if isinstance(form, RegexLiteral):
        # Generate: re.compile("pattern")
        node = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="re", ctx=ast.Load()),
                attr="compile",
                ctx=ast.Load(),
            ),
            args=[ast.Constant(value=form.pattern)],
            keywords=[],
        )
        return copy_location(node, form)

    # UUIDLiteral -> uuid.UUID("...")
    if isinstance(form, UUIDLiteral):
        # Generate: uuid.UUID("value")
        node = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="uuid", ctx=ast.Load()),
                attr="UUID",
                ctx=ast.Load(),
            ),
            args=[ast.Constant(value=form.value)],
            keywords=[],
        )
        return copy_location(node, form)

    # InstLiteral -> datetime.datetime(..., tzinfo=datetime.timezone.utc)
    if isinstance(form, InstLiteral):
        return compile_inst_literal(form)

    # ReadTimeEval -> evaluate at compile time and inject result
    if isinstance(form, ReadTimeEval):
        return compile_read_time_eval(form)

    # keyword - preserved as Keyword object at runtime
    if isinstance(form, Keyword):
        node = ast.Call(
            func=ast.Name(id="Keyword", ctx=ast.Load()),
            args=[ast.Constant(value=form.name)],
            keywords=[],
        )
        return copy_location(node, form)

    # symbol
    if isinstance(form, Symbol):
        return compile_symbol_expr(form)

    # list (special forms or function calls)
    if isinstance(form, list):
        if not form:
            return ast.Constant(value=None)
        head = form[0]

        if is_symbol(head, "deftest"):
            raise SyntaxError("deftest is only allowed at module top level")

        # (. base a b c)
        if is_symbol(head, "."):
            return compile_dot_form(form[1:])

        # expression if
        if is_symbol(head, "if"):
            return compile_if_expr(form[1:])

        # expression do
        if is_symbol(head, "do"):
            return compile_do_expr(form[1:])

        # expression let
        if is_symbol(head, "let"):
            return compile_let_expr(form[1:], loc)

        # fn literal
        if is_symbol(head, "fn"):
            return compile_fn_expr(form[1:])

        # call - method call syntax
        if is_symbol(head, "call"):
            return compile_call_form(form[1:])

        # (.method obj args...) - shorthand method call syntax
        if (
            isinstance(head, Symbol)
            and head.name.startswith(".")
            and len(head.name) > 1
        ):
            return compile_method_call(head.name[1:], form[1:])

        # try as expression: requires statement context
        if is_symbol(head, "try"):
            return compile_try_expr(form[1:])

        # with as expression: uses IIFE pattern
        if is_symbol(head, "with"):
            return compile_with_expr(form[1:])

        # async-with as expression: uses async IIFE pattern
        if is_symbol(head, "async-with"):
            return compile_async_with_expr(form[1:])

        # loop as expression: uses IIFE pattern
        if is_symbol(head, "loop"):
            return compile_loop_expr(form[1:], loc)

        # match expression: pattern matching
        if is_symbol(head, "match"):
            return compile_match_expr(form[1:], loc)

        # recur outside of loop context
        if is_symbol(head, "recur"):
            raise SyntaxError("recur can only be used in tail position within a loop")

        # set! as expression: returns the value being set
        if is_symbol(head, "set!"):
            return compile_set_expr(form[1:])

        # throw as expression: wrap in lambda that raises
        if is_symbol(head, "throw"):
            return compile_throw_expr(form[1:])

        # yield as expression
        if is_symbol(head, "yield"):
            return compile_yield_expr(form[1:])

        # yield-from as expression
        if is_symbol(head, "yield-from"):
            return compile_yield_from_expr(form[1:])

        # await as expression
        if is_symbol(head, "await"):
            return compile_await_expr(form[1:])

        # apply: (apply f args) or (apply f arg1 arg2 args-list)
        # Compiles to f(*args) or f(arg1, arg2, *args_list)
        if is_symbol(head, "apply"):
            return compile_apply(form[1:])

        # Binary operators: (+ a b), (- a b), etc.
        if isinstance(head, Symbol) and head.name in BINARY_OPS:
            if len(form) < 2:
                raise SyntaxError(
                    f"binary operator {head.name} requires at least 1 argument"
                )
            # Single argument: return as-is (useful for generic code)
            if len(form) == 2:
                return compile_expr(form[1])
            # Multiple arguments: chain left-to-right
            # (+ 1 2 3) => ((1 + 2) + 3)
            result = compile_expr(form[1])
            for arg in form[2:]:
                result = ast.BinOp(
                    left=result, op=BINARY_OPS[head.name], right=compile_expr(arg)
                )
                copy_location(result, form)
            return result

        # Comparison operators: (= a b), (< a b), etc.
        if isinstance(head, Symbol) and head.name in COMPARE_OPS:
            if len(form) < 3:
                raise SyntaxError(
                    f"comparison operator {head.name} requires at least 2 arguments"
                )
            # Python allows chained comparisons: a < b < c
            left = compile_expr(form[1])
            ops = []
            comparators = []
            for i in range(2, len(form)):
                ops.append(COMPARE_OPS[head.name])
                comparators.append(compile_expr(form[i]))
            node = ast.Compare(left=left, ops=ops, comparators=comparators)
            return copy_location(node, form)

        # Boolean operators: (and a b c), (or a b c)
        if isinstance(head, Symbol) and head.name in BOOL_OPS:
            if len(form) < 3:
                raise SyntaxError(
                    f"boolean operator {head.name} requires at least 2 arguments"
                )
            values = [compile_expr(f) for f in form[1:]]
            node = ast.BoolOp(op=BOOL_OPS[head.name], values=values)
            return copy_location(node, form)

        # Unary not: (not x)
        if is_symbol(head, "not"):
            if len(form) != 2:
                raise SyntaxError("not requires exactly 1 argument")
            node = ast.UnaryOp(op=ast.Not(), operand=compile_expr(form[1]))
            return copy_location(node, form)

        # function call
        fn = compile_expr(head)
        args, keywords = compile_call_args(form[1:])
        node = ast.Call(func=fn, args=args, keywords=keywords)
        return copy_location(node, form)

    raise TypeError(f"cannot compile form: {form!r}")

class _CodegenLowerer:
    """Delegate feature-module recursion back to the central dispatchers."""

    @staticmethod
    def compile_expr(form):
        return compile_expr(form)

    @staticmethod
    def compile_stmt(form):
        return compile_stmt(form)

    @staticmethod
    def compile_type_annotation(type_expr):
        return compile_type_annotation(type_expr)

    @staticmethod
    def compile_loop_stmt_with_return(args):
        return compile_loop_stmt_with_return(args)

    @staticmethod
    def compile_try_stmt_with_return(args):
        return compile_try_stmt_with_return(args)

    @staticmethod
    def compile_do_expr(forms):
        return compile_do_expr(forms)

    @staticmethod
    def compile_symbol_expr(symbol):
        return compile_symbol_expr(symbol)


install_lowerer(_CodegenLowerer())
