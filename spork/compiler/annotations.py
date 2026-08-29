"""Compilation of Spork type annotations and function metadata."""

import ast

from spork.compiler.lowering import compile_expr
from spork.runtime import Decorated, Symbol, VectorLiteral
from spork.runtime.types import normalize_name

TYPE_ANNOTATION_FLAGS = {
    "async", "generator", "static", "classmethod",
    "staticmethod", "property",
}


def compile_type_annotation(type_expr):
    """
    Compile a type expression from Spork metadata to a Python AST node.

    Handles:
    - Simple types: int, str, float, bool, etc.
    - Qualified types: typing.List, typing.Optional
    - Generic types: (List int) -> List[int], (Dict str int) -> Dict[str, int]
    - Callable types: (Callable int int) and (Callable [[int] int])
    - Already-subscripted types: typing.List[int] (passed through)

    Args:
        type_expr: A Symbol, list (generic), or other expression representing a type

    Returns:
        ast.expr: An AST node suitable for use as an annotation
    """
    if isinstance(type_expr, Symbol):
        name = type_expr.name
        # Check for dotted name like typing.List
        if "." in name:
            # Split into parts and build attribute chain
            parts = name.split(".")
            # Start with the first part as a Name
            result = ast.Name(id=normalize_name(parts[0]), ctx=ast.Load())
            # Chain the rest as Attribute accesses
            for part in parts[1:]:
                result = ast.Attribute(
                    value=result,
                    attr=normalize_name(part),
                    ctx=ast.Load(),
                )
            return result
        else:
            # Simple type: int, str, MyClass, etc.
            return ast.Name(id=normalize_name(name), ctx=ast.Load())

    elif isinstance(type_expr, list) and len(type_expr) >= 1:
        # Generic type: (List int) -> List[int]
        # First element is the generic type, rest are type arguments
        base_type = type_expr[0]
        type_args = type_expr[1:]

        if not type_args:
            # Just (List) with no args - treat as simple type
            return compile_type_annotation(base_type)

        # Compile the base type
        base_node = compile_type_annotation(base_type)

        # Callable requires its parameter types to be a list in the generated
        # Python annotation: Callable[[arg, ...], result]. Spork accepts either
        # a compact form or the equivalent nested-vector form.
        base_name = (
            base_type.name.rsplit(".", 1)[-1]
            if isinstance(base_type, Symbol)
            else None
        )
        if base_name == "Callable":
            callable_parts = type_args
            if len(callable_parts) == 1 and isinstance(
                callable_parts[0], VectorLiteral
            ):
                callable_parts = callable_parts[0].items
            if len(callable_parts) < 2:
                raise SyntaxError(
                    "Callable type annotation requires parameter types and a return type"
                )

            result_type = callable_parts[-1]
            if len(callable_parts) == 2 and isinstance(
                callable_parts[0], VectorLiteral
            ):
                parameter_types = callable_parts[0].items
            else:
                parameter_types = callable_parts[:-1]

            if (
                len(parameter_types) == 1
                and isinstance(parameter_types[0], Symbol)
                and parameter_types[0].name == "..."
            ):
                parameters_node = ast.Constant(value=Ellipsis)
            else:
                parameters_node = ast.List(
                    elts=[compile_type_annotation(arg) for arg in parameter_types],
                    ctx=ast.Load(),
                )

            slice_node = ast.Tuple(
                elts=[parameters_node, compile_type_annotation(result_type)],
                ctx=ast.Load(),
            )
        elif len(type_args) == 1:
            # Single type arg: (List int) -> List[int]
            slice_node = compile_type_annotation(type_args[0])
        else:
            # Multiple type args: (Dict str int) -> Dict[str, int]
            # Create a tuple of type args
            slice_node = ast.Tuple(
                elts=[compile_type_annotation(arg) for arg in type_args],
                ctx=ast.Load(),
            )

        # Create subscript: List[int] or Dict[str, int]
        return ast.Subscript(
            value=base_node,
            slice=slice_node,
            ctx=ast.Load(),
        )

    else:
        # Fallback: compile as a regular expression
        # This handles things like typing.List[int] that are already subscripted
        return compile_expr(type_expr)


def is_type_annotation_flag(expr) -> bool:
    """
    Check if a Decorated expression is a compiler flag rather than a type annotation.

    Flags like ^async, ^generator, ^static are handled specially
    and should not be treated as type annotations.
    """
    if isinstance(expr, Symbol):
        return expr.name in TYPE_ANNOTATION_FLAGS
    return False


def extract_decorators_and_type(decorated_list):
    """
    Extract decorators, flags, and return type from a list of Decorated nodes.

    Args:
        decorated_list: List of Decorated nodes preceding a function/var name

    Returns:
        (decorators, is_async, is_generator, return_type)
        - decorators: List of decorator expressions (for @decorator syntax)
        - is_async: True if ^async was present
        - is_generator: True if ^generator was present
        - return_type: The type annotation expression, or None
    """
    decorators = []
    is_async = False
    is_generator = False
    return_type = None

    for dec in decorated_list:
        if not isinstance(dec, Decorated):
            continue

        dec_expr = dec.expr

        # Check for special flags
        if isinstance(dec_expr, Symbol):
            name = dec_expr.name
            if name == "async":
                is_async = True
                continue
            elif name == "generator":
                is_generator = True
                continue
            elif name in ("staticmethod", "classmethod", "property"):
                # These are Python decorators, not type annotations
                decorators.append(dec_expr)
                continue

        # Check if this looks like a type annotation
        # Type annotations are:
        # - Simple symbols that are NOT decorator functions (int, str, MyType)
        # - Generic type expressions like (List int)
        if isinstance(dec_expr, Symbol):
            # Heuristic: lowercase names are likely types (int, str, bool, float)
            # Capitalized names could be types or decorators
            # We'll treat non-flag symbols as type annotations
            if not is_type_annotation_flag(dec_expr):
                if return_type is None:
                    return_type = dec_expr
                else:
                    # Multiple type-like annotations - treat extras as decorators
                    decorators.append(dec_expr)
        elif isinstance(dec_expr, list):
            # Could be a generic type (List int) or a decorator call (route "/api")
            # If first element is a known type constructor, it's a type
            # Otherwise treat as decorator
            if dec_expr and isinstance(dec_expr[0], Symbol):
                first_name = dec_expr[0].name
                # Common generic type constructors (including qualified names)
                type_constructors = {
                    "list",
                    "dict",
                    "set",
                    "tuple",
                    "List",
                    "Dict",
                    "Set",
                    "Tuple",
                    "Optional",
                    "Union",
                    "Callable",
                    "Sequence",
                    "Mapping",
                    "Iterable",
                    "Iterator",
                    "Generator",
                    "Vector",
                    "Map",
                    "Cons",
                }
                # Also check if the base name (after last dot) is a type constructor
                base_name = (
                    first_name.split(".")[-1] if "." in first_name else first_name
                )
                if (
                    first_name in type_constructors
                    or base_name in type_constructors
                    or base_name[:1].isupper()
                ):
                    if return_type is None:
                        return_type = dec_expr
                    else:
                        decorators.append(dec_expr)
                else:
                    decorators.append(dec_expr)
            else:
                decorators.append(dec_expr)
        else:
            decorators.append(dec_expr)

    return decorators, is_async, is_generator, return_type
