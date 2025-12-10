"""
spork.compiler.codegen - Code generation (Spork Forms -> Python AST)

This module handles Phase 3-4 of compilation: transforming Spork forms
into Python AST nodes that can be compiled and executed.
"""

import ast
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional, cast

from spork.compiler.macros import (
    MACRO_ENV,
    is_symbol,
    macroexpand_all,
    process_import_macros,
)
from spork.compiler.macros import (
    process_defmacros as _process_defmacros_base,
)

# Import from compiler modules
from spork.compiler.reader import (
    SourceLocation,
    copy_location,
    get_source_location,
    read_str,
    set_location,
)

# Import from runtime
from spork.runtime import (
    Cons,
    Decorated,
    Keyword,
    KwargsLiteral,
    Map,
    MapLiteral,
    SetLiteral,
    Symbol,
    Vector,
    VectorLiteral,
    setup_runtime_env,
)
from spork.runtime.types import normalize_name

# === Compilation context ===

# Global counter for generating unique function names
_fn_counter = 0


def gen_fn_name():
    """Generate a unique name for an anonymous function."""
    global _fn_counter
    _fn_counter += 1
    return f"_spork_fn_{_fn_counter}"


# Global counter for generating unique symbol names
_gensym_counter = 0


def gensym(prefix="__spork_"):
    """Generate a unique symbol name for temporary variables."""
    global _gensym_counter
    _gensym_counter += 1
    return f"{prefix}{_gensym_counter}"


# === Type Annotation Compilation ===

# Special decorator names that are flags, not type annotations
TYPE_ANNOTATION_FLAGS = {"async", "generator", "static", "classmethod", "staticmethod"}


