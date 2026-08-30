"""Lowering for conditionals, bindings, and context managers."""

import ast

from spork.compiler.ast_helpers import flatten_stmts
from spork.compiler.context import get_compile_context
from spork.compiler.destructuring import compile_destructure
from spork.compiler.generated_names import gen_fn_name, gensym
from spork.compiler.lowering import (
    compile_expr,
    compile_loop_stmt_with_return,
    compile_stmt,
    compile_try_stmt_with_return,
)
from spork.compiler.macros import is_symbol
from spork.compiler.reader import get_source_location, set_location
from spork.runtime import Keyword, MapLiteral, Symbol, VectorLiteral
from spork.runtime.types import normalize_name


def compile_if_stmt(args, form_loc=None):
    # (if test then else)
    if len(args) not in (2, 3):
        raise SyntaxError("if requires test, then, optional else")
    test_form = args[0]
    then_form = args[1]
    else_form = args[2] if len(args) == 3 else None
    test = compile_expr(test_form)
    body = flatten_stmts([compile_stmt(then_form)])
    orelse = flatten_stmts([compile_stmt(else_form)]) if else_form is not None else []
    # Ensure body is not empty
    if not body:
        body.append(ast.Pass())
    node = ast.If(test=test, body=body, orelse=orelse)
    set_location(node, form_loc)
    return node


