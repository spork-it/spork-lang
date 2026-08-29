"""Lowering for symbol access and Python call interop."""

import ast

from spork.compiler.lowering import compile_expr
from spork.compiler.macros import is_symbol
from spork.compiler.reader import copy_location
from spork.runtime import Keyword, KwargsLiteral, Symbol
from spork.runtime.types import normalize_name


def compile_symbol_expr(sym: Symbol):
    """Compile a symbol to a Name or Attribute access, with source location.

    Symbols containing dots are compiled to attribute chains:
        foo.bar.baz -> foo.bar.baz (Python attribute access)

    This handles:
        - Python module access: os.path.join
        - Object attributes: self.x
        - Namespace aliases: math.sqrt (where math is a required namespace)
    """
    name = sym.name
    parts = name.split(".")
    node: ast.expr = ast.Name(id=normalize_name(parts[0]), ctx=ast.Load())
    copy_location(node, sym)
    for attr in parts[1:]:
        node = ast.Attribute(value=node, attr=normalize_name(attr), ctx=ast.Load())
        copy_location(node, sym)
    return node


def compile_dot_form(args):
    """
    Compile (. base attrs...) for attribute access and subscripting.

    Syntax:
    - (. obj attr) → obj.attr (attribute access)
    - (. obj attr1 attr2) → obj.attr1.attr2 (chained attribute access)
    - (. obj 0) → obj[0] (subscript access)
    - (. obj (expr)) → obj[expr] (subscript with expression)

    For method calls, use the `call` special form instead.
    """
    if not args:
        raise SyntaxError("(. base attrs...) requires at least base and one attr")
    base_form = args[0]
    attrs = args[1:]

    if not attrs:
        raise SyntaxError("(. base) requires at least one attribute or subscript")

    base_expr = compile_expr(base_form)

    # Process each accessor in the chain
    node = base_expr
    for at in attrs:
        if isinstance(at, Symbol):
            # Attribute access: obj.attr
            node = ast.Attribute(
                value=node, attr=normalize_name(at.name), ctx=ast.Load()
            )
        elif isinstance(at, int):
            # Integer indexing: obj[0]
            node = ast.Subscript(
                value=node, slice=ast.Constant(value=at), ctx=ast.Load()
            )
        else:
            # General subscript: obj[expr]
            node = ast.Subscript(value=node, slice=compile_expr(at), ctx=ast.Load())

    return node


def compile_call_form(args):
    """
    Compile (call obj method arg1 arg2...) to method call.

    Syntax:
    - (call obj method arg1 arg2) → obj.method(arg1, arg2)

    The first argument is the object, second is the method name (symbol),
    and remaining arguments are passed to the method.
    """
    if len(args) < 2:
        raise SyntaxError("call requires at least object and method name")

    obj_form = args[0]
    method_form = args[1]
    call_args = args[2:]

    if not isinstance(method_form, Symbol):
        raise SyntaxError("method name must be a symbol")

    # Compile the object
    obj_expr = compile_expr(obj_form)

    # Access the method as an attribute
    method_expr = ast.Attribute(
        value=obj_expr, attr=normalize_name(method_form.name), ctx=ast.Load()
    )

    # Compile call arguments
    compiled_args, compiled_keywords = compile_call_args(call_args)

    # Create the method call
    return ast.Call(func=method_expr, args=compiled_args, keywords=compiled_keywords)


def compile_method_call(method_name, args):
    """
    Compile (.method obj arg1 arg2...) to method call.

    Syntax:
    - (.append list item) → list.append(item)
    - (.format string x y) → string.format(x, y)

    The first argument is the object, remaining arguments are passed to the method.
    """
    if not args:
        raise SyntaxError(f"(.{method_name} ...) requires at least an object argument")

    obj_form = args[0]
    call_args = args[1:]

    # Compile the object
    obj_expr = compile_expr(obj_form)

    # Access the method as an attribute (normalize hyphens to underscores)
    method_expr = ast.Attribute(
        value=obj_expr, attr=normalize_name(method_name), ctx=ast.Load()
    )

    # Compile call arguments
    compiled_args, compiled_keywords = compile_call_args(call_args)

    # Create the method call
    return ast.Call(func=method_expr, args=compiled_args, keywords=compiled_keywords)


