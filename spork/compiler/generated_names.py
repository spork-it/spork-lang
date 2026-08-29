"""Unique names used by generated Python AST."""

_fn_counter = 0
_gensym_counter = 0


def gen_fn_name() -> str:
    """Generate a unique name for an anonymous function."""
    global _fn_counter
    _fn_counter += 1
    return f"_spork_fn_{_fn_counter}"


def gensym(prefix: str = "__spork_") -> str:
    """Generate a unique temporary variable name."""
    global _gensym_counter
    _gensym_counter += 1
    return f"{prefix}{_gensym_counter}"
