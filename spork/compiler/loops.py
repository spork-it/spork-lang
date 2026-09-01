"""Lowering for eager iteration expressions, effect loops, and ``recur``."""

import ast
from typing import Optional, cast

from spork.compiler.ast_helpers import flatten_stmts, is_keyword
from spork.compiler.context import (
    LoopContext,
    get_compile_context,
    set_loop_context,
)
from spork.compiler.destructuring import compile_destructure
from spork.compiler.generated_names import gensym
from spork.compiler.lowering import compile_expr, compile_stmt
from spork.compiler.macros import is_symbol
from spork.compiler.reader import SourceLocation, get_source_location, set_location
from spork.runtime import Keyword, MapLiteral, Symbol, VectorLiteral
from spork.runtime.types import normalize_name


def _binding_names(pattern) -> set[str]:
    """Collect normalized names introduced by an iteration binding pattern."""
    if isinstance(pattern, Symbol):
        return {normalize_name(pattern.name)}
    if isinstance(pattern, VectorLiteral):
        names: set[str] = set()
        for item in pattern.items:
            if not (isinstance(item, Symbol) and item.name == "&"):
                names.update(_binding_names(item))
        return names
    if isinstance(pattern, MapLiteral):
        names = set()
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys":
                if isinstance(value, VectorLiteral):
                    for symbol in value.items:
                        if isinstance(symbol, Symbol):
                            names.add(normalize_name(symbol.name))
            elif isinstance(value, Symbol):
                names.add(normalize_name(value.name))
        return names
    return set()


