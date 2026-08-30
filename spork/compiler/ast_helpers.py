"""Small AST and form helpers shared by lowering modules."""

import ast

from spork.runtime import Keyword


def is_keyword(value, name=None) -> bool:
    if isinstance(value, Keyword):
        return name is None or value.name == name
    return False


def flatten_stmts(stmts):
    """Flatten a list that may contain nested lists of statements."""
    result = []
    for stmt in stmts:
        if isinstance(stmt, list):
            result.extend(flatten_stmts(stmt))
        elif stmt is not None:
            result.append(stmt)
    return result


def contains_yield(nodes) -> bool:
    """Return whether AST nodes yield in the current function scope.

    Yields owned by nested functions do not make the enclosing function a
    generator. This distinction matters for tests and other functions that
    define a local generator helper.
    """

    class YieldFinder(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Yield(self, node: ast.Yield) -> None:
            self.found = True

        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
            self.found = True

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

    if not isinstance(nodes, list):
        nodes = [nodes]
    finder = YieldFinder()
    for node in nodes:
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        finder.visit(node)
        if finder.found:
            return True
    return False
