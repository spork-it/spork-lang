"""Dependency inversion seam for feature-specific lowering modules.

The central dispatcher installs one lowerer implementation. Feature modules call
through this interface instead of importing :mod:`spork.compiler.codegen`, which
keeps the module dependency graph acyclic while preserving recursive lowering.
"""

import ast
from typing import Any, Protocol


class Lowerer(Protocol):
    """Operations feature lowerers may delegate back to the dispatcher."""

    def compile_expr(self, form: Any) -> ast.expr: ...

    def compile_stmt(self, form: Any): ...

    def compile_type_annotation(self, type_expr: Any) -> ast.expr: ...

    def compile_loop_stmt_with_return(self, args: Any): ...

    def compile_try_stmt_with_return(self, args: Any): ...

    def compile_do_expr(self, forms: Any) -> ast.expr: ...

    def compile_symbol_expr(self, symbol: Any) -> ast.expr: ...


_lowerer: Lowerer | None = None


def install_lowerer(lowerer: Lowerer) -> None:
    """Install the process-wide lowering dispatcher."""
    global _lowerer
    _lowerer = lowerer


def _get_lowerer() -> Lowerer:
    if _lowerer is None:
        raise RuntimeError("Spork lowering dispatcher has not been initialized")
    return _lowerer


def compile_expr(form: Any) -> ast.expr:
    return _get_lowerer().compile_expr(form)


def compile_stmt(form: Any):
    return _get_lowerer().compile_stmt(form)


def compile_type_annotation(type_expr: Any) -> ast.expr:
    return _get_lowerer().compile_type_annotation(type_expr)


def compile_loop_stmt_with_return(args: Any):
    return _get_lowerer().compile_loop_stmt_with_return(args)


def compile_try_stmt_with_return(args: Any):
    return _get_lowerer().compile_try_stmt_with_return(args)


def compile_do_expr(forms: Any) -> ast.expr:
    return _get_lowerer().compile_do_expr(forms)


def compile_symbol_expr(symbol: Any) -> ast.expr:
    return _get_lowerer().compile_symbol_expr(symbol)