def compile_loop(args, form_loc=None):
    """
    Compile (loop [bindings] body...) to a while True loop with recur support.

    This is the statement context version - the loop value is discarded.

    (loop [x 0 y 1]
      (if (< x 10)
        (recur (+ x 1) (* y 2))
        (print y)))

    Compiles to:
    x = 0
    y = 1
    while True:
        if x < 10:
            __x_new = x + 1
            __y_new = y * 2
            x = __x_new
            y = __y_new
            continue
        else:
            print(y)
            break
    """
    if len(args) < 1:
        raise SyntaxError("loop requires bindings vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("loop bindings must be a vector")
    body_forms = args[1:]

    items = bindings.items
    if len(items) % 2 != 0:
        raise SyntaxError("loop bindings must have even number of forms")

    # Parse bindings and create initialization statements
    init_stmts = []
    var_names = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        if not isinstance(pattern, Symbol):
            raise SyntaxError("loop bindings must be simple symbols (no destructuring)")
        var_name = normalize_name(pattern.name)
        var_names.append(var_name)
        value = compile_expr(value_form)
        assign = ast.Assign(
            targets=[ast.Name(id=var_name, ctx=ast.Store())], value=value
        )
        set_location(assign, get_source_location(pattern))
        init_stmts.append(assign)

    # Set up loop context for recur detection
    loop_ctx = LoopContext(var_names=var_names)
    prev_ctx = set_loop_context(loop_ctx)

    try:
        # Compile loop body with break for non-recur exits
        body_stmts = compile_loop_body(body_forms, var_names, mode="break")
    finally:
        set_loop_context(prev_ctx)

    # Build while True loop
    while_body: list[ast.stmt] = body_stmts if body_stmts else [ast.Pass()]
    while_node = ast.While(
        test=ast.Constant(value=True),
        body=while_body,
        orelse=[],
    )
    set_location(while_node, form_loc)

    return init_stmts + [while_node]


def compile_loop_stmt_with_return(args):
    """
    Compile (loop [bindings] body...) in tail position of a function.

    Non-recur exits use return instead of break.
    """
    if len(args) < 1:
        raise SyntaxError("loop requires bindings vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("loop bindings must be a vector")
    body_forms = args[1:]

    items = bindings.items
    if len(items) % 2 != 0:
        raise SyntaxError("loop bindings must have even number of forms")

    # Parse bindings and create initialization statements
    init_stmts = []
    var_names = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        if not isinstance(pattern, Symbol):
            raise SyntaxError("loop bindings must be simple symbols (no destructuring)")
        var_name = normalize_name(pattern.name)
        var_names.append(var_name)
        value = compile_expr(value_form)
        assign = ast.Assign(
            targets=[ast.Name(id=var_name, ctx=ast.Store())], value=value
        )
        set_location(assign, get_source_location(pattern))
        init_stmts.append(assign)

    # Set up loop context for recur detection
    loop_ctx = LoopContext(var_names=var_names)
    prev_ctx = set_loop_context(loop_ctx)

    try:
        # Compile loop body with return for non-recur exits
        body_stmts = compile_loop_body(body_forms, var_names, mode="return")
    finally:
        set_loop_context(prev_ctx)

    # Build while True loop
    while_body: list[ast.stmt] = body_stmts if body_stmts else [ast.Pass()]
    while_node = ast.While(
        test=ast.Constant(value=True),
        body=while_body,
        orelse=[],
    )

    result: list[ast.stmt] = init_stmts + [while_node]
    return result


def compile_loop_expr(args, form_loc=None):
    """
    Compile (loop [bindings] body...) in expression context.

    Uses a result variable to capture the loop's return value.
    """
    if len(args) < 1:
        raise SyntaxError("loop requires bindings vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("loop bindings must be a vector")
    body_forms = args[1:]

    items = bindings.items
    if len(items) % 2 != 0:
        raise SyntaxError("loop bindings must have even number of forms")

    # Preserve helpers that belong to an enclosing expression. Only helpers
    # created while lowering this loop may be moved into the loop wrapper.
    # Clearing the whole context here can strand an enclosing binding's helper
    # inside this function even though that helper is called outside it.
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)

    # Generate result variable name
    result_var = gensym("__loop_result_")

    # Initialize result variable to None
    result_init = ast.Assign(
        targets=[ast.Name(id=result_var, ctx=ast.Store())],
        value=ast.Constant(value=None),
    )

    # Parse bindings and create initialization statements
    init_stmts = [result_init]
    var_names = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        if not isinstance(pattern, Symbol):
            raise SyntaxError("loop bindings must be simple symbols (no destructuring)")
        var_name = normalize_name(pattern.name)
        var_names.append(var_name)
        value = compile_expr(value_form)
        assign = ast.Assign(
            targets=[ast.Name(id=var_name, ctx=ast.Store())], value=value
        )
        set_location(assign, get_source_location(pattern))
        init_stmts.append(assign)

    # Set up loop context for recur detection
    loop_ctx = LoopContext(var_names=var_names)
    prev_ctx = set_loop_context(loop_ctx)

    try:
        # Compile loop body with result variable assignment for non-recur exits
        body_stmts = compile_loop_body(
            body_forms, var_names, mode="result", result_var=result_var
        )
    finally:
        set_loop_context(prev_ctx)

    # Build while True loop
    while_body: list[ast.stmt] = body_stmts if body_stmts else [ast.Pass()]
    while_node = ast.While(
        test=ast.Constant(value=True),
        body=while_body,
        orelse=[],
    )
    set_location(while_node, form_loc)

    # Create the function that contains our loop and returns the result
    fn_name = gensym("__loop_fn_")

    # Inject only functions created by this loop after variable initialization
    # so they can reference loop variables. Helpers already pending in the
    # enclosing context must remain there, before the call sites that own them.
    nested_funcs = ctx.nested_functions[saved_funcs_count:]
    ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

    fn_body: list[ast.stmt] = []
    fn_body.extend(cast(list[ast.stmt], init_stmts))
    fn_body.extend(cast(list[ast.stmt], nested_funcs))
    fn_body.append(while_node)
    fn_body.append(ast.Return(value=ast.Name(id=result_var, ctx=ast.Load())))

    fn_def = ast.FunctionDef(
        name=fn_name,
        args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
        ),
        body=fn_body,
        decorator_list=[],
    )
    set_location(fn_def, form_loc)

    # Register this function to be injected at the appropriate scope
    get_compile_context().add_function(fn_def)

    # Return call to the function
    call = ast.Call(func=ast.Name(id=fn_name, ctx=ast.Load()), args=[], keywords=[])
    return set_location(call, form_loc)


def compile_loop_body(
    body_forms,
    var_names: list[str],
    mode: str = "break",
    result_var: Optional[str] = None,
) -> list[ast.stmt]:
    """
    Compile the body of a loop, handling recur in tail position.

    mode can be:
    - 'break': non-recur exits use break (statement context)
    - 'return': non-recur exits use return (function tail context)
    - 'result': non-recur exits assign to result_var and break (expression context)
    """
    if not body_forms:
        # Empty body - just break/return None
        if mode == "return":
            return [ast.Return(value=ast.Constant(value=None))]
        elif mode == "result" and result_var is not None:
            return [
                ast.Assign(
                    targets=[ast.Name(id=result_var, ctx=ast.Store())],
                    value=ast.Constant(value=None),
                ),
                ast.Break(),
            ]
        else:
            return [ast.Break()]

    stmts: list[ast.stmt] = []

    # Compile all but the last form as statements
    for f in body_forms[:-1]:
        s = compile_stmt(f)
        stmts.extend(flatten_stmts([s]))

    # Handle the last form specially for tail position
    last_form = body_forms[-1]
    tail_stmts = compile_loop_tail(last_form, var_names, mode, result_var)
    stmts.extend(tail_stmts)

    return stmts


def compile_loop_tail(
    form, var_names: list[str], mode: str, result_var: Optional[str] = None
) -> list[ast.stmt]:
    """
    Compile a form in tail position of a loop.

    Handles recur, if, let, do specially to find tail positions.
    """
    form_loc = get_source_location(form)

    # Check for recur
    if isinstance(form, list) and form and is_symbol(form[0], "recur"):
        return compile_recur(form[1:], var_names, form_loc)

    # Check for special forms that have their own tail positions
    if isinstance(form, list) and form and isinstance(form[0], Symbol):
        head_name = form[0].name

        if head_name == "if":
            return compile_loop_tail_if(form[1:], var_names, mode, result_var, form_loc)

        if head_name == "let":
            return compile_loop_tail_let(form[1:], var_names, mode, result_var)

        if head_name == "do":
            return compile_loop_tail_do(form[1:], var_names, mode, result_var)

        if head_name == "cond":
            return compile_loop_tail_cond(
                form[1:], var_names, mode, result_var, form_loc
            )

    # Not a special form - compile as expression and exit the loop
    expr = compile_expr(form)
    if mode == "return":
        ret = ast.Return(value=expr)
        set_location(ret, form_loc)
        return [ret]
    elif mode == "result" and result_var is not None:
        assign = ast.Assign(
            targets=[ast.Name(id=result_var, ctx=ast.Store())], value=expr
        )
        set_location(assign, form_loc)
        brk = ast.Break()
        set_location(brk, form_loc)
        return [assign, brk]
    else:  # mode == 'break'
        # Evaluate the expression (for side effects) then break
        expr_stmt = ast.Expr(value=expr)
        set_location(expr_stmt, form_loc)
        brk = ast.Break()
        set_location(brk, form_loc)
        return [expr_stmt, brk]


def compile_recur(
    args, var_names: list[str], form_loc: Optional[SourceLocation] = None
) -> list[ast.stmt]:
    """
    Compile (recur arg1 arg2 ...) to variable reassignment + continue.

    Uses temporary variables to handle cases like (recur y x) where
    we need to swap values.
    """
    if len(args) != len(var_names):
        raise SyntaxError(f"recur requires {len(var_names)} arguments, got {len(args)}")

    stmts: list[ast.stmt] = []

    # First, compute all new values into temporaries
    temp_names: list[str] = []
    for i, arg in enumerate(args):
        temp = gensym(f"__{var_names[i]}_new_")
        temp_names.append(temp)
        value = compile_expr(arg)
        assign = ast.Assign(targets=[ast.Name(id=temp, ctx=ast.Store())], value=value)
        set_location(assign, form_loc)
        stmts.append(assign)

    # Then assign temporaries to the actual loop variables
    for var_name, temp_name in zip(var_names, temp_names):
        assign = ast.Assign(
            targets=[ast.Name(id=var_name, ctx=ast.Store())],
            value=ast.Name(id=temp_name, ctx=ast.Load()),
        )
        set_location(assign, form_loc)
        stmts.append(assign)

    # Add continue to restart the loop
    cont = ast.Continue()
    set_location(cont, form_loc)
    stmts.append(cont)

    return stmts


def compile_loop_tail_if(
    args,
    var_names: list[str],
    mode: str,
    result_var: Optional[str],
    form_loc: Optional[SourceLocation] = None,
) -> list[ast.stmt]:
    """
    Compile (if test then else) in tail position of a loop.
    Both branches are compiled as loop tails.
    """
    if len(args) not in (2, 3):
        raise SyntaxError("if requires test, then, optional else")

    test_form = args[0]
    then_form = args[1]
    else_form = args[2] if len(args) == 3 else None

    test = compile_expr(test_form)
    then_stmts: list[ast.stmt] = compile_loop_tail(
        then_form, var_names, mode, result_var
    )
    else_stmts: list[ast.stmt]

    if else_form is not None:
        else_stmts = compile_loop_tail(else_form, var_names, mode, result_var)
    else:
        # No else branch - default to None exit
        if mode == "return":
            else_stmts = [ast.Return(value=ast.Constant(value=None))]
        elif mode == "result" and result_var is not None:
            else_stmts = [
                ast.Assign(
                    targets=[ast.Name(id=result_var, ctx=ast.Store())],
                    value=ast.Constant(value=None),
                ),
                ast.Break(),
            ]
        else:
            else_stmts = [ast.Break()]

    if_node = ast.If(test=test, body=then_stmts, orelse=else_stmts)
    set_location(if_node, form_loc)
    return [if_node]


def compile_loop_tail_let(
    args, var_names: list[str], mode: str, result_var: Optional[str]
) -> list[ast.stmt]:
    """
    Compile (let [bindings] body...) in tail position of a loop.
    The last body form is compiled as a loop tail.
    """
    if len(args) < 1:
        raise SyntaxError("let requires bindings vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("let bindings must be a vector")
    body_forms = args[1:]

    items = bindings.items
    if len(items) % 2 != 0:
        raise SyntaxError("let bindings must have even number of forms")

    stmts: list[ast.stmt] = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        value = compile_expr(value_form)
        stmts.extend(compile_destructure(pattern, value))

    if not body_forms:
        # Empty body - exit with None
        tail_stmts = compile_loop_tail(None, var_names, mode, result_var)
        stmts.extend(tail_stmts)
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            stmts.extend(flatten_stmts([s]))
        # Last form is a loop tail
        tail_stmts = compile_loop_tail(body_forms[-1], var_names, mode, result_var)
        stmts.extend(tail_stmts)

    return stmts


def compile_loop_tail_do(
    args, var_names: list[str], mode: str, result_var: Optional[str]
) -> list[ast.stmt]:
    """
    Compile (do body...) in tail position of a loop.
    The last body form is compiled as a loop tail.
    """
    if not args:
        # Empty do - exit with None
        return compile_loop_tail(None, var_names, mode, result_var)

    stmts: list[ast.stmt] = []
    # Compile all but last as statements
    for f in args[:-1]:
        s = compile_stmt(f)
        stmts.extend(flatten_stmts([s]))
    # Last form is a loop tail
    tail_stmts = compile_loop_tail(args[-1], var_names, mode, result_var)
    stmts.extend(tail_stmts)

    return stmts


def compile_loop_tail_cond(
    args,
    var_names: list[str],
    mode: str,
    result_var: Optional[str],
    form_loc: Optional[SourceLocation] = None,
) -> list[ast.stmt]:
    """
    Compile (cond test1 expr1 test2 expr2 ...) in tail position of a loop.
    Each expression is compiled as a loop tail.
    """
    if len(args) % 2 != 0:
        raise SyntaxError("cond requires even number of forms (test expr pairs)")

    if not args:
        # Empty cond - exit with None
        return compile_loop_tail(None, var_names, mode, result_var)

    # Build nested if statements from the end
    # Start with the default case (None if no :else)
    result: Optional[list[ast.stmt]] = None

    pairs = list(zip(args[::2], args[1::2]))
    for test_form, expr_form in reversed(pairs):
        # Check for :else keyword
        if isinstance(test_form, Keyword) and test_form.name == "else":
            # :else branch - just the expression
            result = compile_loop_tail(expr_form, var_names, mode, result_var)
        else:
            test = compile_expr(test_form)
            then_stmts: list[ast.stmt] = compile_loop_tail(
                expr_form, var_names, mode, result_var
            )
            else_stmts: list[ast.stmt]

            if result is None:
                # No else branch yet - default to None exit
                if mode == "return":
                    else_stmts = [ast.Return(value=ast.Constant(value=None))]
                elif mode == "result" and result_var is not None:
                    else_stmts = [
                        ast.Assign(
                            targets=[ast.Name(id=result_var, ctx=ast.Store())],
                            value=ast.Constant(value=None),
                        ),
                        ast.Break(),
                    ]
                else:
                    else_stmts = [ast.Break()]
            else:
                else_stmts = result

            if_node = ast.If(test=test, body=then_stmts, orelse=else_stmts)
            set_location(if_node, form_loc)
            result = [if_node]

    return result if result else compile_loop_tail(None, var_names, mode, result_var)


def compile_while(args, form_loc=None):
    """Compile (while test body...) to ast.While."""
    if len(args) < 1:
        raise SyntaxError("while requires test expression")
    test_form = args[0]
    body_forms = args[1:]

    test = compile_expr(test_form)
    body = []
    if not body_forms:
        body.append(ast.Pass())
    else:
        for f in body_forms:
            s = compile_stmt(f)
            body.extend(flatten_stmts([s]))

    node = ast.While(test=test, body=body, orelse=[])
    set_location(node, form_loc)
    return node


def compile_for(args, form_loc=None):
    """Compile a discarded ``for`` expression as an allocation-free loop.

    Statement context does not observe the vector produced by ``for``, so this
    lowering evaluates the same body forms without building that vector.  The
    ``doseq`` prelude form intentionally expands through this path.
    """
    if len(args) < 1:
        raise SyntaxError("for requires binding vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("for binding must be a vector")
    if len(bindings.items) != 2:
        raise SyntaxError("for binding must have exactly 2 elements [var seq]")

    var_form = bindings.items[0]
    seq_form = bindings.items[1]
    body_forms = args[1:]
    if not body_forms:
        raise SyntaxError("for requires a body expression")

    iter_expr = compile_expr(seq_form)

    # Check if we need destructuring
    if isinstance(var_form, Symbol):
        # Simple case: no destructuring needed
        target = ast.Name(id=normalize_name(var_form.name), ctx=ast.Store())

        body = []
        if not body_forms:
            body.append(ast.Pass())
        else:
            for f in body_forms:
                s = compile_stmt(f)
                body.extend(flatten_stmts([s]))

        node = ast.For(target=target, iter=iter_expr, body=body, orelse=[])
        set_location(node, form_loc)
        return node
    else:
        # Destructuring case: use a temp variable and destructure in body
        temp = gensym("__for_item_")
        target = ast.Name(id=temp, ctx=ast.Store())
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        body = []
        # First, add destructuring assignments
        body.extend(compile_destructure(var_form, temp_load))

        # Then add the actual body
        if not body_forms:
            pass  # Destructuring is enough, no need for Pass
        else:
            for f in body_forms:
                s = compile_stmt(f)
                body.extend(flatten_stmts([s]))

        # Ensure body is not empty
        if not body:
            body.append(ast.Pass())

        node = ast.For(target=target, iter=iter_expr, body=body, orelse=[])
        set_location(node, form_loc)
        return node


def compile_for_expr(args, form_loc=None):
    """Compile ``(for [x coll] body...)`` to an eager persistent vector.

    A transient vector keeps construction efficient, while the enclosing IIFE
    gives iteration bindings expression-local scope.  Earlier body forms are
    evaluated for effects and each iteration's final body value is retained.
    """
    if len(args) < 1:
        raise SyntaxError("for requires binding vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("for binding must be a vector")
    if len(bindings.items) != 2:
        raise SyntaxError("for binding must have exactly 2 elements [var seq]")

    body_forms = args[1:]
    if not body_forms:
        raise SyntaxError("for requires a body expression")

    var_form = bindings.items[0]
    coll_form = bindings.items[1]

    iter_expr = compile_expr(coll_form)

    # Generate unique names
    func_name = gensym("_for_expr_")
    transient_name = gensym("_t_")

    # Save the current nested functions state so we can capture any new ones
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)
    ctx.push_scope(_binding_names(var_form))
    ctx.push_nonlocal_frame()

    # Build the function body
    func_body = []

    # _t = EMPTY_VECTOR.transient()
    transient_init = ast.Assign(
        targets=[ast.Name(id=transient_name, ctx=ast.Store())],
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="EMPTY_VECTOR", ctx=ast.Load()),
                attr="transient",
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        ),
    )
    func_body.append(transient_init)

    # Build the for loop body
    loop_body = []

    # Handle destructuring if needed
    if isinstance(var_form, Symbol):
        # Simple case
        target = ast.Name(id=normalize_name(var_form.name), ctx=ast.Store())
    else:
        # Destructuring case
        item_temp = gensym("_item_")
        target = ast.Name(id=item_temp, ctx=ast.Store())
        item_load = ast.Name(id=item_temp, ctx=ast.Load())
        loop_body.extend(compile_destructure(var_form, item_load))

    # Evaluate all but the final body form for effects. The final value is
    # retained in the result vector for this iteration.
    for body_form in body_forms[:-1]:
        statement = compile_stmt(body_form)
        loop_body.extend(flatten_stmts([statement]))

    body_compiled = compile_expr(body_forms[-1])

    # Capture any nested functions that were generated during body compilation
    # These need to be defined INSIDE our function, not at module level
    nested_funcs = ctx.nested_functions[saved_funcs_count:]
    ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]
    nonlocals = ctx.pop_nonlocal_frame()
    ctx.pop_scope()

    # Python requires nonlocal declarations before assignments in the helper.
    if nonlocals:
        func_body.insert(0, ast.Nonlocal(names=sorted(nonlocals)))

    # Add captured nested functions at the start of our function body
    for nf in nested_funcs:
        func_body.append(nf)

    # _t.conj_mut(expr)
    conj_call = ast.Expr(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=transient_name, ctx=ast.Load()),
                attr="conj_mut",
                ctx=ast.Load(),
            ),
            args=[body_compiled],
            keywords=[],
        )
    )
    loop_body.append(conj_call)

    # for var in coll: ...
    for_loop = ast.For(target=target, iter=iter_expr, body=loop_body, orelse=[])
    func_body.append(for_loop)

    # return _t.persistent()
    return_stmt = ast.Return(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=transient_name, ctx=ast.Load()),
                attr="persistent",
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        )
    )
    func_body.append(return_stmt)

    # Build the IIFE function definition
    func_def = ast.FunctionDef(
        name=func_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=func_body,
        decorator_list=[],
        returns=None,
    )

    # Register the function to be added at module/function level
    ctx.add_function(func_def)

    # Return a call to the function
    call_expr = ast.Call(
        func=ast.Name(id=func_name, ctx=ast.Load()), args=[], keywords=[]
    )

    return set_location(call_expr, form_loc)


