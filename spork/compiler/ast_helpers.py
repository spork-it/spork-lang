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
    """Return whether AST nodes contain ``yield`` or ``yield from``."""
    if not isinstance(nodes, list):
        nodes = [nodes]
    for node in nodes:
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node)):
            return True
    return False