def compile_apply(args):
    """
    Compile (apply f args) or (apply f arg1 arg2 ... args-seq).

    The last argument is spread as *args.

    Examples:
        (apply f xs)                  -> f(*xs)
        (apply f a b xs)              -> f(a, b, *xs)
        (apply f a *{:key v} xs)      -> f(a, *xs, key=v)
        (apply f a *{opts} xs)        -> f(a, *xs, **opts)
        (apply f a * :key v xs)       -> f(a, *xs, key=v)
    """
    if len(args) < 2:
        raise SyntaxError("apply requires at least function and args sequence")

    fn_form = args[0]
    call_args = args[1:]

    fn_expr = compile_expr(fn_form)

    # All but last are regular args, last is spread
    regular_args = call_args[:-1]
    spread_arg = call_args[-1]

    # Compile regular arguments (may include keyword args with *{:key value} syntax)
    compiled_args = []
    compiled_keywords = []
    i = 0
    in_kwargs_mode = False

    while i < len(regular_args):
        f = regular_args[i]

        # Check for * separator
        if is_symbol(f, "*"):
            in_kwargs_mode = True
            i += 1
            continue

        # Check for *{...} kwargs literal syntax
        if isinstance(f, KwargsLiteral):
            for key, val in f.pairs:
                if key is None:
                    # Splat variable: *{opts} -> **spork_kwargs_dict(opts)
                    # Wrap in spork_kwargs_dict to convert Keyword keys to strings
                    wrapped = ast.Call(
                        func=ast.Name(id="spork_kwargs_dict", ctx=ast.Load()),
                        args=[compile_expr(val)],
                        keywords=[],
                    )
                    compiled_keywords.append(ast.keyword(arg=None, value=wrapped))
                elif isinstance(key, Keyword):
                    key_name = normalize_name(key.name)
                    compiled_keywords.append(
                        ast.keyword(arg=key_name, value=compile_expr(val))
                    )
                elif isinstance(key, Symbol):
                    key_name = normalize_name(key.name)
                    compiled_keywords.append(
                        ast.keyword(arg=key_name, value=compile_expr(val))
                    )
                elif isinstance(key, str):
                    compiled_keywords.append(
                        ast.keyword(arg=key, value=compile_expr(val))
                    )
                else:
                    raise SyntaxError(
                        f"Kwargs keys must be keywords, symbols, or strings, got {type(key).__name__}"
                    )
            i += 1
            continue

        # In kwargs mode after *, expect :key value pairs
        if in_kwargs_mode:
            if isinstance(f, Keyword):
                if i + 1 >= len(regular_args):
                    raise SyntaxError(f"Keyword :{f.name} must be followed by a value")
                key_name = normalize_name(f.name)
                val = regular_args[i + 1]
                compiled_keywords.append(
                    ast.keyword(arg=key_name, value=compile_expr(val))
                )
                i += 2
                continue
            else:
                raise SyntaxError(
                    f"After * separator, expected :keyword or *{{...}}, got {type(f).__name__}"
                )

        # Regular positional argument
        compiled_args.append(compile_expr(f))
        i += 1

    # Add the spread argument as *args
    compiled_args.append(ast.Starred(value=compile_expr(spread_arg), ctx=ast.Load()))

    return ast.Call(func=fn_expr, args=compiled_args, keywords=compiled_keywords)


def compile_call_args(forms):
    """Compile function call arguments.

    Supports multiple syntaxes for keyword arguments:

    1. *{:key value} - inline keyword args in a map literal
    2. *{variable} - splat a map variable as **variable
    3. *{:key value variable} - mixed inline and splat
    4. * :key value - separator followed by bare keyword-value pairs

    Examples:
        (f 1 2 3)                         -> f(1, 2, 3)
        (f 1 *{:name "Alice"})            -> f(1, name="Alice")
        (f 1 *{opts})                     -> f(1, **opts)
        (f 1 *{:name "Alice" opts})       -> f(1, name="Alice", **opts)
        (f 1 * :name "Alice" :age 30)     -> f(1, name="Alice", age=30)
        (f 1 * :timeout 10 *{defaults})   -> f(1, timeout=10, **defaults)
    """
    args = []
    keywords = []
    i = 0
    in_kwargs_mode = False  # True after seeing * separator

    while i < len(forms):
        f = forms[i]

        # Check for * separator (bare symbol, not *{...})
        if is_symbol(f, "*"):
            in_kwargs_mode = True
            i += 1
            continue

        # Check for *{...} kwargs literal syntax
        if isinstance(f, KwargsLiteral):
            for key, val in f.pairs:
                if key is None:
                    # Splat variable: *{opts} -> **spork_kwargs_dict(opts)
                    # Wrap in spork_kwargs_dict to convert Keyword keys to strings
                    wrapped = ast.Call(
                        func=ast.Name(id="spork_kwargs_dict", ctx=ast.Load()),
                        args=[compile_expr(val)],
                        keywords=[],
                    )
                    keywords.append(ast.keyword(arg=None, value=wrapped))
                elif isinstance(key, Keyword):
                    key_name = normalize_name(key.name)
                    keywords.append(ast.keyword(arg=key_name, value=compile_expr(val)))
                elif isinstance(key, Symbol):
                    key_name = normalize_name(key.name)
                    keywords.append(ast.keyword(arg=key_name, value=compile_expr(val)))
                elif isinstance(key, str):
                    keywords.append(ast.keyword(arg=key, value=compile_expr(val)))
                else:
                    raise SyntaxError(
                        f"Kwargs keys must be keywords, symbols, or strings, got {type(key).__name__}"
                    )
            i += 1
            continue

        # In kwargs mode after *, expect :key value pairs
        if in_kwargs_mode:
            if isinstance(f, Keyword):
                # :key value pair
                if i + 1 >= len(forms):
                    raise SyntaxError(f"Keyword :{f.name} must be followed by a value")
                key_name = normalize_name(f.name)
                val = forms[i + 1]
                keywords.append(ast.keyword(arg=key_name, value=compile_expr(val)))
                i += 2
                continue
            else:
                raise SyntaxError(
                    f"After * separator, expected :keyword or *{{...}}, got {type(f).__name__}"
                )

        # Regular positional argument
        args.append(compile_expr(f))
        i += 1

    return args, keywords