def compile_async_for_expr(args, form_loc=None):
    """Compile ``(async-for [x coll] body...)`` to an awaited eager vector."""
    if len(args) < 1:
        raise SyntaxError("async-for requires binding vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("async-for binding must be a vector")
    if len(bindings.items) != 2:
        raise SyntaxError(
            "async-for binding must have exactly 2 elements [var seq]"
        )

    body_forms = args[1:]
    if not body_forms:
        raise SyntaxError("async-for requires a body expression")

    var_form = bindings.items[0]
    coll_form = bindings.items[1]
    iter_expr = compile_expr(coll_form)

    func_name = gensym("_async_for_expr_")
    transient_name = gensym("_t_")

    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)
    ctx.push_scope(_binding_names(var_form))
    ctx.push_nonlocal_frame()

    func_body: list[ast.stmt] = [
        ast.Assign(
            targets=[ast.Name(id=transient_name, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="EMPTY_VECTOR", ctx=ast.Load()),
                    attr="transient",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            ),
        )
    ]
    loop_body: list[ast.stmt] = []

    if isinstance(var_form, Symbol):
        target = ast.Name(id=normalize_name(var_form.name), ctx=ast.Store())
    else:
        item_temp = gensym("_item_")
        target = ast.Name(id=item_temp, ctx=ast.Store())
        loop_body.extend(
            compile_destructure(
                var_form, ast.Name(id=item_temp, ctx=ast.Load())
            )
        )

    for body_form in body_forms[:-1]:
        statement = compile_stmt(body_form)
        loop_body.extend(flatten_stmts([statement]))

    body_compiled = compile_expr(body_forms[-1])
    loop_body.append(
        ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=transient_name, ctx=ast.Load()),
                    attr="conj_mut",
                    ctx=ast.Load(),
                ),
                args=[body_compiled],
                keywords=[],
            )
        )
    )

    nested_funcs = ctx.nested_functions[saved_funcs_count:]
    ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]
    nonlocals = ctx.pop_nonlocal_frame()
    ctx.pop_scope()

    if nonlocals:
        func_body.insert(0, ast.Nonlocal(names=sorted(nonlocals)))
    func_body.extend(nested_funcs)
    func_body.append(
        ast.AsyncFor(target=target, iter=iter_expr, body=loop_body, orelse=[])
    )
    func_body.append(
        ast.Return(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=transient_name, ctx=ast.Load()),
                    attr="persistent",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )
    )

    func_def = ast.AsyncFunctionDef(
        name=func_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=func_body,
        decorator_list=[],
        returns=None,
    )
    set_location(func_def, form_loc)
    ctx.add_function(func_def)

    call_expr = ast.Call(
        func=ast.Name(id=func_name, ctx=ast.Load()), args=[], keywords=[]
    )
    awaited = ast.Await(value=call_expr)
    return set_location(awaited, form_loc)


