"""Lowering for namespace declarations and their import clauses."""

import ast

from spork.compiler.context import get_compile_context
from spork.compiler.reader import set_location
from spork.runtime import Keyword, Symbol, VectorLiteral
from spork.runtime.types import normalize_name


def _lower_python_require(
    req_ns, python_module, alias, refer, namespace, form_loc, ctx
):
    """Lower a requireable Python-backed Spork namespace to imports."""
    stmts: list[ast.stmt] = []
    ns_macros = namespace.macros if namespace else {}

    if alias:
        import_stmt = ast.Import(
            names=[
                ast.alias(
                    name=python_module,
                    asname=normalize_name(alias),
                )
            ]
        )
        set_location(import_stmt, form_loc)
        stmts.append(import_stmt)
        ctx.ns_aliases[alias] = req_ns

    if refer == ":all":
        import_stmt = ast.ImportFrom(
            module=python_module,
            names=[ast.alias(name="*", asname=None)],
            level=0,
        )
        set_location(import_stmt, form_loc)
        stmts.append(import_stmt)
    elif refer:
        names = []
        for sym in refer:
            if sym in ns_macros:
                continue
            ctx.ns_refers[sym] = req_ns
            names.append(ast.alias(name=normalize_name(sym), asname=None))
        if names:
            import_stmt = ast.ImportFrom(
                module=python_module,
                names=names,
                level=0,
            )
            set_location(import_stmt, form_loc)
            stmts.append(import_stmt)

    if not alias and not refer:
        import_stmt = ast.Import(names=[ast.alias(name=python_module, asname=None)])
        set_location(import_stmt, form_loc)
        stmts.append(import_stmt)

    return stmts


def compile_ns(args, form_loc=None):
    """
    Compile (ns name (:require ...) (:import ...)) form.

    Sets up namespace context and generates import statements.

    Syntax:
        (ns my.app.core)
        (ns my.app.core
          (:require
            [std.string :as strings]
            [my.lib.helpers :as helpers :refer [foo bar]])
          (:import
            [numpy :as np]
            [os.path :as osp]
            [collections [defaultdict Counter]]
            [math :refer [sin cos]]))

    :require - For Spork namespaces (loads macros and runtime definitions)
    :import  - For Python modules (runtime imports only)
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
                    resolve_type, resolved_target = resolve_require(
                        req_ns, ctx.current_file
                    )
                except FileNotFoundError as e:
                    raise SyntaxError(str(e)) from e

                if resolve_type == "python":
                    # spork-runtime exposes std.* as Python modules carrying
                    # Spork export and macro metadata.
                    stmts.extend(
                        _lower_python_require(
                            req_ns,
                            resolved_target,
                            alias,
                            refer,
                            get_namespace(req_ns),
                            form_loc,
                            ctx,
                        )
                    )
                    continue

                if resolve_type == "spork":
                    # AOT output is imported by Python without the Spork
                    # namespace registry. Lower project/package dependencies to
                    # normal Python imports so a class has one identity no
                    # matter which compiled module references it.
                    if ctx.aot_imports:
                        python_module = ".".join(
                            normalize_name(segment) for segment in req_ns.split(".")
                        )
                        stmts.extend(
                            _lower_python_require(
                                req_ns,
                                python_module,
                                alias,
                                refer,
                                get_namespace(req_ns),
                                form_loc,
                                ctx,
                            )
                        )
                        continue

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
                            # Get the namespace's macros dict to skip macro symbols
                            # (macros are handled at compile-time by process_ns_macros)
                            ns_macros = {}
                            ns_info_for_macros = get_namespace(req_ns)
                            if ns_info_for_macros:
                                ns_macros = ns_info_for_macros.macros or {}

                            for sym in refer:
                                # Skip macros - they're compile-time only
                                if sym in ns_macros:
                                    continue

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
                    raise AssertionError(
                        ":require resolved a non-Spork target; use :import for Python"
                    )

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
