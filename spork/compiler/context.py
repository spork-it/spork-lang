"""Mutable state scoped to a Spork compilation operation."""

import ast
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class CompilationContext:
    """State shared by lowering operations for one compilation."""

    def __init__(self):
        self.nested_functions: list[ast.FunctionDef] = []
        self.current_ns: Optional[str] = None
        self.current_file: Optional[str] = None
        self.ns_aliases: dict[str, str] = {}
        self.ns_refers: dict[str, str] = {}
        self.require_stmts: list[ast.stmt] = []
        self.scope_stack: list[set] = []
        self.nonlocal_stack: list[set] = []
        self.test_names: set[str] = set()
        self.test_counter: int = 0
        self.aot_imports: bool = False

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
        """Check if a variable is defined in the current scope."""
        if self.scope_stack:
            return name in self.scope_stack[-1]
        return False

    def is_in_any_scope(self, name: str) -> bool:
        """Check if a variable is defined in any enclosing scope."""
        return any(name in scope for scope in self.scope_stack)

    def push_nonlocal_frame(self):
        """Push a nonlocal tracking frame for a wrapper function."""
        self.nonlocal_stack.append(set())

    def pop_nonlocal_frame(self) -> set:
        """Pop and return the current nonlocal frame."""
        if self.nonlocal_stack:
            return self.nonlocal_stack.pop()
        return set()

    def mark_nonlocal(self, name: str):
        """Mark a variable as needing a nonlocal declaration."""
        if self.nonlocal_stack:
            self.nonlocal_stack[-1].add(name)

    def get_nonlocals(self) -> set:
        """Get variables needing nonlocal declarations in the current frame."""
        if self.nonlocal_stack:
            return self.nonlocal_stack[-1]
        return set()


@dataclass
class LoopContext:
    """Loop variables available to ``recur`` lowering."""

    var_names: list[str]


_loop_context_var: ContextVar[Optional[LoopContext]] = ContextVar(
    "_loop_context", default=None
)
_compile_context_var: ContextVar[Optional[CompilationContext]] = ContextVar(
    "_compile_context", default=None
)


def get_loop_context() -> Optional[LoopContext]:
    """Get the current loop context, or ``None`` outside a loop."""
    return _loop_context_var.get()


def set_loop_context(ctx: Optional[LoopContext]) -> Optional[LoopContext]:
    """Set the loop context and return the previous value."""
    previous = _loop_context_var.get()
    _loop_context_var.set(ctx)
    return previous


def get_compile_context() -> CompilationContext:
    """Get the current compilation context, creating one if needed."""
    ctx = _compile_context_var.get()
    if ctx is None:
        ctx = CompilationContext()
        _compile_context_var.set(ctx)
    return ctx


@contextmanager
def compilation_context(*, aot_imports: bool = False):
    """Use an isolated context for one possibly-recursive compilation."""
    ctx = CompilationContext()
    ctx.aot_imports = aot_imports
    token = _compile_context_var.set(ctx)
    try:
        yield ctx
    finally:
        _compile_context_var.reset(token)