def compile_type_annotation(type_expr):
    """
    Compile a type expression from Spork metadata to a Python AST node.

    Handles:
    - Simple types: int, str, float, bool, etc.
    - Qualified types: typing.List, typing.Optional
    - Generic types: (List int) -> List[int], (Dict str int) -> Dict[str, int]
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

        # Compile type arguments
        if len(type_args) == 1:
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
            elif name in ("staticmethod", "classmethod"):
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
                if first_name in type_constructors or base_name in type_constructors:
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


@dataclass
class CompilationContext:
    """Context for tracking nested function definitions and namespace during compilation."""

    def __init__(self):
        self.nested_functions: list[ast.FunctionDef] = []
        self.current_ns: Optional[str] = None  # Current namespace name
        self.current_file: Optional[str] = None  # Current file being compiled
        self.ns_aliases: dict[str, str] = {}  # alias -> full namespace name
        self.ns_refers: dict[str, str] = {}  # symbol -> source namespace
        self.require_stmts: list[ast.stmt] = []  # Import statements from :require
        self.scope_stack: list[set] = []
        self.nonlocal_stack: list[set] = []

    def add_function(self, func_def):
        """Add a nested function definition to be injected later."""
        self.nested_functions.append(func_def)

    def get_and_clear_functions(self):
        """Get all nested functions and clear the list."""
        funcs = self.nested_functions[:]
        self.nested_functions.clear()
        return funcs

    def add_require_stmt(self, stmt):
        """Add an import statement from :require processing."""
        self.require_stmts.append(stmt)

    def get_and_clear_require_stmts(self):
        """Get all require statements and clear the list."""
        stmts = self.require_stmts[:]
        self.require_stmts.clear()
        return stmts

    def push_scope(self, variables: Optional[set] = None):
        """Push a new scope level with optional initial variables."""
        self.scope_stack.append(variables if variables else set())

    def pop_scope(self):
        """Pop the current scope level."""
        if self.scope_stack:
            self.scope_stack.pop()

    def add_to_scope(self, name: str):
        """Add a variable to the current scope."""
        if self.scope_stack:
            self.scope_stack[-1].add(name)

    def is_in_current_scope(self, name: str) -> bool:
        """Check if a variable is defined in the current (innermost) scope."""
        if self.scope_stack:
            return name in self.scope_stack[-1]
        return False

    def is_in_any_scope(self, name: str) -> bool:
        """Check if a variable is defined in any enclosing scope."""
        for scope in self.scope_stack:
            if name in scope:
                return True
        return False

    def push_nonlocal_frame(self):
        """Push a new nonlocal tracking frame for a wrapper function."""
        self.nonlocal_stack.append(set())

    def pop_nonlocal_frame(self) -> set:
        """Pop and return the current nonlocal frame."""
        if self.nonlocal_stack:
            return self.nonlocal_stack.pop()
        return set()

    def mark_nonlocal(self, name: str):
        """Mark a variable as needing nonlocal declaration."""
        if self.nonlocal_stack:
            self.nonlocal_stack[-1].add(name)

    def get_nonlocals(self) -> set:
        """Get the current set of variables needing nonlocal declarations."""
        if self.nonlocal_stack:
            return self.nonlocal_stack[-1]
        return set()


@dataclass
class LoopContext:
    """Context for tracking loop variables during loop/recur compilation."""

    var_names: list[str]  # The normalized variable names for the loop bindings


# Thread-safe loop context using contextvars
_loop_context_var: ContextVar[Optional[LoopContext]] = ContextVar(
    "_loop_context", default=None
)


def get_loop_context() -> Optional[LoopContext]:
    """Get the current loop context, or None if not in a loop."""
    return _loop_context_var.get()


def set_loop_context(ctx: Optional[LoopContext]) -> Optional[LoopContext]:
    """Set the loop context and return the previous one."""
    prev = _loop_context_var.get()
    _loop_context_var.set(ctx)
    return prev


# Thread-safe compilation context using contextvars
_compile_context_var: ContextVar[Optional[CompilationContext]] = ContextVar(
    "_compile_context", default=None
)


def get_compile_context() -> CompilationContext:
    """Get the current compilation context, creating one if needed."""
    ctx = _compile_context_var.get()
    if ctx is None:
        ctx = CompilationContext()
        _compile_context_var.set(ctx)
    return ctx


def is_keyword(x, name=None):
    if isinstance(x, Keyword):
        if name is None:
            return True
        return x.name == name
    return False


def flatten_stmts(stmts):
    """Flatten a list that may contain nested lists of statements."""
    result = []
    for s in stmts:
        if isinstance(s, list):
            result.extend(flatten_stmts(s))
        elif s is not None:
            result.append(s)
    return result


def contains_yield(nodes):
    """
    Check if any of the given AST nodes (or their children) contain
    ast.Yield or ast.YieldFrom. This is used to detect generator functions
    and avoid adding implicit return statements.
    """
    if not isinstance(nodes, list):
        nodes = [nodes]

    for node in nodes:
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        # Walk all child nodes
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                return True
    return False


# === Operator mappings ===

BINARY_OPS = {
    "+": ast.Add(),
    "-": ast.Sub(),
    "*": ast.Mult(),
    "/": ast.Div(),
    "//": ast.FloorDiv(),
    "%": ast.Mod(),
    "**": ast.Pow(),
    "<<": ast.LShift(),
    ">>": ast.RShift(),
    "|": ast.BitOr(),
    "^": ast.BitXor(),
    "&": ast.BitAnd(),
}

COMPARE_OPS = {
    "=": ast.Eq(),
    "!=": ast.NotEq(),
    "not=": ast.NotEq(),
    "<": ast.Lt(),
    "<=": ast.LtE(),
    ">": ast.Gt(),
    ">=": ast.GtE(),
    "is": ast.Is(),
    "is-not": ast.IsNot(),
    "in": ast.In(),
    "not-in": ast.NotIn(),
}

BOOL_OPS = {
    "and": ast.And(),
    "or": ast.Or(),
}


# === Quote and Quasiquote ===


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


# Global counter for auto-gensym in quasiquotes
_auto_gensym_counter = 0


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


# === Analysis & Lowering ===


def compile_module(forms, filename="<string>"):
    """
    Phase 3 & 4: Analyze and Lower
    Compile forms into a Python AST module.
    """
    # Reset the compilation context for this compilation
    _compile_context_var.set(CompilationContext())

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


def compile_ns(args, form_loc=None):
    """
    Compile (ns name (:require ...) (:import ...)) form.

    Sets up namespace context and generates import statements.

    Syntax:
        (ns my.app.core)
        (ns my.app.core
          (:require
            [spork.pds :as pds]
            [my.lib.helpers :as helpers :refer [foo bar]]
            [math :as m]
            [logging :refer [getLogger]])
          (:import
            [numpy :as np]
            [os.path :as osp]
            [collections [defaultdict Counter]]
            [math :refer [sin cos]]))

    :require - For Spork namespaces (loads macros) and Python modules
    :import  - For Python modules only (no macro loading, just runtime imports)
    """
    from spork.runtime.ns import (
        get_namespace,
        parse_require_spec,
        resolve_require,
    )

    if not args:
        raise SyntaxError("ns form requires a namespace name")

    # First arg is the namespace name
    ns_name_form = args[0]
    if not isinstance(ns_name_form, Symbol):
        raise SyntaxError("ns name must be a symbol")

    ns_name = ns_name_form.name
    ctx = get_compile_context()
    ctx.current_ns = ns_name

    stmts: list[ast.stmt] = []

    # Process remaining args (should be :require, :import, etc. clauses)
    for clause in args[1:]:
        if not isinstance(clause, list) or len(clause) == 0:
            raise SyntaxError(f"Invalid ns clause: {clause}")

        clause_head = clause[0]

        if isinstance(clause_head, Keyword) and clause_head.name == "require":
            # Process each require spec
            for spec in clause[1:]:
                req_info = parse_require_spec(spec)
                req_ns = req_info["ns"]
                alias = req_info["alias"]
                refer = req_info["refer"]

                try:
                    resolve_type, spork_path = resolve_require(req_ns, ctx.current_file)
                except FileNotFoundError as e:
                    raise SyntaxError(str(e)) from e

                if resolve_type == "spork":
                    # Spork namespace - need to load it
                    # Check if already loaded
                    ns_info = get_namespace(req_ns)
                    if ns_info is None:
                        # Generate a call to load the namespace at runtime
                        # This will be: __spork_require__("my.lib.helpers")
                        load_call = ast.Expr(
                            value=ast.Call(
                                func=ast.Name(id="__spork_require__", ctx=ast.Load()),
                                args=[ast.Constant(value=req_ns)],
                                keywords=[],
                            )
                        )
                        set_location(load_call, form_loc)
                        stmts.append(load_call)

                    # Track alias
                    if alias:
                        ctx.ns_aliases[alias] = req_ns
                        # Generate: alias = __spork_ns_env__("req_ns")
                        alias_assign = ast.Assign(
                            targets=[
                                ast.Name(id=normalize_name(alias), ctx=ast.Store())
                            ],
                            value=ast.Call(
                                func=ast.Name(id="__spork_ns_env__", ctx=ast.Load()),
                                args=[ast.Constant(value=req_ns)],
                                keywords=[],
                            ),
                        )
                        set_location(alias_assign, form_loc)
                        stmts.append(alias_assign)

                    # Handle :refer
                    if refer:
                        if refer == ":all":
                            # Generate: __spork_refer_all__("req_ns", locals())
                            refer_call = ast.Expr(
                                value=ast.Call(
                                    func=ast.Name(
                                        id="__spork_refer_all__", ctx=ast.Load()
                                    ),
                                    args=[
                                        ast.Constant(value=req_ns),
                                        ast.Call(
                                            func=ast.Name(id="locals", ctx=ast.Load()),
                                            args=[],
                                            keywords=[],
                                        ),
                                    ],
                                    keywords=[],
                                )
                            )
                            set_location(refer_call, form_loc)
                            stmts.append(refer_call)
                        else:
                            # Generate individual symbol bindings
                            for sym in refer:
                                ctx.ns_refers[sym] = req_ns
                                # sym = __spork_ns_get__("req_ns", "sym")
                                sym_assign = ast.Assign(
                                    targets=[
                                        ast.Name(
                                            id=normalize_name(sym), ctx=ast.Store()
                                        )
                                    ],
                                    value=ast.Call(
                                        func=ast.Name(
                                            id="__spork_ns_get__", ctx=ast.Load()
                                        ),
                                        args=[
                                            ast.Constant(value=req_ns),
                                            ast.Constant(value=sym),
                                        ],
                                        keywords=[],
                                    ),
                                )
                                set_location(sym_assign, form_loc)
                                stmts.append(sym_assign)

                else:
                    # Python module
                    module_name = req_ns.replace("/", ".")

                    if refer and refer != ":all":
                        # from module import sym1, sym2
                        names = [ast.alias(name=s, asname=None) for s in refer]
                        import_stmt = ast.ImportFrom(
                            module=module_name, names=names, level=0
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)

                        # Also track refers
                        for sym in refer:
                            ctx.ns_refers[sym] = req_ns

                    if alias:
                        # import module as alias
                        import_stmt = ast.Import(
                            names=[
                                ast.alias(
                                    name=module_name, asname=normalize_name(alias)
                                )
                            ]
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)
                        ctx.ns_aliases[alias] = req_ns
                    elif not refer:
                        # Just import module
                        import_stmt = ast.Import(
                            names=[ast.alias(name=module_name, asname=None)]
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)

        elif isinstance(clause_head, Keyword) and clause_head.name == "import":
            # :import is for Python modules (runtime only, no macro loading)
            # Syntax mirrors :require but only emits Python imports
            # (ns foo
            #   (:import
            #     [numpy :as np]
            #     [os.path :as osp]
            #     [collections [defaultdict Counter]]
            #     [math :refer [sin cos]]))
            for spec in clause[1:]:
                if isinstance(spec, VectorLiteral):
                    items = spec.items
                    if len(items) == 0:
                        raise SyntaxError(":import spec cannot be empty")

                    # First element must be module name
                    if not isinstance(items[0], Symbol):
                        raise SyntaxError(
                            f":import spec must start with module name, got {type(items[0]).__name__}"
                        )

                    module_name = items[0].name.replace("/", ".")
                    module_alias = None
                    refer_names = None

                    # Parse remaining elements
                    i = 1
                    while i < len(items):
                        item = items[i]

                        # Check for :as alias
                        if isinstance(item, Keyword) and item.name == "as":
                            if i + 1 >= len(items):
                                raise SyntaxError(":as requires an alias name")
                            if not isinstance(items[i + 1], Symbol):
                                raise SyntaxError(
                                    f":as alias must be a symbol, got {type(items[i + 1]).__name__}"
                                )
                            module_alias = items[i + 1].name
                            i += 2

                        # Check for :refer [...] (selective imports)
                        elif isinstance(item, Keyword) and item.name == "refer":
                            if i + 1 >= len(items):
                                raise SyntaxError(":refer requires a vector of names")
                            if not isinstance(items[i + 1], VectorLiteral):
                                raise SyntaxError(
                                    f":refer requires a vector, got {type(items[i + 1]).__name__}"
                                )
                            # Parse names with optional :as aliases
                            # e.g., [name1 :as alias1 name2]
                            refer_names = []
                            refer_vec = items[i + 1].items
                            j = 0
                            while j < len(refer_vec):
                                if isinstance(refer_vec[j], Symbol):
                                    name = refer_vec[j].name
                                    alias = None
                                    # Check for :as following
                                    if (
                                        j + 2 < len(refer_vec)
                                        and isinstance(refer_vec[j + 1], Keyword)
                                        and refer_vec[j + 1].name == "as"
                                        and isinstance(refer_vec[j + 2], Symbol)
                                    ):
                                        alias = refer_vec[j + 2].name
                                        j += 3
                                    else:
                                        j += 1
                                    refer_names.append((name, alias))
                                else:
                                    j += 1
                            i += 2

                        # Check for bare vector (old syntax: [module [name1 name2]])
                        elif isinstance(item, VectorLiteral):
                            # Parse names with optional :as aliases
                            refer_names = []
                            refer_vec = item.items
                            j = 0
                            while j < len(refer_vec):
                                if isinstance(refer_vec[j], Symbol):
                                    name = refer_vec[j].name
                                    alias = None
                                    # Check for :as following
                                    if (
                                        j + 2 < len(refer_vec)
                                        and isinstance(refer_vec[j + 1], Keyword)
                                        and refer_vec[j + 1].name == "as"
                                        and isinstance(refer_vec[j + 2], Symbol)
                                    ):
                                        alias = refer_vec[j + 2].name
                                        j += 3
                                    else:
                                        j += 1
                                    refer_names.append((name, alias))
                                else:
                                    j += 1
                            i += 1

                        # Bare symbol after module (old syntax: [module name1 name2])
                        elif isinstance(item, Symbol):
                            # Collect remaining symbols as names to import
                            refer_names = []
                            while i < len(items) and isinstance(items[i], Symbol):
                                refer_names.append((items[i].name, None))
                                i += 1

                        else:
                            raise SyntaxError(
                                f"Unexpected element in :import spec: {type(item).__name__}"
                            )

                    # Generate import statements
                    if refer_names:
                        # from module import name1, name2 as alias2, ...
                        # refer_names is now list of (name, alias) tuples
                        names = [
                            ast.alias(name=n, asname=normalize_name(a) if a else None)
                            for n, a in refer_names
                        ]
                        import_stmt = ast.ImportFrom(
                            module=module_name, names=names, level=0
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)

                    if module_alias:
                        # import module as alias
                        import_stmt = ast.Import(
                            names=[
                                ast.alias(
                                    name=module_name,
                                    asname=normalize_name(module_alias),
                                )
                            ]
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)
                        ctx.ns_aliases[module_alias] = module_name

                    # If neither alias nor refer, just import the module
                    if module_alias is None and refer_names is None:
                        import_stmt = ast.Import(
                            names=[ast.alias(name=module_name, asname=None)]
                        )
                        set_location(import_stmt, form_loc)
                        stmts.append(import_stmt)
                else:
                    raise SyntaxError(
                        f":import expects vector specs like [module :as alias], got {type(spec).__name__}"
                    )
        else:
            raise SyntaxError(f"Unknown ns clause: {clause_head}")

    if not stmts:
        # Return a pass statement if no imports
        node = ast.Pass()
        set_location(node, form_loc)
        return node

    return stmts


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


def _compile_std_import(
    module_name: str, alias: str | None, form_loc
) -> list[ast.stmt]:
    """
    Compile an import of a std.* module using __spork_require__.

    Generates:
        __spork_require__("std.string")
        str = __spork_ns_env__("std.string")
    """
    stmts: list[ast.stmt] = []

    # Call __spork_require__ to load the namespace
    require_call = ast.Expr(
        value=ast.Call(
            func=ast.Name(id="__spork_require__", ctx=ast.Load()),
            args=[ast.Constant(value=module_name)],
            keywords=[],
        )
    )
    set_location(require_call, form_loc)
    stmts.append(require_call)

    # Bind to alias (or last segment of module name)
    bind_name = alias if alias else module_name.split(".")[-1]
    bind_stmt = ast.Assign(
        targets=[ast.Name(id=normalize_name(bind_name), ctx=ast.Store())],
        value=ast.Call(
            func=ast.Name(id="__spork_ns_env__", ctx=ast.Load()),
            args=[ast.Constant(value=module_name)],
            keywords=[],
        ),
    )
    set_location(bind_stmt, form_loc)
    stmts.append(bind_stmt)

    return stmts


def _parse_names_vector(names_vec: VectorLiteral) -> list[ast.alias]:
    """
    Parse a vector of names to import, handling :as aliases.

    Examples:
        [sin cos sqrt]           -> [sin, cos, sqrt]
        [sin :as s cos :as c]    -> [sin as s, cos as c]
        [defaultdict Counter]    -> [defaultdict, Counter]
    """
    items = names_vec.items
    namespecs: list[ast.alias] = []
    j = 0
    while j < len(items):
        item = items[j]
        if not isinstance(item, Symbol):
            raise SyntaxError(
                f"import names must be symbols, got {type(item).__name__}"
            )
        name = item.name
        alias = None
        if (
            j + 2 <= len(items)
            and is_keyword(items[j + 1], "as")
            and isinstance(items[j + 2], Symbol)
        ):
            alias = normalize_name(items[j + 2].name)
            j += 3
        else:
            j += 1
        namespecs.append(ast.alias(name=name, asname=alias))
    return namespecs


def _compile_import_clause(clause: VectorLiteral, form_loc=None) -> list[ast.stmt]:
    """
    Compile a single import clause in the new syntax.

    Clause formats:
        [module]                        -> import module
        [module :as alias]              -> import module as alias
        [module [names...]]             -> from module import names...
        [module :as alias [names...]]   -> import module as alias; from module import names...

    Names can have :as aliases:
        [module [name1 :as n1 name2]]   -> from module import name1 as n1, name2
    """
    stmts: list[ast.stmt] = []
    items = clause.items

    if len(items) == 0:
        raise SyntaxError("import clause cannot be empty")

    # First element must be the module name
    if not isinstance(items[0], Symbol):
        raise SyntaxError(
            f"import clause must start with module name, got {type(items[0]).__name__}"
        )

    module_name = items[0].name.replace("/", ".")
    module_alias = None
    names_vec = None

    # Parse remaining elements
    i = 1
    while i < len(items):
        item = items[i]

        # Check for :as alias
        if is_keyword(item, "as"):
            if i + 1 >= len(items):
                raise SyntaxError(":as requires an alias name")
            if not isinstance(items[i + 1], Symbol):
                raise SyntaxError(
                    f":as alias must be a symbol, got {type(items[i + 1]).__name__}"
                )
            module_alias = items[i + 1].name
            i += 2

        # Check for names vector
        elif isinstance(item, VectorLiteral):
            if names_vec is not None:
                raise SyntaxError("import clause can only have one names vector")
            names_vec = item
            i += 1

        else:
            raise SyntaxError(
                f"unexpected element in import clause: {type(item).__name__}"
            )

    # Generate import statements
    # Handle std.* modules specially
    if module_name.startswith("std."):
        if names_vec is not None:
            raise SyntaxError(
                "std.* modules do not support selective imports, use :as instead"
            )
        stmts.extend(_compile_std_import(module_name, module_alias, form_loc))
    else:
        # If we have a module alias, generate: import module as alias
        if module_alias is not None:
            stmt = ast.Import(
                names=[ast.alias(name=module_name, asname=normalize_name(module_alias))]
            )
            set_location(stmt, form_loc)
            stmts.append(stmt)

        # If we have names to import, generate: from module import name1, name2, ...
        if names_vec is not None:
            namespecs = _parse_names_vector(names_vec)
            stmt = ast.ImportFrom(module=module_name, names=namespecs, level=0)
            set_location(stmt, form_loc)
            stmts.append(stmt)

        # If neither alias nor names, just import the module
        if module_alias is None and names_vec is None:
            stmt = ast.Import(names=[ast.alias(name=module_name, asname=None)])
            set_location(stmt, form_loc)
            stmts.append(stmt)

    return stmts


# === def / defn ===


def _get_specialized_vector_constructor(type_expr, value_form):
    """
    Check if we can optimize to a specialized vector constructor.

    Returns 'vec_f64', 'vec_i64', or None.

    Only optimizes when:
    1. Type annotation is (Vector float) or (Vector int)
    2. Value is a vector literal [...]
    """
    # Only optimize vector literals
    if not isinstance(value_form, VectorLiteral):
        return None

    # Check if type_expr is (Vector float) or (Vector int)
    if not isinstance(type_expr, list) or len(type_expr) != 2:
        return None

    base, elem_type = type_expr
    if not (isinstance(base, Symbol) and base.name == "Vector"):
        return None

    if isinstance(elem_type, Symbol):
        if elem_type.name == "float":
            return "vec_f64"
        elif elem_type.name == "int":
            return "vec_i64"

    return None


def _make_specialized_vector_call(constructor, vector_literal):
    """
    Convert a vector literal to a specialized constructor call.

    [1.0 2.0 3.0] with constructor='vec_f64'
    → vec_f64(1.0, 2.0, 3.0)
    """
    # Compile each element
    args = [compile_expr(elem) for elem in vector_literal.items]

    # Build: vec_f64(args...) or vec_i64(args...)
    # These are available directly in the runtime environment
    func = ast.Name(id=constructor, ctx=ast.Load())

    return ast.Call(func=func, args=args, keywords=[])


def compile_def(args, form_loc=None):
    """
    Compile (def name value) or (def pattern value) for destructuring.

    Supports:
    - Simple: (def x 42)
    - With type annotation: (def ^int x 42) -> x: int = 42
    - Generic types: (def ^(List int) items []) -> items: List[int] = []
    - Specialized vectors: (def ^(Vector float) data [1.0 2.0]) -> uses vec_f64
    - Vector destructuring: (def [a b] [1 2])
    - Dict destructuring: (def {:keys [x y]} {:x 1 :y 2})
    """
    if len(args) < 2:
        raise SyntaxError("def requires at least 2 arguments: name/pattern and value")

    # Check for type annotation: (def ^type name value)
    type_annotation = None
    type_expr_raw = None  # Keep the raw type expression for specialized vector check
    if isinstance(args[0], Decorated):
        if len(args) != 3:
            raise SyntaxError(
                "def with type annotation requires 3 arguments: ^type name value"
            )
        type_expr_raw = args[0].expr
        type_annotation = compile_type_annotation(type_expr_raw)
        pattern = args[1]
        value_form = args[2]
    else:
        if len(args) != 2:
            raise SyntaxError(
                "def requires exactly 2 arguments: name/pattern and value"
            )
        pattern = args[0]
        value_form = args[1]

    # Check for specialized vector optimization
    # If we have ^(Vector float) or ^(Vector int) with a vector literal,
    # use the specialized constructor for better performance
    specialized_constructor = None
    if type_expr_raw is not None:
        specialized_constructor = _get_specialized_vector_constructor(
            type_expr_raw, value_form
        )

    if specialized_constructor:
        value = _make_specialized_vector_call(specialized_constructor, value_form)
    else:
        value = compile_expr(value_form)

    # If the value expression generated nested functions, inject them first
    nested_funcs = get_compile_context().get_and_clear_functions()

    # If we have a type annotation and a simple symbol, emit AnnAssign
    if type_annotation is not None and isinstance(pattern, Symbol):
        var_name = normalize_name(pattern.name)
        stmt = ast.AnnAssign(
            target=ast.Name(id=var_name, ctx=ast.Store()),
            annotation=type_annotation,
            value=value,
            simple=1,  # Required for module-level annotations
        )
        if form_loc:
            set_location(stmt, form_loc)
        else:
            copy_location(stmt, pattern)

        if nested_funcs:
            return nested_funcs + [stmt]
        return stmt

    # Use compile_destructure for all patterns (handles both simple symbols and complex patterns)
    stmts = compile_destructure(pattern, value, form_loc)

    if nested_funcs:
        # Return a list with function defs followed by the destructuring assignments
        return nested_funcs + stmts

    # If single statement, return it directly; otherwise return list
    if len(stmts) == 1:
        return stmts[0]
    return stmts


def compile_defmacro(args):
    """
    (defmacro name [params] body...)
    This should not be called during normal compilation since defmacros
    are processed in a first pass. Returns a pass statement.
    """
    # Return a pass statement (macros don't generate runtime code)
    return ast.Pass()


def compile_defclass(args, form_loc=None):
    """
    Compile class definitions.

    Syntax:
        (defclass Name body...)
        (defclass Name [Parent1 Parent2] body...)
        (defclass ^decorator Name body...)
        (defclass ^decorator1 ^decorator2 Name [Parent] body...)

    Body can contain:
        - (defn method-name [self ...] ...) for methods
        - (def class-var value) for class variables
        - (field name type) for annotated fields (no default)
        - (field name type default) for annotated fields with default
        - (defn ^staticmethod name [...] ...) for static methods
        - (defn ^classmethod name [cls ...] ...) for class methods
        - (defn ^property name [self] ...) for properties

    Examples:
        (defclass Point
          (defn __init__ [self x y]
            (set! self.x x)
            (set! self.y y))
          (defn __repr__ [self]
            (+ "Point(" (str self.x) ", " (str self.y) ")")))

        (defclass Child [Parent]
          (defn __init__ [self name]
            (call (super) __init__)
            (set! self.name name)))

        (defclass ^dataclass Config
          (field name str "default")
          (field debug bool false)
          (field max-retries int 3))
    """
    if len(args) < 1:
        raise SyntaxError("defclass requires at least a class name")

    # Collect decorators (^decorator before the name)
    decorators = []
    i = 0
    while i < len(args) and isinstance(args[i], Decorated):
        decorators.append(args[i].expr)
        i += 1
    args = args[i:]

    if len(args) < 1:
        raise SyntaxError("defclass requires a class name")

    name_sym = args[0]
    if not isinstance(name_sym, Symbol):
        raise SyntaxError("defclass name must be a symbol")

    class_name = normalize_name(name_sym.name)

    # Check for base classes: (defclass Name [Base1 Base2] body...)
    bases = []
    body_start = 1
    if len(args) > 1 and isinstance(args[1], VectorLiteral):
        for base in args[1].items:
            if isinstance(base, Symbol):
                bases.append(compile_expr(base))
            else:
                bases.append(compile_expr(base))
        body_start = 2

    body_forms = args[body_start:]

    # Compile class body
    class_body = []
    for form in body_forms:
        if isinstance(form, list) and form:
            head = form[0]
            if is_symbol(head, "defn"):
                # Method definition
                method = compile_defn(form[1:])
                class_body.append(method)
            elif is_symbol(head, "def"):
                # Class variable
                var_stmts = compile_def(form[1:])
                if isinstance(var_stmts, list):
                    class_body.extend(var_stmts)
                else:
                    class_body.append(var_stmts)
            elif is_symbol(head, "field"):
                # Annotated field: (field name type) or (field name type default)
                field_stmts = compile_field(form[1:])
                class_body.extend(field_stmts)
            else:
                # Other statements (rare but possible)
                stmt = compile_stmt(form)
                if isinstance(stmt, list):
                    class_body.extend(stmt)
                else:
                    class_body.append(stmt)
        else:
            # Expression statement
            class_body.append(ast.Expr(value=compile_expr(form)))

    # Ensure class body is not empty
    if not class_body:
        class_body.append(ast.Pass())

    # Compile decorator expressions
    decorator_list = []
    for dec in decorators:
        if isinstance(dec, Symbol):
            # Simple decorator: ^dataclass -> @dataclass
            decorator_list.append(ast.Name(id=normalize_name(dec.name), ctx=ast.Load()))
        elif isinstance(dec, list) and dec:
            # Decorator with args: ^(decorator arg) -> @decorator(arg)
            decorator_list.append(compile_expr(dec))
        else:
            raise SyntaxError(f"Invalid decorator expression: {dec!r}")

    node = ast.ClassDef(
        name=class_name,
        bases=bases,
        keywords=[],
        body=class_body,
        decorator_list=decorator_list,
    )
    if form_loc:
        set_location(node, form_loc)
    else:
        copy_location(node, name_sym)
    return node


def compile_field(args):
    """
    Compile annotated field declarations for classes.

    Syntax:
        (field name type)         -> name: type
        (field name type default) -> name: type = default

    Examples:
        (field x int)             -> x: int
        (field name str "")       -> name: str = ""
        (field items list [])     -> items: list = []
    """
    if len(args) < 2:
        raise SyntaxError("field requires at least name and type")
    if len(args) > 3:
        raise SyntaxError("field takes at most name, type, and default")

    name_form = args[0]
    type_form = args[1]
    default_form = args[2] if len(args) == 3 else None

    if not isinstance(name_form, Symbol):
        raise SyntaxError("field name must be a symbol")

    field_name = normalize_name(name_form.name)
    type_expr = compile_expr(type_form)

    # Create annotated assignment: name: type or name: type = default
    target = ast.Name(id=field_name, ctx=ast.Store())

    if default_form is not None:
        # name: type = default
        default_expr = compile_expr(default_form)
        stmt = ast.AnnAssign(
            target=target,
            annotation=type_expr,
            value=default_expr,
            simple=1,
        )
    else:
        # name: type (no default)
        stmt = ast.AnnAssign(
            target=target,
            annotation=type_expr,
            value=None,
            simple=1,
        )

    return [stmt]


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
        elif is_symbol(item, "#"):
            # Keyword-only marker - everything after is keyword-only
            i += 1
        else:
            # Regular positional arg (could have default)
            if not has_vararg and not is_symbol(item, "#"):
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

        # Check for # keyword-only marker
        if is_symbol(item, "#"):
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


def compile_pattern_dispatch_clause(
    param_patterns, guard_expr, body_forms, ok_var, is_generator=False
):
    """
    Compile a single clause of pattern-based dispatch.

    Generates code that:
    1. Checks types and patterns for each parameter
    2. Binds variables (with type annotations when present)
    3. Checks guard if present
    4. Executes body if all checks pass

    Returns (stmts, bindings_made) where stmts is the list of statements
    and bindings_made indicates if any pattern matching was done.
    """
    stmts = []
    # bindings_list now contains (name, value_expr, type_expr) tuples
    # type_expr is None if no type annotation, otherwise the compiled type AST
    bindings_list = []
    # Track the current type annotation for the pattern being processed
    current_type_annotation = None
    arg_index = 0

    for param_info in param_patterns:
        if param_info[0] == "&":
            # Vararg: pattern, type_expr
            _, pattern, type_expr = param_info
            # Get rest of args
            value_expr = ast.Subscript(
                value=ast.Name(id="__args__", ctx=ast.Load()),
                slice=ast.Slice(
                    lower=ast.Constant(value=arg_index),
                    upper=None,
                    step=None,
                ),
                ctx=ast.Load(),
            )
            # Type check if present
            if type_expr is not None:
                type_ast = compile_expr(type_expr)
                check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.UnaryOp(
                                op=ast.Not(),
                                operand=ast.Call(
                                    func=ast.Name(id="isinstance", ctx=ast.Load()),
                                    args=[value_expr, type_ast],
                                    keywords=[],
                                ),
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                stmts.append(check)
                # Set current type annotation for bindings created by pattern check
                current_type_annotation = compile_type_annotation(type_expr)
            else:
                current_type_annotation = None
            # Pattern match - pass type annotation for bindings
            stmts.extend(
                compile_pattern_check(
                    pattern, value_expr, ok_var, bindings_list, current_type_annotation
                )
            )

        elif param_info[0] == "**":
            # Kwargs: pattern
            _, pattern, _ = param_info
            value_expr = ast.Name(id="__kwargs__", ctx=ast.Load())
            stmts.extend(
                compile_pattern_check(pattern, value_expr, ok_var, bindings_list)
            )

        else:
            # Regular parameter: (pattern, _, type_expr)
            pattern, _, type_expr = param_info
            value_expr = ast.Subscript(
                value=ast.Name(id="__args__", ctx=ast.Load()),
                slice=ast.Constant(value=arg_index),
                ctx=ast.Load(),
            )
            # Type check if present
            if type_expr is not None:
                type_ast = compile_expr(type_expr)
                check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.UnaryOp(
                                op=ast.Not(),
                                operand=ast.Call(
                                    func=ast.Name(id="isinstance", ctx=ast.Load()),
                                    args=[value_expr, type_ast],
                                    keywords=[],
                                ),
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                stmts.append(check)
                # Set current type annotation for bindings created by pattern check
                current_type_annotation = compile_type_annotation(type_expr)
            else:
                current_type_annotation = None
            # Pattern match - pass type annotation for bindings
            stmts.extend(
                compile_pattern_check(
                    pattern, value_expr, ok_var, bindings_list, current_type_annotation
                )
            )
            arg_index += 1

    # Build the body that runs when patterns match
    match_body = []

    # Add bindings - now with type annotations when present
    for binding in bindings_list:
        if len(binding) == 3:
            name, val_expr, type_annotation = binding
        else:
            # Backward compatibility
            name, val_expr = binding
            type_annotation = None

        if type_annotation is not None:
            # Emit annotated assignment: x: int = value
            match_body.append(
                ast.AnnAssign(
                    target=ast.Name(id=normalize_name(name), ctx=ast.Store()),
                    annotation=type_annotation,
                    value=val_expr,
                    simple=1,
                )
            )
        else:
            match_body.append(
                ast.Assign(
                    targets=[ast.Name(id=normalize_name(name), ctx=ast.Store())],
                    value=val_expr,
                )
            )

    # Save nested functions count before compiling body/guard
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)

    # Compile guard if present
    if guard_expr is not None:
        guard_compiled = compile_expr(guard_expr)

        # Compile body forms
        body_stmts = []
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            body_stmts.extend(flatten_stmts([s]))

        # Last form - return it
        last_form = body_forms[-1]
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "let":
                body_stmts.extend(
                    flatten_stmts([compile_let_stmt_with_return(last_form[1:])])
                )
            elif head_name == "do":
                body_stmts.extend(
                    flatten_stmts([compile_do_stmt_with_return(last_form[1:])])
                )
            elif head_name in ("while", "for", "set!"):
                body_stmts.extend(flatten_stmts([compile_stmt(last_form)]))
                if not is_generator:
                    body_stmts.append(ast.Return(value=ast.Constant(value=None)))
            elif head_name == "return":
                body_stmts.extend(flatten_stmts([compile_stmt(last_form)]))
            else:
                if is_generator:
                    body_stmts.extend(flatten_stmts([compile_stmt(last_form)]))
                else:
                    body_stmts.append(ast.Return(value=compile_expr(last_form)))
        else:
            if is_generator:
                body_stmts.extend(flatten_stmts([compile_stmt(last_form)]))
            else:
                body_stmts.append(ast.Return(value=compile_expr(last_form)))

        # Extract nested functions
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]
        match_body.extend(nested_funcs)

        # Wrap body in guard check
        guard_if = ast.If(
            test=guard_compiled,
            body=body_stmts if body_stmts else [ast.Pass()],
            orelse=[],
        )
        match_body.append(guard_if)
    else:
        # No guard - compile body directly
        for f in body_forms[:-1]:
            s = compile_stmt(f)
            match_body.extend(flatten_stmts([s]))

        last_form = body_forms[-1]
        if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
            head_name = last_form[0].name
            if head_name == "let":
                match_body.extend(
                    flatten_stmts([compile_let_stmt_with_return(last_form[1:])])
                )
            elif head_name == "do":
                match_body.extend(
                    flatten_stmts([compile_do_stmt_with_return(last_form[1:])])
                )
            elif head_name in ("while", "for", "set!"):
                match_body.extend(flatten_stmts([compile_stmt(last_form)]))
                if not is_generator:
                    match_body.append(ast.Return(value=ast.Constant(value=None)))
            elif head_name == "return":
                match_body.extend(flatten_stmts([compile_stmt(last_form)]))
            else:
                if is_generator:
                    match_body.extend(flatten_stmts([compile_stmt(last_form)]))
                else:
                    match_body.append(ast.Return(value=compile_expr(last_form)))
        else:
            if is_generator:
                match_body.extend(flatten_stmts([compile_stmt(last_form)]))
            else:
                match_body.append(ast.Return(value=compile_expr(last_form)))

        # Extract nested functions
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]
        # Insert nested funcs at beginning of match_body
        match_body = list(nested_funcs) + match_body

    # Wrap in: if ok_var: <match_body>
    if match_body:
        inner_if = ast.If(
            test=ast.Name(id=ok_var, ctx=ast.Load()),
            body=match_body,  # type: ignore
            orelse=[],
        )
        stmts.append(inner_if)

    return stmts


def compile_arity_body(params, body_forms):
    """
    Compile a single arity's body, returning (args_node, body_nodes).
    This is shared logic used by both single-arity and multi-arity compilation.
    """
    args_node, destructure_stmts = compile_params(params.items)
    body_nodes = []

    # Add destructuring statements at the start of the function body
    body_nodes.extend(destructure_stmts)

    # Compile all but the last form as statements
    for f in body_forms[:-1]:
        stmts = compile_stmt(f)
        body_nodes.extend(flatten_stmts([stmts]))

    # Last form: try to return it as an expression, but handle let/do specially
    last_form = body_forms[-1]

    if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
        head_name = last_form[0].name

        if head_name == "let":
            let_stmts = compile_let_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([let_stmts]))
        elif head_name == "do":
            do_stmts = compile_do_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([do_stmts]))
        elif head_name == "try":
            try_stmts = compile_try_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([try_stmts]))
        elif head_name == "with":
            with_stmt = compile_with_stmt_with_return(last_form[1:])
            body_nodes.append(with_stmt)
        elif head_name in ("while", "for", "set!"):
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
            body_nodes.append(ast.Return(value=ast.Constant(value=None)))
        elif head_name == "return":
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            body_nodes.append(ast.Return(value=compile_expr(last_form)))
    else:
        body_nodes.append(ast.Return(value=compile_expr(last_form)))

    return args_node, body_nodes


def compile_multi_arity_defn(
    name_sym,
    arity_forms,
    decorators=None,
    form_loc=None,
    is_async=False,
    is_generator=False,
    return_type_node=None,
):
    """
    Compile a multi-arity function definition with pattern matching support.

    Example:
        (defn add
          ([x] x)
          ([x y] (+ x y))
          ([x y & more] (+ x y (apply + more))))

    With pattern matching:
        (defn describe
          ([^int n :when (>= n 0)] "nonnegative int")
          ([^int n] "negative int")
          ([^str s] "string")
          ([x] "something else"))

    Generates:
        def add(*__args__, **__kwargs__):
            __n__ = len(__args__)
            if __n__ == 1:
                # Try each clause with arity 1 in order
                ...
            elif __n__ == 2:
                ...
            else:
                raise TypeError(...)
    """
    fn_name = normalize_name(name_sym.name)

    # Check if we need pattern dispatch
    use_pattern_dispatch = has_pattern_dispatch(arity_forms)

    if use_pattern_dispatch:
        return compile_multi_arity_pattern_defn(
            name_sym,
            arity_forms,
            decorators,
            form_loc,
            is_async,
            is_generator,
            return_type_node,
        )

    # Parse all arities (simple case without pattern matching)
    arities = []
    has_variadic = False
    has_any_kwargs = False

    for arity_form in arity_forms:
        params, body_forms, min_args, has_vararg, has_kwargs = parse_arity(arity_form)
        if has_vararg:
            if has_variadic:
                raise SyntaxError("Only one variadic arity allowed per function")
            has_variadic = True
        if has_kwargs:
            has_any_kwargs = True
        arities.append((params, body_forms, min_args, has_vararg, has_kwargs))

    # Sort arities: fixed arities first (by min_args), variadic last
    fixed_arities = [(p, b, m, v, k) for p, b, m, v, k in arities if not v]
    variadic_arities = [(p, b, m, v, k) for p, b, m, v, k in arities if v]

    # Check for duplicate fixed arities
    fixed_counts = [m for _, _, m, _, _ in fixed_arities]
    if len(fixed_counts) != len(set(fixed_counts)):
        raise SyntaxError("Duplicate arity definitions")

    # Sort fixed arities by arg count
    fixed_arities.sort(key=lambda x: x[2])

    # Build the dispatch function
    # def fn_name(*__args__, **__kwargs__):
    args_node = ast.arguments(
        posonlyargs=[],
        args=[],
        vararg=ast.arg(arg="__args__", annotation=None),
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=ast.arg(arg="__kwargs__", annotation=None) if has_any_kwargs else None,
        defaults=[],
    )

    body_nodes = []

    # __n__ = len(__args__)
    body_nodes.append(
        ast.Assign(
            targets=[ast.Name(id="__n__", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="len", ctx=ast.Load()),
                args=[ast.Name(id="__args__", ctx=ast.Load())],
                keywords=[],
            ),
        )
    )

    # Build if/elif chain for dispatch
    dispatch_cases = []

    for params, body_forms, min_args, _, has_kwargs in fixed_arities:
        # Condition: __n__ == min_args
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=min_args)],
        )

        # Generate body for this arity
        arity_body = compile_arity_dispatch_body(
            params, body_forms, has_kwargs, is_generator
        )
        dispatch_cases.append((test, arity_body))

    # Add variadic arity if present
    if variadic_arities:
        params, body_forms, min_args, has_vararg, has_kwargs = variadic_arities[0]
        # Condition: __n__ >= min_args
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.GtE()],
            comparators=[ast.Constant(value=min_args)],
        )
        arity_body = compile_arity_dispatch_body(
            params, body_forms, has_kwargs, is_generator
        )
        dispatch_cases.append((test, arity_body))

    # Build the if/elif/else chain
    if dispatch_cases:
        # Start with the else clause (error)
        error_msg = f"{fn_name} called with wrong number of arguments"
        else_body = [
            ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="TypeError", ctx=ast.Load()),
                    args=[ast.Constant(value=error_msg)],
                    keywords=[],
                ),
                cause=None,
            )
        ]

        # Build from the end
        current_else: list[ast.stmt] = list(else_body)
        for test, arity_body in reversed(dispatch_cases):
            current_if = ast.If(
                test=test,
                body=arity_body,
                orelse=current_else,
            )
            current_else = [current_if]

        body_nodes.append(current_else[0])

    # Check for yield without ^generator annotation
    if contains_yield(body_nodes) and not is_generator:
        raise SyntaxError(
            f"Function '{fn_name}' contains yield but is not marked with ^generator. "
            f"Use (defn ^generator {name_sym.name} ...) for generator functions."
        )

    # Compile decorator expressions
    decorator_list = []
    if decorators:
        for dec in decorators:
            if isinstance(dec, Symbol):
                # Simple decorator: ^staticmethod -> @staticmethod
                decorator_list.append(
                    ast.Name(id=normalize_name(dec.name), ctx=ast.Load())
                )
            elif isinstance(dec, list) and dec:
                # Decorator with args: ^(route "/api") -> @route("/api")
                decorator_list.append(compile_expr(dec))
            else:
                raise SyntaxError(f"Invalid decorator expression: {dec!r}")

    if is_async:
        func = ast.AsyncFunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )
    else:
        func = ast.FunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )

    # Set source location on the function definition
    if form_loc:
        set_location(func, form_loc)
    else:
        copy_location(func, name_sym)

    # Inject any nested function definitions at the start of the function body
    nested_funcs = get_compile_context().get_and_clear_functions()
    if nested_funcs:
        func.body = nested_funcs + func.body

    return func


def compile_multi_arity_pattern_defn(
    name_sym,
    arity_forms,
    decorators=None,
    form_loc=None,
    is_async=False,
    is_generator=False,
    return_type_node=None,
):
    """
    Compile a multi-arity function definition with pattern matching dispatch.

    Groups clauses by arity, then tries each clause within an arity group
    in source order using pattern matching.

    Example:
        (defn describe
          ([^int n :when (>= n 0)] "nonnegative int")
          ([^int n] "negative int")
          ([^str s] "string")
          ([x] "something else"))
    """
    fn_name = normalize_name(name_sym.name)

    # Parse all arities with pattern info
    clauses = []
    has_any_kwargs = False

    for arity_form in arity_forms:
        param_patterns, guard_expr, body_forms, arity, has_vararg, has_kwargs = (
            parse_arity_with_patterns(arity_form)
        )
        if has_kwargs:
            has_any_kwargs = True
        clauses.append(
            (param_patterns, guard_expr, body_forms, arity, has_vararg, has_kwargs)
        )

    # Group clauses by arity
    # Variadic clauses (has_vararg=True) go in a separate group
    arity_groups = {}  # arity -> list of (param_patterns, guard_expr, body_forms, has_kwargs)
    variadic_clauses = []  # list of (param_patterns, guard_expr, body_forms, min_arity, has_kwargs)

    for (
        param_patterns,
        guard_expr,
        body_forms,
        arity,
        has_vararg,
        has_kwargs,
    ) in clauses:
        if has_vararg:
            # Count non-vararg params for min arity
            min_arity = sum(1 for p in param_patterns if p[0] not in ("&", "**"))
            variadic_clauses.append(
                (param_patterns, guard_expr, body_forms, min_arity, has_kwargs)
            )
        else:
            if arity not in arity_groups:
                arity_groups[arity] = []
            arity_groups[arity].append(
                (param_patterns, guard_expr, body_forms, has_kwargs)
            )

    # Build the dispatch function
    args_node = ast.arguments(
        posonlyargs=[],
        args=[],
        vararg=ast.arg(arg="__args__", annotation=None),
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=ast.arg(arg="__kwargs__", annotation=None) if has_any_kwargs else None,
        defaults=[],
    )

    body_nodes = []

    # __n__ = len(__args__)
    body_nodes.append(
        ast.Assign(
            targets=[ast.Name(id="__n__", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="len", ctx=ast.Load()),
                args=[ast.Name(id="__args__", ctx=ast.Load())],
                keywords=[],
            ),
        )
    )

    # Build if/elif chain for arity dispatch
    dispatch_cases = []

    # Sort arities for deterministic output
    for arity in sorted(arity_groups.keys()):
        group = arity_groups[arity]
        # Condition: __n__ == arity
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=arity)],
        )

        # Generate body that tries each clause in order
        arity_body = compile_arity_pattern_group(group, fn_name, is_generator)
        dispatch_cases.append((test, arity_body))

    # Add variadic clauses
    # Sort by min_arity descending so more specific patterns are tried first
    variadic_clauses.sort(key=lambda x: x[3], reverse=True)
    for (
        param_patterns,
        guard_expr,
        body_forms,
        min_arity,
        has_kwargs,
    ) in variadic_clauses:
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.GtE()],
            comparators=[ast.Constant(value=min_arity)],
        )
        # Single clause for variadic
        arity_body = compile_arity_pattern_group(
            [(param_patterns, guard_expr, body_forms, has_kwargs)],
            fn_name,
            is_generator,
        )
        dispatch_cases.append((test, arity_body))

    # Build the if/elif/else chain
    if dispatch_cases:
        # Start with the else clause (error)
        error_msg = (
            f"{fn_name} called with wrong number of arguments or no matching pattern"
        )
        else_body = [
            ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="MatchError", ctx=ast.Load()),
                    args=[ast.Constant(value=error_msg)],
                    keywords=[],
                ),
                cause=None,
            )
        ]

        # Build from the end
        current_else: list[ast.stmt] = list(else_body)
        for test, arity_body in reversed(dispatch_cases):
            current_if = ast.If(
                test=test,
                body=arity_body,
                orelse=current_else,
            )
            current_else = [current_if]

        body_nodes.append(current_else[0])

    # Check for yield without ^generator annotation
    if contains_yield(body_nodes) and not is_generator:
        raise SyntaxError(
            f"Function '{fn_name}' contains yield but is not marked with ^generator. "
            f"Use (defn ^generator {name_sym.name} ...) for generator functions."
        )

    # Compile decorator expressions
    decorator_list = []
    if decorators:
        for dec in decorators:
            if isinstance(dec, Symbol):
                decorator_list.append(
                    ast.Name(id=normalize_name(dec.name), ctx=ast.Load())
                )
            elif isinstance(dec, list) and dec:
                decorator_list.append(compile_expr(dec))
            else:
                raise SyntaxError(f"Invalid decorator expression: {dec!r}")

    if is_async:
        func = ast.AsyncFunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )
    else:
        func = ast.FunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )

    if form_loc:
        set_location(func, form_loc)
    else:
        copy_location(func, name_sym)

    # Inject any nested function definitions at the start of the function body
    nested_funcs = get_compile_context().get_and_clear_functions()
    if nested_funcs:
        func.body = nested_funcs + func.body

    return func


def compile_arity_pattern_group(clauses, fn_name, is_generator=False):
    """
    Compile a group of clauses with the same arity.
    Tries each clause in order using pattern matching.
    Returns list of statements.
    """
    stmts = []

    for param_patterns, guard_expr, body_forms, _ in clauses:
        ok_var = gensym("__clause_ok_")

        # Initialize ok flag
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                value=ast.Constant(value=True),
            )
        )

        # Compile pattern matching for this clause
        clause_stmts = compile_pattern_dispatch_clause(
            param_patterns, guard_expr, body_forms, ok_var, is_generator
        )
        stmts.extend(clause_stmts)

    # If no clause matched, raise MatchError
    stmts.append(
        ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="MatchError", ctx=ast.Load()),
                args=[ast.Constant(value=f"No matching clause for {fn_name}")],
                keywords=[],
            ),
            cause=None,
        )
    )

    return stmts


def compile_arity_dispatch_body(params, body_forms, has_kwargs, is_generator=False):
    """
    Compile the body of an arity case in dispatch.

    Generates parameter unpacking from __args__ and then the body.
    Now supports type annotations via ^type syntax (Phase 4).

    When a parameter has a type annotation like ^int x, this generates:
        x: int = __args__[0]
    instead of:
        x = __args__[0]
    """
    body_nodes = []

    # Unpack parameters from __args__
    items = params.items
    i = 0
    arg_index = 0

    # Track pending type annotation from ^type syntax
    pending_type_annotation = None

    while i < len(items):
        item = items[i]

        # Check for type annotation (^type before parameter)
        if isinstance(item, Decorated):
            pending_type_annotation = compile_type_annotation(item.expr)
            i += 1
            continue

        if is_symbol(item, "&"):
            # Vararg: rest = __args__[arg_index:]
            vararg_item = items[i + 1]

            # Use pending type annotation if available
            vararg_annotation = pending_type_annotation
            pending_type_annotation = None

            if isinstance(vararg_item, Symbol):
                vararg_name = normalize_name(vararg_item.name)
                value_expr = ast.Subscript(
                    value=ast.Name(id="__args__", ctx=ast.Load()),
                    slice=ast.Slice(
                        lower=ast.Constant(value=arg_index),
                        upper=None,
                        step=None,
                    ),
                    ctx=ast.Load(),
                )
                if vararg_annotation is not None:
                    # Emit annotated assignment: rest: Type = __args__[idx:]
                    body_nodes.append(
                        ast.AnnAssign(
                            target=ast.Name(id=vararg_name, ctx=ast.Store()),
                            annotation=vararg_annotation,
                            value=value_expr,
                            simple=1,
                        )
                    )
                else:
                    body_nodes.append(
                        ast.Assign(
                            targets=[ast.Name(id=vararg_name, ctx=ast.Store())],
                            value=value_expr,
                        )
                    )
            else:
                # Destructuring vararg
                temp = gensym("__vararg_")
                body_nodes.append(
                    ast.Assign(
                        targets=[ast.Name(id=temp, ctx=ast.Store())],
                        value=ast.Subscript(
                            value=ast.Name(id="__args__", ctx=ast.Load()),
                            slice=ast.Slice(
                                lower=ast.Constant(value=arg_index),
                                upper=None,
                                step=None,
                            ),
                            ctx=ast.Load(),
                        ),
                    )
                )
                body_nodes.extend(
                    compile_destructure(vararg_item, ast.Name(id=temp, ctx=ast.Load()))
                )
            i += 2

        elif is_symbol(item, "**"):
            # Kwargs: kwargs = __kwargs__
            kwargs_item = items[i + 1]

            # Use pending type annotation if available
            kwargs_annotation = pending_type_annotation
            pending_type_annotation = None

            if isinstance(kwargs_item, Symbol):
                kwargs_name = normalize_name(kwargs_item.name)
                if kwargs_annotation is not None:
                    body_nodes.append(
                        ast.AnnAssign(
                            target=ast.Name(id=kwargs_name, ctx=ast.Store()),
                            annotation=kwargs_annotation,
                            value=ast.Name(id="__kwargs__", ctx=ast.Load()),
                            simple=1,
                        )
                    )
                else:
                    body_nodes.append(
                        ast.Assign(
                            targets=[ast.Name(id=kwargs_name, ctx=ast.Store())],
                            value=ast.Name(id="__kwargs__", ctx=ast.Load()),
                        )
                    )
            else:
                # Destructuring kwargs
                temp = gensym("__kwargs_")
                body_nodes.append(
                    ast.Assign(
                        targets=[ast.Name(id=temp, ctx=ast.Store())],
                        value=ast.Name(id="__kwargs__", ctx=ast.Load()),
                    )
                )
                body_nodes.extend(
                    compile_destructure(kwargs_item, ast.Name(id=temp, ctx=ast.Load()))
                )
            i += 2

        elif is_symbol(item, "#"):
            # Keyword-only marker - skip (handled by kwargs in multi-arity)
            i += 1

        else:
            # Regular positional arg
            param_item = item

            if isinstance(item, list) and len(item) == 2:
                param_item = item[0]

            # Use pending type annotation if available
            param_annotation = pending_type_annotation
            pending_type_annotation = None

            if isinstance(param_item, Symbol):
                param_name = normalize_name(param_item.name)
                value_expr = ast.Subscript(
                    value=ast.Name(id="__args__", ctx=ast.Load()),
                    slice=ast.Constant(value=arg_index),
                    ctx=ast.Load(),
                )
                if param_annotation is not None:
                    # Emit annotated assignment: x: int = __args__[0]
                    body_nodes.append(
                        ast.AnnAssign(
                            target=ast.Name(id=param_name, ctx=ast.Store()),
                            annotation=param_annotation,
                            value=value_expr,
                            simple=1,
                        )
                    )
                else:
                    body_nodes.append(
                        ast.Assign(
                            targets=[ast.Name(id=param_name, ctx=ast.Store())],
                            value=value_expr,
                        )
                    )
            elif is_destructuring_pattern(param_item):
                # Destructuring pattern
                temp = gensym("__param_")
                body_nodes.append(
                    ast.Assign(
                        targets=[ast.Name(id=temp, ctx=ast.Store())],
                        value=ast.Subscript(
                            value=ast.Name(id="__args__", ctx=ast.Load()),
                            slice=ast.Constant(value=arg_index),
                            ctx=ast.Load(),
                        ),
                    )
                )
                body_nodes.extend(
                    compile_destructure(param_item, ast.Name(id=temp, ctx=ast.Load()))
                )
            else:
                raise SyntaxError(f"Invalid parameter: {param_item}")

            arg_index += 1
            i += 1

    # Compile the body
    for f in body_forms[:-1]:
        stmts = compile_stmt(f)
        body_nodes.extend(flatten_stmts([stmts]))

    last_form = body_forms[-1]
    if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
        head_name = last_form[0].name

        if head_name == "let":
            let_stmts = compile_let_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([let_stmts]))
        elif head_name == "do":
            do_stmts = compile_do_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([do_stmts]))
        elif head_name == "try":
            try_stmts = compile_try_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([try_stmts]))
        elif head_name == "with":
            with_stmt = compile_with_stmt_with_return(last_form[1:])
            body_nodes.append(with_stmt)
        elif head_name in ("while", "for", "async-for", "set!"):
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
            # Only add return None if not a generator
            if not is_generator:
                body_nodes.append(ast.Return(value=ast.Constant(value=None)))
        elif head_name == "return":
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular expression - check if generator
            if is_generator:
                # Generator function - just add the statement, no return
                stmts = compile_stmt(last_form)
                body_nodes.extend(flatten_stmts([stmts]))
            else:
                # Regular function - add return
                body_nodes.append(ast.Return(value=compile_expr(last_form)))
    else:
        # Simple value - check if generator
        if is_generator:
            # Generator function - compile as statement, no return
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular function - return it
            body_nodes.append(ast.Return(value=compile_expr(last_form)))

    return body_nodes


def compile_defn(args, form_loc=None):
    if len(args) < 2:
        raise SyntaxError("defn requires name and params")

    # Collect decorators, flags, and return type from metadata before the name
    # Uses extract_decorators_and_type to properly classify:
    # - ^async, ^generator -> flags
    # - ^int, ^(List int) -> return type annotation
    # - ^(route "/api") -> decorator
    decorated_list = []
    i = 0
    while i < len(args) and isinstance(args[i], Decorated):
        decorated_list.append(args[i])
        i += 1
    args = args[i:]

    decorators, is_async, is_generator, return_type = extract_decorators_and_type(
        decorated_list
    )

    # Compile return type annotation if present
    return_type_node = None
    if return_type is not None:
        return_type_node = compile_type_annotation(return_type)

    if len(args) < 2:
        raise SyntaxError("defn requires name and params")

    name_sym = args[0]
    if not isinstance(name_sym, Symbol):
        raise SyntaxError("defn name must be symbol")

    # Check for multi-arity syntax
    if is_multi_arity(args[1:]):
        return compile_multi_arity_defn(
            name_sym,
            args[1:],
            decorators,
            form_loc,
            is_async,
            is_generator,
            return_type_node,
        )

    params = args[1]
    if not isinstance(params, VectorLiteral):
        raise SyntaxError("defn params must be vector")
    body_forms = args[2:] or [None]
    args_node, destructure_stmts = compile_params(params.items)
    body_nodes = []

    # Check for docstring (first form is a string literal)
    docstring_node = None
    if body_forms and isinstance(body_forms[0], str):
        # Extract docstring as an Expr node
        docstring_node = ast.Expr(value=ast.Constant(value=body_forms[0]))
        # If docstring is the only form, we need at least one form for the body
        if len(body_forms) == 1:
            body_forms = [None]
        else:
            body_forms = body_forms[1:]

    # Add destructuring statements at the start of the function body
    body_nodes.extend(destructure_stmts)

    # Compile all but the last form as statements
    for f in body_forms[:-1]:
        stmts = compile_stmt(f)
        body_nodes.extend(flatten_stmts([stmts]))

    # Last form: try to return it as an expression, but handle let/do specially
    last_form = body_forms[-1]

    # Check if it's a let or do that might contain statements
    if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
        head_name = last_form[0].name

        if head_name == "let":
            # Compile let as statements, with last body form returned
            let_stmts = compile_let_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([let_stmts]))
        elif head_name == "do":
            # Compile do as statements, with last form returned
            do_stmts = compile_do_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([do_stmts]))
        elif head_name == "try":
            # Compile try as statements, with last body form returned
            try_stmts = compile_try_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([try_stmts]))
        elif head_name == "with":
            # Compile with as statements, with last body form returned
            with_stmt = compile_with_stmt_with_return(last_form[1:])
            body_nodes.append(with_stmt)
        elif head_name == "loop":
            # Compile loop as statements, with last body form returned
            loop_stmts = compile_loop_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([loop_stmts]))
        elif head_name in ("while", "for", "async-for", "set!"):
            # Pure statement forms - no return value
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
            # Only add return None if not a generator
            if not is_generator:
                ret_node = ast.Return(value=ast.Constant(value=None))
                last_loc = get_source_location(last_form)
                set_location(ret_node, last_loc)
                body_nodes.append(ret_node)
        elif head_name == "return":
            # Already a return statement
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular expression - check if generator
            if is_generator:
                # Generator function - just add the statement, no return
                stmts = compile_stmt(last_form)
                body_nodes.extend(flatten_stmts([stmts]))
            else:
                # Regular function - add return
                ret_node = ast.Return(value=compile_expr(last_form))
                last_loc = get_source_location(last_form)
                set_location(ret_node, last_loc)
                body_nodes.append(ret_node)
    else:
        # Simple value - check if generator
        if is_generator:
            # Generator function - compile as statement, no return
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular function - return it
            ret_node = ast.Return(value=compile_expr(last_form))
            last_loc = get_source_location(last_form)
            set_location(ret_node, last_loc)
            body_nodes.append(ret_node)

    # Ensure function has at least one statement
    if not body_nodes:
        body_nodes.append(ast.Pass())

    # Check for yield without ^generator annotation
    if contains_yield(body_nodes) and not is_generator:
        fn_name = normalize_name(name_sym.name)
        raise SyntaxError(
            f"Function '{fn_name}' contains yield but is not marked with ^generator. "
            f"Use (defn ^generator {name_sym.name} ...) for generator functions."
        )

    # Compile decorator expressions
    decorator_list = []
    for dec in decorators:
        if isinstance(dec, Symbol):
            # Simple decorator: ^staticmethod -> @staticmethod
            decorator_list.append(ast.Name(id=normalize_name(dec.name), ctx=ast.Load()))
        elif isinstance(dec, list) and dec:
            # Decorator with args: ^(route "/api") -> @route("/api")
            decorator_list.append(compile_expr(dec))
        else:
            raise SyntaxError(f"Invalid decorator expression: {dec!r}")

    if is_async:
        func = ast.AsyncFunctionDef(
            name=normalize_name(name_sym.name),
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )
    else:
        func = ast.FunctionDef(
            name=normalize_name(name_sym.name),
            args=args_node,
            body=body_nodes,
            decorator_list=decorator_list,
            returns=return_type_node,
        )

    # Set source location on the function definition
    if form_loc:
        set_location(func, form_loc)
    else:
        copy_location(func, name_sym)

    # Inject any nested function definitions at the start of the function body
    # but AFTER the docstring if present
    nested_funcs = get_compile_context().get_and_clear_functions()
    if docstring_node:
        # Docstring must be first, then nested functions, then rest of body
        func.body = [docstring_node] + nested_funcs + func.body
    elif nested_funcs:
        func.body = nested_funcs + func.body

    return func


def compile_params(items):
    """
    Compile function parameters with support for defaults, keyword-only args,
    kwargs, and type annotations.

    Syntax:
    - [x (y 1)]       -> def f(x, y=1):
    - [x & rest]      -> def f(x, *rest):
    - [x # y]         -> def f(x, *, y):
    - [x # (y 1)]     -> def f(x, *, y=1):
    - [x ** k]        -> def f(x, **k):
    - [x & rest ** k] -> def f(x, *rest, **k):
    - [x # y ** k]    -> def f(x, *, y, **k):

    Type annotations (Phase 3):
    - [^int x]        -> def f(x: int):
    - [^int x ^str y] -> def f(x: int, y: str):
    - [^(List int) items] -> def f(items: List[int]):

    Returns: (ast.arguments, List[ast.stmt])
    """
    # Lists for ast.arguments
    pos_args: list[ast.arg] = []
    pos_defaults: list[ast.expr] = []

    vararg: Optional[ast.arg] = None

    kwonly_args: list[ast.arg] = []
    kw_defaults: list[Optional[ast.expr]] = []

    kwarg: Optional[ast.arg] = None

    # Side effects (destructuring assignments)
    destructure_stmts: list[ast.stmt] = []

    # State machine: "pos", "rest", "kw", "kwargs"
    state = "pos"

    # Track pending type annotation from ^type syntax
    pending_type_annotation = None

    i = 0
    while i < len(items):
        item = items[i]

        # 0. Check for type annotation (^type before parameter)
        if isinstance(item, Decorated):
            # This is a type annotation like ^int or ^(List int)
            pending_type_annotation = compile_type_annotation(item.expr)
            i += 1
            continue

        # 1. Handle Markers

        # Check for Kwargs (**)
        if is_symbol(item, "**"):
            if state == "kwargs":
                raise SyntaxError("** can only appear once")
            state = "kwargs"

            # The next item must be the kwarg name
            if i + 1 >= len(items):
                raise SyntaxError("** must be followed by a name")

            kwarg_item = items[i + 1]
            i += 2  # Skip ** and name

            # Use pending type annotation if available
            kwarg_annotation = pending_type_annotation
            pending_type_annotation = None

            if isinstance(kwarg_item, Symbol):
                kwarg = ast.arg(
                    arg=normalize_name(kwarg_item.name), annotation=kwarg_annotation
                )
            else:
                # Destructuring pattern for kwargs
                temp = gensym("__kwarg_")
                kwarg = ast.arg(arg=temp, annotation=None)
                temp_load = ast.Name(id=temp, ctx=ast.Load())
                destructure_stmts.extend(compile_destructure(kwarg_item, temp_load))
            continue

        # Check for Varargs (&)
        if is_symbol(item, "&"):
            if state not in ("pos",):
                raise SyntaxError(
                    "& (rest) must come before # (keyword args) and ** (kwargs)"
                )
            state = "rest"

            # The next item must be the vararg name
            if i + 1 >= len(items):
                raise SyntaxError("& must be followed by a name")

            vararg_item = items[i + 1]
            i += 2  # Skip & and name

            # Use pending type annotation if available
            vararg_annotation = pending_type_annotation
            pending_type_annotation = None

            # Handle destructuring in vararg: (defn f [& [x y]])
            if isinstance(vararg_item, Symbol):
                vararg = ast.arg(
                    arg=normalize_name(vararg_item.name), annotation=vararg_annotation
                )
            else:
                # E.g. (defn f [& [first & rest]])
                temp = gensym("__vararg_")
                vararg = ast.arg(arg=temp, annotation=None)
                temp_load = ast.Name(id=temp, ctx=ast.Load())
                destructure_stmts.extend(compile_destructure(vararg_item, temp_load))
            continue

        # Check for Keyword Marker (#)
        if is_symbol(item, "#"):
            if state == "kwargs":
                raise SyntaxError("# (keyword args) must come before ** (kwargs)")
            state = "kw"
            i += 1
            continue

        # 2. Extract Name and Default Value
        # Format can be `name` or `(name default_value)`
        param_item = item
        default_val_expr = None
        has_default = False

        # In Spork reader, (x 1) is a list. [x 1] is a Vector.
        # We use list () for defaults to distinguish from destructuring []
        if isinstance(item, list):
            if len(item) != 2:
                raise SyntaxError(f"Parameter default must be (name value), got {item}")
            param_item = item[0]
            default_val_expr = compile_expr(item[1])
            has_default = True

        # 3. Handle Destructuring vs Simple Symbol
        py_arg = None

        # Use pending type annotation if available
        param_annotation = pending_type_annotation
        pending_type_annotation = None

        if isinstance(param_item, Symbol):
            py_arg = ast.arg(
                arg=normalize_name(param_item.name), annotation=param_annotation
            )
        elif is_destructuring_pattern(param_item):
            # Generate temp param name for Python signature
            temp = gensym("__param_")
            py_arg = ast.arg(arg=temp, annotation=param_annotation)

            # Create destructuring logic for body
            temp_load = ast.Name(id=temp, ctx=ast.Load())
            destructure_stmts.extend(compile_destructure(param_item, temp_load))
        else:
            raise SyntaxError(f"Invalid parameter format: {param_item}")

        # 4. Add to AST based on state
        if state == "pos":
            pos_args.append(py_arg)
            if has_default and default_val_expr is not None:
                pos_defaults.append(default_val_expr)
            elif pos_defaults:
                # In Python positional args, you can't have a non-default after a default
                raise SyntaxError("Non-default argument follows default argument")

        elif state == "rest":
            raise SyntaxError("Only one variable allowed after &")

        elif state == "kw":
            kwonly_args.append(py_arg)
            # In Python, kwonly args can be required (default=None) or optional
            kw_defaults.append(default_val_expr)

        elif state == "kwargs":
            raise SyntaxError("No parameters allowed after ** kwargs")

        i += 1

    args_node = ast.arguments(
        posonlyargs=[],
        args=pos_args,
        vararg=vararg,
        kwonlyargs=kwonly_args,
        kw_defaults=kw_defaults,
        kwarg=kwarg,
        defaults=pos_defaults,
    )

    return args_node, destructure_stmts


def compile_destructure(pattern, value_expr, form_loc=None):
    """
    Compile destructuring assignment.

    pattern: Symbol, Vector, or dict representing the destructuring pattern
    value_expr: ast.expr representing the value being destructured
    form_loc: Optional source location for the generated statements

    Returns: List of ast.stmt (assignment statements)

    Supports:
    - Simple binding: symbol -> single assignment
    - Vector destructuring: [a b c] -> sequential element access
    - Vector with rest: [a b & rest] -> first N elements + rest
    - Dict with :keys: {:keys [x y]} -> extract named keys
    - Dict with key-value: {a :x b :y} -> bind 'a' to map[:x], 'b' to map[:y]
    - Nested patterns: [[a b] c] -> recursive destructuring
    """
    # Get location from pattern if form_loc not provided
    loc = form_loc or get_source_location(pattern)

    if isinstance(pattern, Symbol):
        # Simple binding
        target = ast.Name(id=normalize_name(pattern.name), ctx=ast.Store())
        copy_location(target, pattern)
        stmt = ast.Assign(targets=[target], value=value_expr)
        set_location(stmt, loc)
        return [stmt]

    if isinstance(pattern, VectorLiteral):
        # Sequence destructuring: [a b c] or [a b & rest]
        stmts = []
        items = pattern.items

        if not items:
            # Empty pattern, just evaluate the expression for side effects
            stmt = ast.Expr(value=value_expr)
            set_location(stmt, loc)
            return [stmt]

        # Check for & rest
        rest_idx = -1
        for i, item in enumerate(items):
            if isinstance(item, Symbol) and item.name == "&":
                rest_idx = i
                break
        has_rest = rest_idx >= 0

        # Use a temp var for the value to avoid re-evaluation
        temp = gensym("__destructure_")
        temp_name = ast.Name(id=temp, ctx=ast.Store())
        assign_stmt = ast.Assign(targets=[temp_name], value=value_expr)
        set_location(assign_stmt, loc)
        stmts.append(assign_stmt)
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        if has_rest:
            # Generate: first N bindings from value[:N], rest binding from value[N:]
            pre_rest = items[:rest_idx]
            if rest_idx + 1 >= len(items):
                raise SyntaxError("& must be followed by a binding pattern")
            rest_pattern = items[rest_idx + 1]

            # Bind pre-rest elements using nth for persistent structure support
            for i, sub_pattern in enumerate(pre_rest):
                elem = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(compile_destructure(sub_pattern, elem, loc))

            # Bind rest using drop for persistent structure support
            # Note: drop signature is (drop n coll), and we realize it with vec
            # to get a persistent vector instead of a lazy generator
            drop_call = ast.Call(
                func=ast.Name(id="drop", ctx=ast.Load()),
                args=[ast.Constant(value=len(pre_rest)), temp_load],
                keywords=[],
            )
            rest_val = ast.Call(
                func=ast.Name(id="vec", ctx=ast.Load()),
                args=[drop_call],
                keywords=[],
            )
            stmts.extend(compile_destructure(rest_pattern, rest_val, loc))
        else:
            # Simple sequence destructuring using nth
            for i, sub_pattern in enumerate(items):
                elem = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(compile_destructure(sub_pattern, elem, loc))

        return stmts

    if isinstance(pattern, MapLiteral):
        # Dict destructuring with Clojure-style syntax
        # MapLiteral preserves the original key-value pairs
        stmts = []

        if not pattern.pairs:
            # Empty pattern, just evaluate the expression for side effects
            stmt = ast.Expr(value=value_expr)
            set_location(stmt, loc)
            return [stmt]

        # Use a temp var for the value to avoid re-evaluation
        temp = gensym("__destructure_")
        temp_name = ast.Name(id=temp, ctx=ast.Store())
        assign_stmt = ast.Assign(targets=[temp_name], value=value_expr)
        set_location(assign_stmt, loc)
        stmts.append(assign_stmt)
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        # Check for :keys syntax: {:keys [x y]} means bind x to map["x"], y to map["y"]
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys":
                # :keys [x y z] syntax - look up by keyword
                if isinstance(value, VectorLiteral):
                    for sym in value.items:
                        if not isinstance(sym, Symbol):
                            raise SyntaxError(":keys must contain symbols")
                        # Create Keyword object for lookup
                        key_expr = ast.Call(
                            func=ast.Name(id="Keyword", ctx=ast.Load()),
                            args=[ast.Constant(value=sym.name)],
                            keywords=[],
                        )
                        elem = ast.Call(
                            func=ast.Name(id="get", ctx=ast.Load()),
                            args=[temp_load, key_expr],
                            keywords=[],
                        )
                        stmts.extend(compile_destructure(sym, elem, loc))
                else:
                    raise SyntaxError(":keys value must be a vector of symbols")
            elif isinstance(key, Symbol):
                # Clojure-style: {a :x b :y} means bind 'a' to value at key :x
                # key is the binding pattern, value is the lookup key
                if isinstance(value, Keyword):
                    # Create Keyword object for lookup
                    lookup_expr = ast.Call(
                        func=ast.Name(id="Keyword", ctx=ast.Load()),
                        args=[ast.Constant(value=value.name)],
                        keywords=[],
                    )
                elif isinstance(value, str):
                    lookup_expr = ast.Constant(value=value)
                else:
                    raise SyntaxError(
                        f"Dict destructuring key must be a keyword or string, got {type(value)}"
                    )
                elem = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, lookup_expr],
                    keywords=[],
                )
                stmts.extend(compile_destructure(key, elem, loc))
            else:
                raise SyntaxError(
                    f"Invalid dict destructuring pattern: {key!r} -> {value!r}"
                )

        return stmts

    raise SyntaxError(f"Invalid destructuring pattern: {pattern!r}")


def is_destructuring_pattern(form):
    """Check if a form is a destructuring pattern (VectorLiteral or MapLiteral, not Symbol)."""
    return isinstance(form, (VectorLiteral, MapLiteral))


def make_keyword_expr(name: str) -> ast.Call:
    """Create an AST expression that constructs a Keyword object."""
    return ast.Call(
        func=ast.Name(id="Keyword", ctx=ast.Load()),
        args=[ast.Constant(value=name)],
        keywords=[],
    )


# === Pattern Matching ===


def is_wildcard_pattern(pattern):
    """Check if pattern is the wildcard _."""
    return isinstance(pattern, Symbol) and pattern.name == "_"


def is_literal_pattern(pattern):
    """Check if pattern is a literal (nil, true, false, number, string, keyword)."""
    if pattern is None:
        return True
    if isinstance(pattern, bool):
        return True
    if isinstance(pattern, (int, float, str)):
        return True
    if isinstance(pattern, Keyword):
        return True
    if isinstance(pattern, Symbol) and pattern.name in ("nil", "true", "false"):
        return True
    return False


def is_type_pattern(pattern):
    """
    Check if pattern is a type pattern: (^Type pat) or (^Type pat :when guard).
    A type pattern is a list where the first element is a Decorated form.
    """
    if not isinstance(pattern, list) or len(pattern) < 1:
        return False
    first = pattern[0]
    return isinstance(first, Decorated)


def is_guarded_pattern(pattern):
    """
    Check if pattern has a guard: (pat :when guard-expr).
    Returns True if the pattern is a list with :when as second-to-last element.
    """
    if not isinstance(pattern, list) or len(pattern) < 3:
        return False
    # Check for :when keyword
    for item in pattern:
        if isinstance(item, Keyword) and item.name == "when":
            return True
    return False


def parse_guarded_pattern(pattern):
    """
    Parse a guarded pattern (pat :when guard-expr).
    Returns (inner_pattern, guard_expr).
    If not guarded, returns (pattern, None).
    """
    if not isinstance(pattern, list) or len(pattern) < 3:
        return pattern, None

    # Look for :when keyword
    for i, item in enumerate(pattern):
        if isinstance(item, Keyword) and item.name == "when":
            if i + 1 >= len(pattern):
                raise SyntaxError(":when must be followed by a guard expression")
            # Everything before :when is the pattern, after is the guard
            if i == 1:
                inner_pattern = pattern[0]
            else:
                inner_pattern = pattern[:i]
            guard_expr = pattern[i + 1]
            return inner_pattern, guard_expr

    return pattern, None


def parse_type_pattern(pattern):
    """
    Parse a type pattern (^Type pat) or (^Type pat :when guard).
    Returns (type_expr, inner_pattern, guard_expr).
    """
    if not isinstance(pattern, list) or len(pattern) < 1:
        raise SyntaxError(f"Invalid type pattern: {pattern}")

    first = pattern[0]
    if not isinstance(first, Decorated):
        raise SyntaxError(f"Type pattern must start with ^Type, got {first}")

    type_expr = first.expr

    # Rest of pattern after the type
    if len(pattern) == 1:
        # (^Type) alone - just type check, bind nothing (implicit wildcard)
        return type_expr, Symbol("_"), None
    elif len(pattern) == 2:
        # (^Type pat)
        return type_expr, pattern[1], None
    else:
        # (^Type pat :when guard) or (^Type pat1 pat2 ...)
        # Check for :when
        for i, item in enumerate(pattern[1:], start=1):
            if isinstance(item, Keyword) and item.name == "when":
                if i + 1 >= len(pattern):
                    raise SyntaxError(":when must be followed by a guard expression")
                inner_pattern = pattern[1] if i == 2 else pattern[1:i]
                guard_expr = pattern[i + 1]
                return type_expr, inner_pattern, guard_expr
        # No guard, pattern is everything after type
        if len(pattern) == 2:
            return type_expr, pattern[1], None
        else:
            return type_expr, pattern[1], None


def compile_pattern_check(
    pattern, value_expr, ok_var, bindings_list, type_annotation=None
):
    """
    Compile pattern matching checks and bindings.

    Args:
        pattern: The pattern to match
        value_expr: AST expression for the value being matched
        ok_var: Name of the boolean flag variable (e.g., "__match_ok__")
        bindings_list: List to append (name, value_expr, type_annotation) tuples for bindings
        type_annotation: Optional compiled type AST to attach to symbol bindings

    Returns:
        List of AST statements that:
        1. Check if pattern matches (setting ok_var to False if not)
        2. Bind variables if pattern matches (with type annotations when present)
    """
    stmts = []
    loc = get_source_location(pattern)

    # Wildcard: always matches, binds nothing
    if is_wildcard_pattern(pattern):
        return stmts

    # Literal patterns: match by value equality
    if is_literal_pattern(pattern):
        # Convert pattern to its Python value
        if pattern is None:
            literal_val = ast.Constant(value=None)
        elif isinstance(pattern, bool):
            literal_val = ast.Constant(value=pattern)
        elif isinstance(pattern, Symbol):
            if pattern.name == "nil":
                literal_val = ast.Constant(value=None)
            elif pattern.name == "true":
                literal_val = ast.Constant(value=True)
            elif pattern.name == "false":
                literal_val = ast.Constant(value=False)
            else:
                raise SyntaxError(f"Unknown literal symbol: {pattern.name}")
        elif isinstance(pattern, Keyword):
            literal_val = make_keyword_expr(pattern.name)
        else:
            literal_val = ast.Constant(value=pattern)

        # if ok_var and value != literal: ok_var = False
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.Compare(
                        left=value_expr,
                        ops=[ast.NotEq()],
                        comparators=[literal_val],
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)
        return stmts

    # Symbol pattern: bind the value (with type annotation if present)
    if isinstance(pattern, Symbol):
        bindings_list.append((pattern.name, value_expr, type_annotation))
        return stmts

    # Type pattern: (^Type pat)
    if is_type_pattern(pattern):
        type_expr, inner_pattern, guard = parse_type_pattern(pattern)

        # Compile the type expression
        type_ast = compile_expr(type_expr)

        # if ok_var and not isinstance(value, type): ok_var = False
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.UnaryOp(
                        op=ast.Not(),
                        operand=ast.Call(
                            func=ast.Name(id="isinstance", ctx=ast.Load()),
                            args=[value_expr, type_ast],
                            keywords=[],
                        ),
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)

        # Recursively match inner pattern against the same value
        # Pass the type annotation from this type pattern to inner bindings
        inner_type_annotation = compile_type_annotation(type_expr)
        stmts.extend(
            compile_pattern_check(
                inner_pattern, value_expr, ok_var, bindings_list, inner_type_annotation
            )
        )

        # Handle guard if present (for type patterns with inline guards)
        if guard is not None:
            # The guard will be handled at the outer level
            pass

        return stmts

    # VectorLiteral pattern: [p1 p2 ... pn] or [p1 p2 ... pk & rest]
    if isinstance(pattern, VectorLiteral):
        items = pattern.items
        if not items:
            # Empty vector: check length == 0
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            value_expr,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[value_expr],
                                            keywords=[],
                                        ),
                                        ops=[ast.Eq()],
                                        comparators=[ast.Constant(value=0)],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)
            return stmts

        # Check for & rest
        rest_idx = -1
        for i, item in enumerate(items):
            if isinstance(item, Symbol) and item.name == "&":
                rest_idx = i
                break
        has_rest = rest_idx >= 0

        # Create a temp variable to hold the value
        temp = gensym("__match_seq_")
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id=temp, ctx=ast.Store())],
                value=value_expr,
            )
        )
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        if has_rest:
            # [p1 p2 ... pk & rest]: check len >= k
            pre_rest_count = rest_idx
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            temp_load,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[temp_load],
                                            keywords=[],
                                        ),
                                        ops=[ast.GtE()],
                                        comparators=[
                                            ast.Constant(value=pre_rest_count)
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)

            # Match pre-rest patterns
            for i in range(pre_rest_count):
                elem_expr = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(items[i], elem_expr, ok_var, bindings_list)
                )

            # Match rest pattern
            if rest_idx + 1 < len(items):
                rest_pattern = items[rest_idx + 1]
                # Note: drop signature is (drop n coll), realize with vec
                drop_call = ast.Call(
                    func=ast.Name(id="drop", ctx=ast.Load()),
                    args=[ast.Constant(value=pre_rest_count), temp_load],
                    keywords=[],
                )
                rest_expr = ast.Call(
                    func=ast.Name(id="vec", ctx=ast.Load()),
                    args=[drop_call],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(
                        rest_pattern, rest_expr, ok_var, bindings_list
                    )
                )
        else:
            # [p1 p2 ... pn]: check len == n
            n = len(items)
            check = ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.Name(id=ok_var, ctx=ast.Load()),
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Call(
                                        func=ast.Name(id="hasattr", ctx=ast.Load()),
                                        args=[
                                            temp_load,
                                            ast.Constant(value="__iter__"),
                                        ],
                                        keywords=[],
                                    ),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="len", ctx=ast.Load()),
                                            args=[temp_load],
                                            keywords=[],
                                        ),
                                        ops=[ast.Eq()],
                                        comparators=[ast.Constant(value=n)],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                ],
                orelse=[],
            )
            set_location(check, loc)
            stmts.append(check)

            # Match each sub-pattern
            for i, sub_pattern in enumerate(items):
                elem_expr = ast.Call(
                    func=ast.Name(id="nth", ctx=ast.Load()),
                    args=[temp_load, ast.Constant(value=i)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(sub_pattern, elem_expr, ok_var, bindings_list)
                )

        return stmts

    # Map pattern: {:keys [k1 k2]} or {local :key}
    if isinstance(pattern, MapLiteral):
        # Create a temp variable to hold the value
        temp = gensym("__match_map_")
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id=temp, ctx=ast.Store())],
                value=value_expr,
            )
        )
        temp_load = ast.Name(id=temp, ctx=ast.Load())

        # Check that value is map-like (has __getitem__ or is dict/Map)
        check = ast.If(
            test=ast.BoolOp(
                op=ast.And(),
                values=[
                    ast.Name(id=ok_var, ctx=ast.Load()),
                    ast.UnaryOp(
                        op=ast.Not(),
                        operand=ast.Call(
                            func=ast.Name(id="hasattr", ctx=ast.Load()),
                            args=[temp_load, ast.Constant(value="__getitem__")],
                            keywords=[],
                        ),
                    ),
                ],
            ),
            body=[
                ast.Assign(
                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                    value=ast.Constant(value=False),
                )
            ],
            orelse=[],
        )
        set_location(check, loc)
        stmts.append(check)

        # Process each key-value pair in the pattern
        for key, value in pattern.pairs:
            if isinstance(key, Keyword) and key.name == "keys":
                # :keys [k1 k2 k3] syntax - look up by Keyword objects
                if isinstance(value, VectorLiteral):
                    for sym in value.items:
                        if not isinstance(sym, Symbol):
                            raise SyntaxError(":keys must contain symbols")
                        key_expr = make_keyword_expr(sym.name)
                        # Check key exists
                        key_check = ast.If(
                            test=ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.Name(id=ok_var, ctx=ast.Load()),
                                    ast.Compare(
                                        left=ast.Call(
                                            func=ast.Name(id="get", ctx=ast.Load()),
                                            args=[
                                                temp_load,
                                                key_expr,
                                                ast.Name(id="_MISSING", ctx=ast.Load()),
                                            ],
                                            keywords=[],
                                        ),
                                        ops=[ast.Is()],
                                        comparators=[
                                            ast.Name(id="_MISSING", ctx=ast.Load())
                                        ],
                                    ),
                                ],
                            ),
                            body=[
                                ast.Assign(
                                    targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                                    value=ast.Constant(value=False),
                                )
                            ],
                            orelse=[],
                        )
                        set_location(key_check, loc)
                        stmts.append(key_check)
                        # Bind the value
                        bindings_list.append(
                            (
                                sym.name,
                                ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[temp_load, make_keyword_expr(sym.name)],
                                    keywords=[],
                                ),
                            )
                        )
                else:
                    raise SyntaxError(":keys value must be a vector of symbols")
            elif isinstance(key, Symbol):
                # Clojure-style: {a :x} means bind 'a' to value at key :x
                if isinstance(value, Keyword):
                    lookup_expr = make_keyword_expr(value.name)
                elif isinstance(value, str):
                    lookup_expr = ast.Constant(value=value)
                else:
                    raise SyntaxError(
                        f"Map pattern key must be a keyword or string, got {type(value)}"
                    )
                # Check key exists
                key_check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.Compare(
                                left=ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[
                                        temp_load,
                                        lookup_expr,
                                        ast.Name(id="_MISSING", ctx=ast.Load()),
                                    ],
                                    keywords=[],
                                ),
                                ops=[ast.Is()],
                                comparators=[ast.Name(id="_MISSING", ctx=ast.Load())],
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                set_location(key_check, loc)
                stmts.append(key_check)
                # Bind or match the value pattern
                if isinstance(value, Keyword):
                    lookup_expr2 = make_keyword_expr(value.name)
                elif isinstance(value, str):
                    lookup_expr2 = ast.Constant(value=value)
                else:
                    lookup_expr2 = lookup_expr
                elem_expr = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, lookup_expr2],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(key, elem_expr, ok_var, bindings_list)
                )
            elif isinstance(key, Keyword):
                # Reverse syntax: {:x a} means bind 'a' to value at key :x
                lookup_expr = make_keyword_expr(key.name)
                # Check key exists
                key_check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Name(id=ok_var, ctx=ast.Load()),
                            ast.Compare(
                                left=ast.Call(
                                    func=ast.Name(id="get", ctx=ast.Load()),
                                    args=[
                                        temp_load,
                                        lookup_expr,
                                        ast.Name(id="_MISSING", ctx=ast.Load()),
                                    ],
                                    keywords=[],
                                ),
                                ops=[ast.Is()],
                                comparators=[ast.Name(id="_MISSING", ctx=ast.Load())],
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
                            value=ast.Constant(value=False),
                        )
                    ],
                    orelse=[],
                )
                set_location(key_check, loc)
                stmts.append(key_check)
                # Bind or match the value pattern
                elem_expr = ast.Call(
                    func=ast.Name(id="get", ctx=ast.Load()),
                    args=[temp_load, make_keyword_expr(key.name)],
                    keywords=[],
                )
                stmts.extend(
                    compile_pattern_check(value, elem_expr, ok_var, bindings_list)
                )
            else:
                raise SyntaxError(f"Invalid map pattern key: {key!r}")

        return stmts

    # Guarded pattern at top level: (pat :when guard)
    if is_guarded_pattern(pattern):
        inner_pattern, guard = parse_guarded_pattern(pattern)
        # Just match the inner pattern; guard is handled by caller
        stmts.extend(
            compile_pattern_check(inner_pattern, value_expr, ok_var, bindings_list)
        )
        return stmts

    raise SyntaxError(f"Invalid pattern: {pattern!r}")


def compile_match_case(pattern, result_expr, target_var, result_var, matched_var):
    """
    Compile a single match case.

    Returns a list of AST statements that:
    1. Check if pattern matches target_var
    2. If match succeeds (and guard passes), evaluate result_expr and set result_var, matched_var
    """
    stmts = []
    ok_var = gensym("__match_ok_")
    bindings_list = []

    # Parse guard if present
    inner_pattern, guard_expr = parse_guarded_pattern(pattern)

    # Initialize match ok flag
    stmts.append(
        ast.Assign(
            targets=[ast.Name(id=ok_var, ctx=ast.Store())],
            value=ast.Constant(value=True),
        )
    )

    # Compile pattern checks
    target_load = ast.Name(id=target_var, ctx=ast.Load())
    stmts.extend(
        compile_pattern_check(inner_pattern, target_load, ok_var, bindings_list)
    )

    # Build the body that runs when pattern matches
    match_body = []

    # Add bindings - handle both 2-tuple and 3-tuple formats
    for binding in bindings_list:
        if len(binding) == 3:
            name, val_expr, type_annotation = binding
        else:
            # Backward compatibility with 2-tuple format
            name, val_expr = binding
            type_annotation = None

        if type_annotation is not None:
            # Emit annotated assignment: x: int = value
            match_body.append(
                ast.AnnAssign(
                    target=ast.Name(id=normalize_name(name), ctx=ast.Store()),
                    annotation=type_annotation,
                    value=val_expr,
                    simple=1,
                )
            )
        else:
            match_body.append(
                ast.Assign(
                    targets=[ast.Name(id=normalize_name(name), ctx=ast.Store())],
                    value=val_expr,
                )
            )

    # Save nested functions count before compiling result/guard
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)

    # Compile guard check and result
    if guard_expr is not None:
        # if guard_expr: result_var = result_expr; matched_var = True
        guard_compiled = compile_expr(guard_expr)
        result_compiled = compile_expr(result_expr)

        # Extract nested functions generated during compilation
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

        # Add nested function definitions before the guard check
        match_body.extend(nested_funcs)

        guard_if = ast.If(
            test=guard_compiled,
            body=[
                ast.Assign(
                    targets=[ast.Name(id=result_var, ctx=ast.Store())],
                    value=result_compiled,
                ),
                ast.Assign(
                    targets=[ast.Name(id=matched_var, ctx=ast.Store())],
                    value=ast.Constant(value=True),
                ),
            ],
            orelse=[],
        )
        match_body.append(guard_if)
    else:
        # No guard: result_var = result_expr; matched_var = True
        result_compiled = compile_expr(result_expr)

        # Extract nested functions generated during compilation
        nested_funcs = ctx.nested_functions[saved_funcs_count:]
        ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

        # Add nested function definitions before the result assignment
        match_body.extend(nested_funcs)

        match_body.append(
            ast.Assign(
                targets=[ast.Name(id=result_var, ctx=ast.Store())],
                value=result_compiled,
            )
        )
        match_body.append(
            ast.Assign(
                targets=[ast.Name(id=matched_var, ctx=ast.Store())],
                value=ast.Constant(value=True),
            )
        )

    # Wrap in: if not matched_var: if ok_var: <match_body>
    inner_if = ast.If(
        test=ast.Name(id=ok_var, ctx=ast.Load()),
        body=match_body if match_body else [ast.Pass()],
        orelse=[],
    )

    outer_if = ast.If(
        test=ast.UnaryOp(
            op=ast.Not(),
            operand=ast.Name(id=matched_var, ctx=ast.Load()),
        ),
        body=stmts + [inner_if],
        orelse=[],
    )

    return [outer_if]


def compile_match_expr(args, form_loc=None):
    """
    Compile (match expr pattern1 result1 pattern2 result2 ...).

    Returns an AST expression using IIFE pattern.
    """
    if len(args) < 1:
        raise SyntaxError("match requires at least an expression")
    if len(args) < 3:
        raise SyntaxError("match requires at least one pattern-result pair")
    if (len(args) - 1) % 2 != 0:
        raise SyntaxError("match requires pairs of patterns and results")

    target_expr = args[0]
    cases = []
    for i in range(1, len(args), 2):
        pattern = args[i]
        result = args[i + 1]
        cases.append((pattern, result))

    # Generate variable names
    target_var = gensym("__match_target_")
    result_var = gensym("__match_result_")
    matched_var = gensym("__match_matched_")
    fn_name = gensym("__match_fn_")

    # Build function body
    body_stmts = []

    # target_var = expr
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=target_var, ctx=ast.Store())],
            value=compile_expr(target_expr),
        )
    )

    # matched_var = False
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=matched_var, ctx=ast.Store())],
            value=ast.Constant(value=False),
        )
    )

    # result_var = None (placeholder)
    body_stmts.append(
        ast.Assign(
            targets=[ast.Name(id=result_var, ctx=ast.Store())],
            value=ast.Constant(value=None),
        )
    )

    # Compile each case
    for pattern, result in cases:
        case_stmts = compile_match_case(
            pattern, result, target_var, result_var, matched_var
        )
        body_stmts.extend(case_stmts)

    # if not matched_var: raise MatchError(...)
    body_stmts.append(
        ast.If(
            test=ast.UnaryOp(
                op=ast.Not(),
                operand=ast.Name(id=matched_var, ctx=ast.Load()),
            ),
            body=[
                ast.Raise(
                    exc=ast.Call(
                        func=ast.Name(id="MatchError", ctx=ast.Load()),
                        args=[
                            ast.Constant(value="No pattern matched in match expression")
                        ],
                        keywords=[],
                    ),
                    cause=None,
                )
            ],
            orelse=[],
        )
    )

    # return result_var
    body_stmts.append(ast.Return(value=ast.Name(id=result_var, ctx=ast.Load())))

    # Create the wrapper function
    fn_def = ast.FunctionDef(
        name=fn_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=body_stmts,
        decorator_list=[],
    )

    # Register the function
    get_compile_context().add_function(fn_def)

    # Return call to the function
    return ast.Call(
        func=ast.Name(id=fn_name, ctx=ast.Load()),
        args=[],
        keywords=[],
    )


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
    # Default: compile as expression statement
    node = ast.Expr(value=compile_expr(form))
    set_location(node, form_loc)
    return node


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
            elif head_name in ("while", "for", "set!"):
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
        elif head_name in ("while", "for", "set!"):
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
            elif head_name in ("while", "for", "async-for", "set!"):
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
            elif head_name in ("while", "for", "async-for", "set!"):
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
      - If it's a statement-only construct (while/for/set!/throw/return), compile as statement
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
        if head in ("while", "for", "set!", "throw", "return"):
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


# === Loop/Recur for Tail Call Optimization ===


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

    # Inject any nested function definitions (from inner loops) AFTER variable initialization
    # so that nested functions can reference the loop variables
    nested_funcs = get_compile_context().get_and_clear_functions()

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
    """
    Compile (for [x xs] body...) to ast.For.

    Supports destructuring patterns in the loop variable:
    - Simple: (for [x items] ...)
    - Vector destructuring: (for [[a b] pairs] ...)
    - Dict destructuring: (for [{:keys [k v]} items] ...)
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


def compile_vector_comprehension(for_form, body_expr, form):
    """
    Compile [for [x coll] expr] to efficient vector building using transients.

    Always generates an IIFE to ensure proper scoping:
        def _vec_comp():
            _t = EMPTY_VECTOR.transient()
            for x in coll:
                _t.conj_mut(expr)
            return _t.persistent()
        _vec_comp()
    """
    # Parse the for form: (for [var coll] ...) - we ignore extra body forms in for
    if len(for_form) < 2:
        raise SyntaxError("for in vector comprehension requires [var coll]")

    bindings = for_form[1]
    if not isinstance(bindings, VectorLiteral) or len(bindings.items) != 2:
        raise SyntaxError("for binding must be [var coll]")

    var_form = bindings.items[0]
    coll_form = bindings.items[1]

    iter_expr = compile_expr(coll_form)

    # Generate unique names
    func_name = gensym("_vec_comp_")
    transient_name = gensym("_t_")

    # Save the current nested functions state so we can capture any new ones
    ctx = get_compile_context()
    saved_funcs_count = len(ctx.nested_functions)

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

    # Compile body expression INSIDE the loop context (after variable is bound)
    body_compiled = compile_expr(body_expr)

    # Capture any nested functions that were generated during body compilation
    # These need to be defined INSIDE our function, not at module level
    nested_funcs = ctx.nested_functions[saved_funcs_count:]
    ctx.nested_functions = ctx.nested_functions[:saved_funcs_count]

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

    return copy_location(call_expr, form)


def compile_sorted_vector_comprehension(for_form, body_expr, options, form):
    """
    Compile [sorted-for [x coll] expr :key key-fn :reverse bool] to sorted vector building.

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
    # Parse the for form: (sorted-for [var coll] ...)
    if len(for_form) < 2:
        raise SyntaxError("sorted-for in vector comprehension requires [var coll]")

    bindings = for_form[1]
    if not isinstance(bindings, VectorLiteral) or len(bindings.items) != 2:
        raise SyntaxError("sorted-for binding must be [var coll]")

    var_form = bindings.items[0]
    coll_form = bindings.items[1]

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

    return copy_location(call_expr, form)


def compile_async_for(args, form_loc=None):
    """
    Compile (async-for [x xs] body...) to ast.AsyncFor.

    Supports destructuring patterns in the loop variable:
    - Simple: (async-for [x items] ...)
    - Vector destructuring: (async-for [[a b] pairs] ...)
    - Dict destructuring: (async-for [{:keys [k v]} items] ...)
    """
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

        node = ast.AsyncFor(target=target, iter=iter_expr, body=body, orelse=[])
        set_location(node, form_loc)
        return node
    else:
        # Destructuring case: use a temp variable and destructure in body
        temp = gensym("__async_for_item_")
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

        node = ast.AsyncFor(target=target, iter=iter_expr, body=body, orelse=[])
        set_location(node, form_loc)
        return node


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
        # Check if it's a statement-only form (for, while, set!, etc.)
        is_statement_form = False
        if isinstance(form, list) and form and isinstance(form[0], Symbol):
            head_name = form[0].name
            if head_name in ("for", "while", "async-for", "set!"):
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


def compile_multi_arity_fn_expr(arity_forms, is_async=False, is_generator=False):
    """
    Compile a multi-arity anonymous function.

    Example:
        (fn
          ([x] x)
          ([x y] (+ x y)))

    Supports async:
        (fn ^async
          ([x] (await x))
          ([x y] (await (some-async x y))))

    Supports generator:
        (fn ^generator
          ([x] (yield x))
          ([x y] (yield x) (yield y)))
    """
    fn_name = gen_fn_name()

    # Parse all arities
    arities = []
    has_variadic = False
    has_any_kwargs = False

    for arity_form in arity_forms:
        params, body_forms, min_args, has_vararg, has_kwargs = parse_arity(arity_form)
        if has_vararg:
            if has_variadic:
                raise SyntaxError("Only one variadic arity allowed per function")
            has_variadic = True
        if has_kwargs:
            has_any_kwargs = True
        arities.append((params, body_forms, min_args, has_vararg, has_kwargs))

    # Sort arities: fixed arities first (by min_args), variadic last
    fixed_arities = [(p, b, m, v, k) for p, b, m, v, k in arities if not v]
    variadic_arities = [(p, b, m, v, k) for p, b, m, v, k in arities if v]

    # Check for duplicate fixed arities
    fixed_counts = [m for _, _, m, _, _ in fixed_arities]
    if len(fixed_counts) != len(set(fixed_counts)):
        raise SyntaxError("Duplicate arity definitions")

    # Sort fixed arities by arg count
    fixed_arities.sort(key=lambda x: x[2])

    # Build the dispatch function
    args_node = ast.arguments(
        posonlyargs=[],
        args=[],
        vararg=ast.arg(arg="__args__", annotation=None),
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=ast.arg(arg="__kwargs__", annotation=None) if has_any_kwargs else None,
        defaults=[],
    )

    body_nodes = []

    # __n__ = len(__args__)
    body_nodes.append(
        ast.Assign(
            targets=[ast.Name(id="__n__", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="len", ctx=ast.Load()),
                args=[ast.Name(id="__args__", ctx=ast.Load())],
                keywords=[],
            ),
        )
    )

    # Track nested functions created while compiling this fn's body
    before_count = len(get_compile_context().nested_functions)

    # Build if/elif chain for dispatch
    dispatch_cases = []

    for params, body_forms, min_args, _, has_kwargs in fixed_arities:
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=min_args)],
        )
        arity_body = compile_arity_dispatch_body(
            params, body_forms, has_kwargs, is_generator
        )
        dispatch_cases.append((test, arity_body))

    if variadic_arities:
        params, body_forms, min_args, has_vararg, has_kwargs = variadic_arities[0]
        test = ast.Compare(
            left=ast.Name(id="__n__", ctx=ast.Load()),
            ops=[ast.GtE()],
            comparators=[ast.Constant(value=min_args)],
        )
        arity_body = compile_arity_dispatch_body(
            params, body_forms, has_kwargs, is_generator
        )
        dispatch_cases.append((test, arity_body))

    if dispatch_cases:
        error_msg = "fn called with wrong number of arguments"
        else_body = [
            ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="TypeError", ctx=ast.Load()),
                    args=[ast.Constant(value=error_msg)],
                    keywords=[],
                ),
                cause=None,
            )
        ]

        current_else: list[ast.stmt] = list(else_body)
        for test, arity_body in reversed(dispatch_cases):
            current_if = ast.If(
                test=test,
                body=arity_body,
                orelse=current_else,
            )
            current_else = [current_if]

        body_nodes.append(current_else[0])

    # Check for yield without ^generator annotation
    if contains_yield(body_nodes) and not is_generator:
        raise SyntaxError(
            "Anonymous function contains yield but is not marked with ^generator. "
            "Use (fn ^generator [...] ...) for generator functions."
        )

    # Inject only the nested functions created while compiling this fn's body
    ctx = get_compile_context()
    after_count = len(ctx.nested_functions)
    if after_count > before_count:
        # Extract only the functions created during this fn's compilation
        nested_funcs = ctx.nested_functions[before_count:after_count]
        body_nodes = nested_funcs + body_nodes
        # Remove these functions from the context since we've injected them
        ctx.nested_functions = (
            ctx.nested_functions[:before_count] + ctx.nested_functions[after_count:]
        )

    if is_async:
        func_def = ast.AsyncFunctionDef(
            name=fn_name,
            args=args_node,
            body=cast(list[ast.stmt], body_nodes),
            decorator_list=[],
        )
    else:
        func_def = ast.FunctionDef(
            name=fn_name,
            args=args_node,
            body=cast(list[ast.stmt], body_nodes),
            decorator_list=[],
        )

    # Add the function definition to the context to be injected into the enclosing scope
    get_compile_context().add_function(func_def)
    return ast.Name(id=fn_name, ctx=ast.Load())


def compile_fn_expr(args, ctx=None):
    """
    Compile (fn [x y] body...) to a nested function definition.
    This allows statements like set!, for, while, etc. in the function body.
    Supports varargs with & syntax: (fn [x & rest] ...)
    Supports multi-arity: (fn ([x] x) ([x y] (+ x y)))
    Supports async: (fn ^async [x] (await x))
    Supports generator: (fn ^generator [x] (yield x))

    The function is defined in the enclosing scope, which naturally captures
    variables from that scope (closures work like Python's nested functions).
    """
    if len(args) < 1:
        raise SyntaxError("fn requires parameter vector")

    # Check for ^async and ^generator decorators
    is_async = False
    is_generator = False
    i = 0
    while i < len(args) and isinstance(args[i], Decorated):
        dec_expr = args[i].expr
        if isinstance(dec_expr, Symbol) and dec_expr.name == "async":
            is_async = True
        elif isinstance(dec_expr, Symbol) and dec_expr.name == "generator":
            is_generator = True
        i += 1
    args = args[i:]

    if len(args) < 1:
        raise SyntaxError("fn requires parameter vector")

    # Check for multi-arity syntax
    if is_multi_arity(args):
        return compile_multi_arity_fn_expr(args, is_async, is_generator)

    params = args[0]
    if not isinstance(params, VectorLiteral):
        raise SyntaxError("fn parameters must be a vector")

    body_forms = args[1:] or [None]

    # Generate a unique name for this anonymous function
    fn_name = gen_fn_name()

    # Compile parameters (same as defn)
    args_node, destructure_stmts = compile_params(params.items)

    # Compile body (same as defn)
    body_nodes = []

    # Add destructuring statements at the start of the function body
    body_nodes.extend(destructure_stmts)

    # Track nested functions created while compiling this fn's body
    before_count = len(get_compile_context().nested_functions)

    # Compile all but the last form as statements
    for f in body_forms[:-1]:
        stmts = compile_stmt(f)
        body_nodes.extend(flatten_stmts([stmts]))

    # Last form: try to return it as an expression, but handle let/do specially
    last_form = body_forms[-1]

    # Check if it's a let or do that might contain statements
    if isinstance(last_form, list) and last_form and is_symbol(last_form[0]):
        head_name = last_form[0].name

        if head_name == "let":
            let_stmts = compile_let_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([let_stmts]))
        elif head_name == "do":
            do_stmts = compile_do_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([do_stmts]))
        elif head_name == "try":
            try_stmts = compile_try_stmt_with_return(last_form[1:])
            body_nodes.extend(flatten_stmts([try_stmts]))
        elif head_name == "with":
            with_stmt = compile_with_stmt_with_return(last_form[1:])
            body_nodes.append(with_stmt)
        elif head_name in ("while", "for", "async-for", "set!"):
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
            # Only add return None if not a generator
            if not is_generator:
                body_nodes.append(ast.Return(value=ast.Constant(value=None)))
        elif head_name == "return":
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular expression - check if generator
            if is_generator:
                # Generator function - just add the statement, no return
                stmts = compile_stmt(last_form)
                body_nodes.extend(flatten_stmts([stmts]))
            else:
                # Regular function - add return
                body_nodes.append(ast.Return(value=compile_expr(last_form)))
    else:
        # Simple value - check if generator
        if is_generator:
            # Generator function - compile as statement, no return
            stmts = compile_stmt(last_form)
            body_nodes.extend(flatten_stmts([stmts]))
        else:
            # Regular function - return it
            body_nodes.append(ast.Return(value=compile_expr(last_form)))

    if not body_nodes:
        body_nodes.append(ast.Pass())

    # Check for yield without ^generator annotation
    if contains_yield(body_nodes) and not is_generator:
        raise SyntaxError(
            "Anonymous function contains yield but is not marked with ^generator. "
            "Use (fn ^generator [...] ...) for generator functions."
        )

    # Inject only the nested functions created while compiling this fn's body
    ctx = get_compile_context()
    after_count = len(ctx.nested_functions)
    if after_count > before_count:
        # Extract only the functions created during this fn's compilation
        nested_funcs = ctx.nested_functions[before_count:after_count]
        body_nodes = nested_funcs + body_nodes
        # Remove these functions from the context since we've injected them
        ctx.nested_functions = (
            ctx.nested_functions[:before_count] + ctx.nested_functions[after_count:]
        )

    if is_async:
        func_def = ast.AsyncFunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,  # type: ignore
            decorator_list=[],
        )
    else:
        func_def = ast.FunctionDef(
            name=fn_name,
            args=args_node,
            body=body_nodes,  # type: ignore
            decorator_list=[],
        )

    # Add the function definition to the context to be injected into the enclosing scope
    get_compile_context().add_function(func_def)

    # Return a reference to the function name
    return ast.Name(id=fn_name, ctx=ast.Load())


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
    method_expr = ast.Attribute(value=obj_expr, attr=method_form.name, ctx=ast.Load())

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
    for f in regular_args:
        # Check for *{:key value} kwargs literal syntax
        if isinstance(f, KwargsLiteral):
            for key, val in f.pairs:
                if isinstance(key, Keyword):
                    key_name = normalize_name(key.name)
                elif isinstance(key, Symbol):
                    key_name = normalize_name(key.name)
                elif isinstance(key, str):
                    key_name = key
                else:
                    raise SyntaxError(
                        f"Kwargs keys must be keywords, symbols, or strings, got {type(key).__name__}"
                    )
                compiled_keywords.append(
                    ast.keyword(arg=key_name, value=compile_expr(val))
                )
        else:
            compiled_args.append(compile_expr(f))

    # Add the spread argument as *args
    compiled_args.append(ast.Starred(value=compile_expr(spread_arg), ctx=ast.Load()))

    return ast.Call(func=fn_expr, args=compiled_args, keywords=compiled_keywords)


def compile_call_args(forms):
    """Compile function call arguments.

    Keyword arguments use the syntax *{:key value} - a KwargsLiteral that
    splats keyword arguments into the function call.

    Examples:
        (f 1 2 3)                    -> f(1, 2, 3)
        (f 1 *{:name "Alice"})       -> f(1, name="Alice")
        (f :x :y :z)                 -> f(Keyword("x"), Keyword("y"), Keyword("z"))
        (f *{:a 1} x *{:b 2})        -> f(a=1, x, b=2)
    """
    args = []
    keywords = []
    for f in forms:
        # Check for *{:key value} kwargs literal syntax
        if isinstance(f, KwargsLiteral):
            for key, val in f.pairs:
                if isinstance(key, Keyword):
                    key_name = normalize_name(key.name)
                elif isinstance(key, Symbol):
                    key_name = normalize_name(key.name)
                elif isinstance(key, str):
                    key_name = key
                else:
                    raise SyntaxError(
                        f"Kwargs keys must be keywords, symbols, or strings, got {type(key).__name__}"
                    )
                keywords.append(ast.keyword(arg=key_name, value=compile_expr(val)))
        else:
            args.append(compile_expr(f))
    return args, keywords


# === Execution helpers ===


def process_defmacros(forms, macro_env):
    """
    Wrapper that calls macros.process_defmacros with compile_defn and normalize_name.
    """
    return _process_defmacros_base(forms, macro_env, compile_defn, normalize_name)


# === Compilation Entry Points ===


def compile_forms_to_code(src: str, filename: str = "<string>"):
    """
    Process Spork source through all compilation phases.
    Returns (compiled code object, local macro env).
    """
    # Set up compilation context with filename
    ctx = get_compile_context()
    ctx.current_file = filename if filename != "<string>" else None

    # Phase 1: Read
    forms = read_str(src)
    # Process defmacros (creates a local macro environment)
    local_macro_env = dict(MACRO_ENV)
    forms = process_defmacros(forms, local_macro_env)
    # Process import-macros, which may add to local macro env
    forms = process_import_macros(forms, local_macro_env)
    # Phase 2: Macroexpand with local macro environment
    forms = macroexpand_all(forms, local_macro_env)
    # Phase 3 & 4: Analyze & Lower
    mod = compile_module(forms, filename=filename)
    code = compile(mod, filename, "exec")
    return code, local_macro_env


def eval_str(src: str, env: Optional[dict[str, Any]] = None):
    """Execute Spork source string in the given environment."""
    if env is None:
        env = {}
    setup_runtime_env(env)
    code, _ = compile_forms_to_code(src, "<string>")
    exec(code, env, env)
    return env


def exec_file(path: str, env: Optional[dict[str, Any]] = None):
    """Execute a Spork source file."""
    from spork.runtime.ns import (
        init_source_roots,
        register_namespace,
    )

    # Initialize source roots based on the file being executed
    init_source_roots(current_file=path)

    with open(path, encoding="utf-8") as f:
        src = f.read()
    if env is None:
        env = {
            "__name__": "__main__",
            "__file__": path,
        }
    setup_runtime_env(env)

    # Set up compilation context with current file
    ctx = get_compile_context()
    ctx.current_file = path

    code, macro_env = compile_forms_to_code(src, path)
    env["__spork_macros__"] = macro_env
    exec(code, env, env)

    # Register namespace if this file declared one via (ns ...)
    if ctx.current_ns:
        register_namespace(
            name=ctx.current_ns,
            file=os.path.abspath(path),
            env=env,
            macros=macro_env,
            refers=ctx.ns_refers,
            aliases=ctx.ns_aliases,
        )

    return env


def export_file(path: str):
    """Convert a Spork source file to Python and output to stdout."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    # Use compile_forms_to_code but then unparse the module instead of compiling
    forms = read_str(src)
    local_macro_env = dict(MACRO_ENV)
    forms = process_defmacros(forms, local_macro_env)
    forms = process_import_macros(forms, local_macro_env)
    forms = macroexpand_all(forms, local_macro_env)
    mod = compile_module(forms, filename=path)
    # Convert AST to Python source code
    python_code = ast.unparse(mod)
    print(python_code)