def compile_sorted_for_expr(args, form_loc=None):
    """
    Compile (sorted-for [x coll] expr :key key-fn :reverse bool) to a SortedVector.

    Generates an IIFE that builds a sorted vector:
        def _sorted_vec_comp():
            _t = EMPTY_SORTED_VECTOR.transient()  # or with key/reverse
            for x in coll:
                _t.conj_mut(expr)
            return _t.persistent()
        _sorted_vec_comp()

    Options:
        :key <fn>      - Key function for sorting
        :reverse <bool> - Whether to sort in reverse order
    """
    if len(args) < 1:
        raise SyntaxError("sorted-for requires binding vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("sorted-for binding must be a vector")
    if len(bindings.items) != 2:
        raise SyntaxError(
            "sorted-for binding must have exactly 2 elements [var seq]"
        )
    if len(args) < 2:
        raise SyntaxError("sorted-for requires a body expression")

    var_form = bindings.items[0]
    coll_form = bindings.items[1]
    body_expr = args[1]
    options = args[2:]

    iter_expr = compile_expr(coll_form)

    # Parse options (:key and :reverse)
    key_fn = None
    reverse_val = None
    i = 0
    while i < len(options):
        opt = options[i]
        if is_keyword(opt, "key") and i + 1 < len(options):
            key_fn = options[i + 1]
            i += 2
        elif is_keyword(opt, "reverse") and i + 1 < len(options):
            reverse_val = options[i + 1]
            i += 2
        else:
            raise SyntaxError(f"Unknown option in sorted-for: {opt}")

    # Generate unique names
    func_name = gensym("_sorted_vec_comp_")
    transient_name = gensym("_t_")

    # Save the current nested functions state so we can capture any new ones
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)
    ctx.push_scope(_binding_names(var_form))
    ctx.push_nonlocal_frame()

    # Build the function body
    func_body = []

    # Build the sorted_vec() call with options
    # If no options, use EMPTY_SORTED_VECTOR.transient()
    # If options, use sorted_vec(*{:key key_fn, :reverse reverse_val}).transient()
    if key_fn is None and reverse_val is None:
        # _t = EMPTY_SORTED_VECTOR.transient()
        transient_init = ast.Assign(
            targets=[ast.Name(id=transient_name, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="EMPTY_SORTED_VECTOR", ctx=ast.Load()),
                    attr="transient",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            ),
        )
    else:
        # _t = sorted_vec(*{:key ..., :reverse ...}).transient()
        sorted_vec_keywords = []
        if key_fn is not None:
            sorted_vec_keywords.append(
                ast.keyword(arg="key", value=compile_expr(key_fn))
            )
        if reverse_val is not None:
            sorted_vec_keywords.append(
                ast.keyword(arg="reverse", value=compile_expr(reverse_val))
            )
        transient_init = ast.Assign(
            targets=[ast.Name(id=transient_name, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Call(
                        func=ast.Name(id="sorted_vec", ctx=ast.Load()),
                        args=[],
                        keywords=sorted_vec_keywords,
                    ),
                    attr="transient",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            ),
        )
    func_body.append(transient_init)

    # Build the for loop body
    loop_body = []

    # Handle destructuring if needed
    if isinstance(var_form, Symbol):
        # Simple case
        target = ast.Name(id=normalize_name(var_form.name), ctx=ast.Store())
    else:
        # Destructuring case
        item_temp = gensym("_item_")
        target = ast.Name(id=item_temp, ctx=ast.Store())
        item_load = ast.Name(id=item_temp, ctx=ast.Load())
        loop_body.extend(compile_destructure(var_form, item_load))

    # Compile body expression INSIDE the loop context (after variable is bound)
    body_compiled = compile_expr(body_expr)

    # Capture any nested functions that were generated during body compilation
    nested_funcs = ctx.nested_functions[saved_funcs_count:]
    ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]
    nonlocals = ctx.pop_nonlocal_frame()
    ctx.pop_scope()

    if nonlocals:
        func_body.insert(0, ast.Nonlocal(names=sorted(nonlocals)))

    # Add captured nested functions at the start of our function body
    for nf in nested_funcs:
        func_body.append(nf)

    # _t.conj_mut(expr)
    conj_call = ast.Expr(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=transient_name, ctx=ast.Load()),
                attr="conj_mut",
                ctx=ast.Load(),
            ),
            args=[body_compiled],
            keywords=[],
        )
    )
    loop_body.append(conj_call)

    # for var in coll: ...
    for_loop = ast.For(target=target, iter=iter_expr, body=loop_body, orelse=[])
    func_body.append(for_loop)

    # return _t.persistent()
    return_stmt = ast.Return(
        value=ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=transient_name, ctx=ast.Load()),
                attr="persistent",
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        )
    )
    func_body.append(return_stmt)

    # Build the IIFE function definition
    func_def = ast.FunctionDef(
        name=func_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=func_body,
        decorator_list=[],
        returns=None,
    )

    # Register the function to be added at module/function level
    ctx.add_function(func_def)

    # Return a call to the function
    call_expr = ast.Call(
        func=ast.Name(id=func_name, ctx=ast.Load()), args=[], keywords=[]
    )

    return set_location(call_expr, form_loc)


def compile_async_for(args, form_loc=None):
    """Compile a discarded ``async-for`` expression without allocation."""
    if len(args) < 1:
        raise SyntaxError("async-for requires binding vector")
    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("async-for binding must be a vector")
    if len(bindings.items) != 2:
        raise SyntaxError("async-for binding must have exactly 2 elements [var seq]")

    var_form = bindings.items[0]
    seq_form = bindings.items[1]
    body_forms = args[1:]
    if not body_forms:
        raise SyntaxError("async-for requires a body expression")

    iter_expr = compile_expr(seq_form)
    body: list[ast.stmt] = []

    if isinstance(var_form, Symbol):
        target = ast.Name(id=normalize_name(var_form.name), ctx=ast.Store())
    else:
        temp = gensym("__async_for_item_")
        target = ast.Name(id=temp, ctx=ast.Store())
        body.extend(
            compile_destructure(var_form, ast.Name(id=temp, ctx=ast.Load()))
        )

    for body_form in body_forms:
        statement = compile_stmt(body_form)
        body.extend(flatten_stmts([statement]))

    node = ast.AsyncFor(target=target, iter=iter_expr, body=body, orelse=[])
    set_location(node, form_loc)
    return node