def compile_if_expr(args):
    """
    Compile (if test then else) in expression context.

    Uses block-with-result pattern: wraps in IIFE with _spork_ret variable.
    This allows any form (including while/for) in branches.
    """
    if len(args) not in (2, 3):
        raise SyntaxError("if requires test, then, optional else")

    test_form = args[0]
    then_form = args[1]
    else_form = args[2] if len(args) == 3 else None

    ctx = get_compile_context()
    saved_funcs = ctx.nested_functions[:]

    test_expr = compile_expr(test_form)
    ret_name = "_spork_ret"

    # Compile branches as blocks with result
    then_block = compile_block_with_result([then_form], ret_name)
    else_block = compile_block_with_result(
        [else_form] if else_form is not None else [], ret_name
    )

    # Get any nested functions generated
    nested_funcs = ctx.nested_functions[len(saved_funcs) :]
    ctx.nested_functions = saved_funcs

    # Generate wrapper function
    wrapper_name = gen_fn_name()

    body = []
    body.extend(nested_funcs)

    # Initialize return variable to None
    body.append(
        ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )

    # Add if statement
    body.append(
        ast.If(
            test=test_expr,
            body=then_block if then_block else [ast.Pass()],
            orelse=else_block if else_block else [ast.Pass()],
        )
    )

    # Return the result
    body.append(ast.Return(value=ast.Name(id=ret_name, ctx=ast.Load())))

    # Create wrapper function
    wrapper_func = ast.FunctionDef(
        name=wrapper_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=body,
        decorator_list=[],
    )

    ctx.add_function(wrapper_func)

    return ast.Call(
        func=ast.Name(id=wrapper_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )


def compile_let_stmt(args, form_loc=None):
    """
    Compile (let [x 1 y 2] body...) in statement context.
    Emits sequential assignments followed by body statements.

    Supports destructuring patterns:
    - Vector patterns: [a b c] for sequence destructuring
    - Dict patterns: {:keys [x y]} or {:x a :y b} for map destructuring
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

    # Collect binding names for scope tracking
    def collect_binding_names(pattern):
        """Recursively collect all variable names from a binding pattern."""
        names = set()
        if isinstance(pattern, Symbol):
            names.add(normalize_name(pattern.name))
        elif isinstance(pattern, VectorLiteral):
            for item in pattern.items:
                if isinstance(item, Symbol) and item.name == "&":
                    continue  # Skip the & itself
                names.update(collect_binding_names(item))
        elif isinstance(pattern, MapLiteral):
            for k, v in pattern.pairs:
                if isinstance(k, Keyword) and k.name == "keys":
                    # {:keys [a b c]} form
                    if isinstance(v, VectorLiteral):
                        for sym in v.items:
                            if isinstance(sym, Symbol):
                                names.add(normalize_name(sym.name))
                elif isinstance(v, Symbol):
                    # {:key var} form - var is the binding
                    names.add(normalize_name(v.name))
        return names

    # Collect all binding names
    binding_names = set()
    for i in range(0, len(items), 2):
        pattern = items[i]
        binding_names.update(collect_binding_names(pattern))

    # Push scope with the binding names for nested do/let nonlocal tracking
    ctx = get_compile_context()
    ctx.push_scope(binding_names)

    stmts = []

    # Compile bindings and collect any nested function definitions
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        value = compile_expr(value_form)

        # Inject any nested function definitions before the assignment
        nested_funcs = get_compile_context().get_and_clear_functions()
        if nested_funcs:
            stmts.extend(nested_funcs)

        # Use destructuring for all patterns (handles both simple symbols and complex patterns)
        stmts.extend(compile_destructure(pattern, value, form_loc))

    if not body_forms:
        stmts.append(ast.Pass())
    else:
        for f in body_forms:
            s = compile_stmt(f)
            stmts.extend(flatten_stmts([s]))

    # Pop the scope we pushed
    ctx.pop_scope()

    return stmts


def compile_let_stmt_with_return(args):
    """
    Compile (let [x 1 y 2] body...) in tail position of function.
    Like compile_let_stmt but the last body form is returned.

    Supports destructuring patterns:
    - Vector patterns: [a b c] for sequence destructuring
    - Dict patterns: {:keys [x y]} or {:x a :y b} for map destructuring
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

    # Collect binding names for scope tracking
    def collect_binding_names(pattern):
        """Recursively collect all variable names from a binding pattern."""
        names = set()
        if isinstance(pattern, Symbol):
            names.add(normalize_name(pattern.name))
        elif isinstance(pattern, VectorLiteral):
            for item in pattern.items:
                if isinstance(item, Symbol) and item.name == "&":
                    continue  # Skip the & itself
                names.update(collect_binding_names(item))
        elif isinstance(pattern, MapLiteral):
            for k, v in pattern.pairs:
                if isinstance(k, Keyword) and k.name == "keys":
                    # {:keys [a b c]} form
                    if isinstance(v, VectorLiteral):
                        for sym in v.items:
                            if isinstance(sym, Symbol):
                                names.add(normalize_name(sym.name))
                elif isinstance(v, Symbol):
                    # {:key var} form - var is the binding
                    names.add(normalize_name(v.name))
        return names

    # Collect all binding names
    binding_names = set()
    for i in range(0, len(items), 2):
        pattern = items[i]
        binding_names.update(collect_binding_names(pattern))

    # Push scope with the binding names for nested do/let nonlocal tracking
    ctx = get_compile_context()
    ctx.push_scope(binding_names)

    stmts = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value_form = items[i + 1]
        value = compile_expr(value_form)

        # Inject any nested function definitions before the assignment
        nested_funcs = get_compile_context().get_and_clear_functions()
        if nested_funcs:
            stmts.extend(nested_funcs)

        # Use destructuring for all patterns (handles both simple symbols and complex patterns)
        stmts.extend(compile_destructure(pattern, value))

    if not body_forms:
        stmts.append(ast.Return(value=ast.Constant(value=None)))
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            stmts.extend(flatten_stmts([s]))

        # Last form: check if it's a statement or expression
        last_form = body_forms[-1]
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "try":
                # Try form - compile with return
                s = compile_try_stmt_with_return(last_form[1:])
                stmts.extend(flatten_stmts([s]))
            elif head_name == "with":
                # With form - compile with return
                s = compile_with_stmt_with_return(last_form[1:])
                stmts.append(s)
            elif head_name == "loop":
                # Loop form - compile with return
                s = compile_loop_stmt_with_return(last_form[1:])
                stmts.extend(flatten_stmts([s]))
            elif head_name in ("while", "set!"):
                # Statement form - compile as statement, return None
                s = compile_stmt(last_form)
                stmts.extend(flatten_stmts([s]))
                stmts.append(ast.Return(value=ast.Constant(value=None)))
            elif head_name == "return":
                # Already a return
                s = compile_stmt(last_form)
                stmts.extend(flatten_stmts([s]))
            else:
                # Expression - return it
                stmts.append(ast.Return(value=compile_expr(last_form)))
        else:
            # Simple expression - return it
            stmts.append(ast.Return(value=compile_expr(last_form)))

    # Pop the scope we pushed
    ctx.pop_scope()

    return stmts


def compile_do_stmt_with_return(args):
    """
    Compile (do s1 s2 s3) in tail position of function.
    All forms are statements except the last which is returned.
    """
    if not args:
        return ast.Return(value=ast.Constant(value=None))

    stmts = []
    # Compile all but last as statements
    for f in args[:-1]:
        s = compile_stmt(f)
        stmts.extend(flatten_stmts([s]))

    # Last form: check if it's a statement or expression
    last_form = args[-1]
    if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
        head_name = last_form[0].name
        if head_name == "try":
            # Try form - compile with return
            s = compile_try_stmt_with_return(last_form[1:])
            stmts.extend(flatten_stmts([s]))
        elif head_name == "with":
            # With form - compile with return
            s = compile_with_stmt_with_return(last_form[1:])
            stmts.append(s)
        elif head_name in ("while", "set!"):
            # Statement form - compile as statement, return None
            s = compile_stmt(last_form)
            stmts.extend(flatten_stmts([s]))
            stmts.append(ast.Return(value=ast.Constant(value=None)))
        elif head_name == "return":
            # Already a return
            s = compile_stmt(last_form)
            stmts.extend(flatten_stmts([s]))
        else:
            # Expression - return it
            stmts.append(ast.Return(value=compile_expr(last_form)))
    else:
        # Simple expression - return it
        stmts.append(ast.Return(value=compile_expr(last_form)))

    return stmts


def compile_let_expr(args, form_loc=None):
    """
    Compile (let [x 1 y 2] body...) in expression context.

    Uses block-with-result pattern: wraps in IIFE with _spork_ret variable.
    This allows any forms (including while/for/try) in let bodies.

    Supports destructuring patterns:
    - Vector patterns: [a b c] for sequence destructuring
    - Dict patterns: {:keys [x y]} or {:x a :y b} for map destructuring
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

    # Save current nested functions state
    ctx = get_compile_context()
    saved_funcs = ctx.nested_functions[:]

    # Collect binding names for scope tracking
    def collect_binding_names(pattern):
        """Recursively collect all variable names from a binding pattern."""
        names = set()
        if isinstance(pattern, Symbol):
            names.add(normalize_name(pattern.name))
        elif isinstance(pattern, VectorLiteral):
            for item in pattern.items:
                if isinstance(item, Symbol) and item.name == "&":
                    continue  # Skip the & itself
                names.update(collect_binding_names(item))
        elif isinstance(pattern, MapLiteral):
            for k, v in pattern.pairs:
                if isinstance(k, Keyword) and k.name == "keys":
                    # {:keys [a b c]} form
                    if isinstance(v, VectorLiteral):
                        for sym in v.items:
                            if isinstance(sym, Symbol):
                                names.add(normalize_name(sym.name))
                elif isinstance(v, Symbol):
                    # {:key var} form - var is the binding
                    names.add(normalize_name(v.name))
        return names

    # Collect all binding names
    binding_names = set()
    for i in range(0, len(items), 2):
        pattern = items[i]
        binding_names.update(collect_binding_names(pattern))

    # Push a new scope with the binding names, and a nonlocal frame
    ctx.push_scope(binding_names)
    ctx.push_nonlocal_frame()

    # Compile bindings - collect pattern/value pairs for destructuring
    bind_pairs = []
    for i in range(0, len(items), 2):
        pattern = items[i]
        value = compile_expr(items[i + 1])
        bind_pairs.append((pattern, value))

    # Compile body using block-with-result pattern
    ret_name = "_spork_ret"
    body_stmts = compile_block_with_result(body_forms, ret_name)

    # Get all nested functions that were generated
    nested_funcs = ctx.nested_functions[len(saved_funcs) :]
    ctx.nested_functions = saved_funcs  # Reset

    # Get nonlocal declarations needed and pop the frames
    nonlocals = ctx.pop_nonlocal_frame()
    ctx.pop_scope()

    # Generate wrapper function name
    wrapper_name = gen_fn_name()

    # Build wrapper function body
    stmts = []

    # Add nonlocal declarations first if needed
    if nonlocals:
        stmts.append(ast.Nonlocal(names=sorted(nonlocals)))

    # Add nested function definitions first
    stmts.extend(nested_funcs)

    # Add binding assignments using destructuring
    for pattern, value in bind_pairs:
        stmts.extend(compile_destructure(pattern, value))

    # Initialize return variable to None
    stmts.append(
        ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )

    # Add body statements
    stmts.extend(body_stmts)

    # Return the result
    stmts.append(ast.Return(value=ast.Name(id=ret_name, ctx=ast.Load())))

    # Create wrapper function
    wrapper_func = ast.FunctionDef(
        name=wrapper_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=stmts,
        decorator_list=[],
    )

    # Set source location on wrapper function
    if form_loc:
        set_location(wrapper_func, form_loc)

    # Add wrapper to context
    ctx.add_function(wrapper_func)

    # Return call to wrapper
    call_node = ast.Call(
        func=ast.Name(id=wrapper_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )
    if form_loc:
        set_location(call_node, form_loc)
    return call_node


def parse_with_bindings(items):
    """Parse with bindings from vector items.

    Returns list of (pattern_or_none, context_manager_expr_form) tuples.

    Supports:
    - [name expr] - bind cm to name
    - [name1 expr1 name2 expr2] - multiple bindings
    - [expr] - no binding (just evaluate context manager)
    - [[a b] expr] - destructuring binding
    """
    result = []
    i = 0
    while i < len(items):
        item = items[i]

        # Check if this is a binding pattern or a context manager expression
        # Binding patterns are: Symbol, Vector (for destructuring), MapLiteral (for dict destructuring)
        # Context manager expressions are: list (function call), or other expressions
        if isinstance(item, (Symbol, VectorLiteral, MapLiteral)):
            # This is a binding pattern, next item is the cm expression
            if i + 1 >= len(items):
                raise SyntaxError(
                    "with binding pattern must be followed by context manager expression"
                )
            pattern = item
            cm_form = items[i + 1]
            result.append((pattern, cm_form))
            i += 2
        else:
            # This is a context manager expression with no binding
            result.append((None, item))
            i += 1

    return result


def compile_with(args, form_loc=None):
    """
    Compile (with [bindings] body...) to ast.With.

    Supports:
    - Simple binding: (with [f (open "file.txt" "r")] ...)
    - Multiple bindings: (with [f1 (open "in.txt") f2 (open "out.txt")] ...)
    - No binding: (with [(open "file.txt")] ...)
    - Destructuring: (with [[a b] (some-context-manager)] ...)
    """
    if len(args) < 1:
        raise SyntaxError("with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Compile body
    body = []
    body.extend(destructure_stmts)

    if not body_forms:
        if not body:
            body.append(ast.Pass())
    else:
        for f in body_forms:
            s = compile_stmt(f)
            body.extend(flatten_stmts([s]))
        if not body:
            body.append(ast.Pass())

    node = ast.With(items=withitems, body=body)
    set_location(node, form_loc)
    return node


def compile_with_stmt_with_return(args):
    """
    Compile (with [bindings] body...) in tail position of function.
    Like compile_with but the last body form is returned.
    """
    if len(args) < 1:
        raise SyntaxError("with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Compile body with return for last form
    body = []
    body.extend(destructure_stmts)

    if not body_forms:
        body.append(ast.Return(value=ast.Constant(value=None)))
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            body.extend(flatten_stmts([s]))

        # Last form: check if it's a statement or expression
        last_form = body_forms[-1]
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "try":
                # Try form - compile with return
                s = compile_try_stmt_with_return(last_form[1:])
                body.extend(flatten_stmts([s]))
            elif head_name == "with":
                # Nested with - compile with return
                s = compile_with_stmt_with_return(last_form[1:])
                body.append(s)
            elif head_name == "async-with":
                # Nested async-with - compile with return
                s = compile_async_with_stmt_with_return(last_form[1:])
                body.append(s)
            elif head_name in ("while", "set!"):
                # Statement form - compile as statement, return None
                s = compile_stmt(last_form)
                body.extend(flatten_stmts([s]))
                body.append(ast.Return(value=ast.Constant(value=None)))
            elif head_name == "return":
                # Already a return
                s = compile_stmt(last_form)
                body.extend(flatten_stmts([s]))
            else:
                # Expression - return it
                body.append(ast.Return(value=compile_expr(last_form)))
        else:
            # Simple expression - return it
            body.append(ast.Return(value=compile_expr(last_form)))

    return ast.With(items=withitems, body=body)


def compile_with_expr(args):
    """
    Compile (with [bindings] body...) as an expression.
    Uses IIFE (immediately invoked function expression) pattern.
    """
    if len(args) < 1:
        raise SyntaxError("with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Build IIFE wrapper
    ctx = get_compile_context()
    saved_funcs = ctx.nested_functions[:]

    ret_name = gensym("__with_ret_")

    # Body of the with statement
    with_body = []
    with_body.extend(destructure_stmts)

    if not body_forms:
        with_body.append(
            ast.Assign(
                targets=[ast.Name(id=ret_name, ctx=ast.Store())],
                value=ast.Constant(value=None),
            )
        )
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            with_body.extend(flatten_stmts([s]))

        # Last form: assign to ret_name
        last_form = body_forms[-1]
        with_body.append(
            ast.Assign(
                targets=[ast.Name(id=ret_name, ctx=ast.Store())],
                value=compile_expr(last_form),
            )
        )

    # Create the with statement
    with_stmt = ast.With(items=withitems, body=with_body)

    # Get any nested functions generated
    nested_funcs = ctx.nested_functions[len(saved_funcs) :]
    ctx.nested_functions = saved_funcs

    # Generate wrapper function
    wrapper_name = gen_fn_name()

    wrapper_body = []
    wrapper_body.extend(nested_funcs)
    wrapper_body.append(
        ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )
    wrapper_body.append(with_stmt)
    wrapper_body.append(ast.Return(value=ast.Name(id=ret_name, ctx=ast.Load())))

    wrapper_def = ast.FunctionDef(
        name=wrapper_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=wrapper_body,
        decorator_list=[],
    )

    # Add wrapper to context for injection
    get_compile_context().add_function(wrapper_def)

    # Return call to wrapper
    return ast.Call(
        func=ast.Name(id=wrapper_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )


def compile_async_with(args, form_loc=None):
    """
    Compile (async-with [bindings] body...) to ast.AsyncWith.

    Supports:
    - Simple binding: (async-with [session (aiohttp.ClientSession)] ...)
    - Multiple bindings: (async-with [s1 (cm1) s2 (cm2)] ...)
    - No binding: (async-with [(some-async-cm)] ...)
    - Destructuring: (async-with [[a b] (some-async-context-manager)] ...)
    """
    if len(args) < 1:
        raise SyntaxError("async-with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("async-with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("async-with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__async_with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Compile body
    body = []
    body.extend(destructure_stmts)

    if not body_forms:
        if not body:
            body.append(ast.Pass())
    else:
        for f in body_forms:
            s = compile_stmt(f)
            body.extend(flatten_stmts([s]))
        if not body:
            body.append(ast.Pass())

    node = ast.AsyncWith(items=withitems, body=body)
    set_location(node, form_loc)
    return node


def compile_async_with_stmt_with_return(args):
    """
    Compile (async-with [bindings] body...) in tail position of function.
    Like compile_async_with but the last body form is returned.
    """
    if len(args) < 1:
        raise SyntaxError("async-with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("async-with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("async-with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__async_with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Compile body with return for last form
    body = []
    body.extend(destructure_stmts)

    if not body_forms:
        body.append(ast.Return(value=ast.Constant(value=None)))
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            body.extend(flatten_stmts([s]))

        # Last form: check if it's a statement or expression
        last_form = body_forms[-1]
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "try":
                # Try form - compile with return
                s = compile_try_stmt_with_return(last_form[1:])
                body.extend(flatten_stmts([s]))
            elif head_name == "with":
                # Nested with - compile with return
                s = compile_with_stmt_with_return(last_form[1:])
                body.append(s)
            elif head_name == "async-with":
                # Nested async-with - compile with return
                s = compile_async_with_stmt_with_return(last_form[1:])
                body.append(s)
            elif head_name in ("while", "set!"):
                # Statement form - compile as statement, return None
                s = compile_stmt(last_form)
                body.extend(flatten_stmts([s]))
                body.append(ast.Return(value=ast.Constant(value=None)))
            elif head_name == "return":
                # Already a return
                s = compile_stmt(last_form)
                body.extend(flatten_stmts([s]))
            else:
                # Expression - return it
                body.append(ast.Return(value=compile_expr(last_form)))
        else:
            # Simple expression - return it
            body.append(ast.Return(value=compile_expr(last_form)))

    return ast.AsyncWith(items=withitems, body=body)


def compile_async_with_expr(args):
    """
    Compile (async-with [bindings] body...) as an expression.
    Uses async IIFE (immediately invoked function expression) pattern.
    """
    if len(args) < 1:
        raise SyntaxError("async-with requires bindings vector")

    bindings = args[0]
    if not isinstance(bindings, VectorLiteral):
        raise SyntaxError("async-with bindings must be a vector")

    body_forms = args[1:]

    # Parse bindings
    parsed = parse_with_bindings(bindings.items)
    if not parsed:
        raise SyntaxError("async-with requires at least one context manager")

    # Build withitems
    withitems = []
    destructure_stmts = []

    for pattern, cm_form in parsed:
        cm_expr = compile_expr(cm_form)

        if pattern is None:
            # No binding
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=None))
        elif isinstance(pattern, Symbol):
            # Simple binding
            target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
        else:
            # Destructuring binding - use temp var and destructure in body
            temp = gensym("__async_with_item_")
            target = ast.Name(id=temp, ctx=ast.Store())
            withitems.append(ast.withitem(context_expr=cm_expr, optional_vars=target))
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(pattern, temp_load))

    # Build async IIFE wrapper
    ctx = get_compile_context()
    saved_funcs = ctx.nested_functions[:]

    ret_name = gensym("__async_with_ret_")

    # Body of the async with statement
    with_body = []
    with_body.extend(destructure_stmts)

    if not body_forms:
        with_body.append(
            ast.Assign(
                targets=[ast.Name(id=ret_name, ctx=ast.Store())],
                value=ast.Constant(value=None),
            )
        )
    else:
        # Compile all but last as statements
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            with_body.extend(flatten_stmts([s]))

        # Last form: assign to ret_name
        last_form = body_forms[-1]
        with_body.append(
            ast.Assign(
                targets=[ast.Name(id=ret_name, ctx=ast.Store())],
                value=compile_expr(last_form),
            )
        )

    # Create the async with statement
    with_stmt = ast.AsyncWith(items=withitems, body=with_body)

    # Get any nested functions generated
    nested_funcs = ctx.nested_functions[len(saved_funcs) :]
    ctx.nested_functions = saved_funcs

    # Generate async wrapper function
    wrapper_name = gen_fn_name()

    wrapper_body = []
    wrapper_body.extend(nested_funcs)
    wrapper_body.append(
        ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )
    wrapper_body.append(with_stmt)
    wrapper_body.append(ast.Return(value=ast.Name(id=ret_name, ctx=ast.Load())))

    wrapper_def = ast.AsyncFunctionDef(
        name=wrapper_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=wrapper_body,
        decorator_list=[],
    )

    # Add wrapper to context for injection
    get_compile_context().add_function(wrapper_def)

    # Return await of call to async wrapper
    return ast.Await(
        value=ast.Call(
            func=ast.Name(id=wrapper_name, ctx=ast.Load()),
            args=[],
            keywords=[],
        )
    )


def compile_block_with_result(forms, ret_name="_spork_ret"):
    """
    Compile a list of forms into statements that manage a return value.

    The block value is stored in ret_name:
    - If there are no forms, ret_name is left as-is (caller should init to None)
    - All but the last form are compiled as statements
    - The last form:
      - If it's a statement-only construct (while/set!/throw/return), compile as statement
      - Otherwise, compile as expression and assign to ret_name

    Returns a list of statement nodes.
    """
    stmts = []

    if not forms:
        # No forms: block value is None (caller should have initialized ret_name)
        return stmts

    # All but last: statement context
    for f in forms[:-1]:
        s = compile_stmt(f)
        stmts.extend(flatten_stmts([s]))

    last = forms[-1]

    # Check if last form is a statement-only construct
    is_stmt_only = False
    if isinstance(last, list) and last and is_symbol(last[0]):
        head = last[0].name
        if head in ("while", "set!", "throw", "return"):
            is_stmt_only = True

    if is_stmt_only:
        # Pure statement: compile it, don't touch ret_name
        s = compile_stmt(last)
        stmts.extend(flatten_stmts([s]))
        # ret_name keeps its current value (likely None)
    else:
        # Expression-producing form: assign its value to ret_name
        value_expr = compile_expr(last)
        assign_stmt = ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())], value=value_expr
        )
        # Preserve source location from the last form
        last_loc = get_source_location(last)
        set_location(assign_stmt, last_loc)
        stmts.append(assign_stmt)

    return stmts


def compile_do_expr(forms):
    """
    Compile (do e1 e2 e3) in expression context.

    Uses block-with-result pattern: wraps in IIFE with _spork_ret variable.
    This allows any forms (including while/for/try) in do blocks.
    """
    if not forms:
        return ast.Constant(value=None)

    # Check if single form is a statement-only construct that needs wrapping
    if len(forms) == 1:
        form = forms[0]
        # Check if it's a statement-only form (while, set!, etc.)
        is_statement_form = False
        if isinstance(form, list) and form and isinstance(form[0], Symbol):
            head_name = form[0].name
            if head_name in ("while", "set!"):
                is_statement_form = True

        if not is_statement_form:
            return compile_expr(form)
        # Fall through to wrapper function creation for statement forms

    ctx = get_compile_context()
    saved_funcs = ctx.nested_functions[:]

    # Push a new scope and nonlocal frame for this wrapper function
    ctx.push_scope()
    ctx.push_nonlocal_frame()

    ret_name = "_spork_ret"
    body_stmts = compile_block_with_result(forms, ret_name)

    # Get any nested functions generated
    nested_funcs = ctx.nested_functions[len(saved_funcs) :]
    ctx.nested_functions = saved_funcs

    # Get nonlocal declarations needed and pop the frame
    nonlocals = ctx.pop_nonlocal_frame()
    ctx.pop_scope()

    # Generate wrapper function
    wrapper_name = gen_fn_name()

    body = []

    # Add nonlocal declarations first if needed
    if nonlocals:
        body.append(ast.Nonlocal(names=sorted(nonlocals)))

    body.extend(nested_funcs)

    # Initialize return variable to None
    body.append(
        ast.Assign(
            targets=[ast.Name(id=ret_name, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )

    # Add body statements
    body.extend(body_stmts)

    # Return the result
    body.append(ast.Return(value=ast.Name(id=ret_name, ctx=ast.Load())))

    # Create wrapper function
    wrapper_func = ast.FunctionDef(
        name=wrapper_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=body,
        decorator_list=[],
    )

    ctx.add_function(wrapper_func)

    return ast.Call(
        func=ast.Name(id=wrapper_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )
