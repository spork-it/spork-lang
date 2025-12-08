"""
Spork REPL - A comprehensive REPL system with pluggable frontends.

This module provides a generic REPL backend that can be used with multiple
frontends (terminal, nREPL, editor integration, etc.).
"""

import ast
import io
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# Import from compiler
from spork.compiler import (
    MACRO_ENV,
    SourceList,
    exec_file,
    get_compile_context,
    macroexpand_all,
    normalize_name,
    read_str,
)
from spork.compiler.codegen import (
    compile_expr,
    compile_module,
    process_defmacros,
)

# Import from runtime
from spork.runtime import (
    _PROTOCOL_IMPLS,
    _PROTOCOLS,
    Keyword,
    MapLiteral,
    Symbol,
    Vector,
    VectorLiteral,
    setup_runtime_env,
    spork_raise,
    spork_try,
)
from spork.runtime.ns import (
    find_spork_file_for_ns,
    get_namespace,
    init_source_roots,
    register_namespace,
)


class ResultType(Enum):
    """Type of result returned from evaluation."""

    VALUE = "value"
    ERROR = "error"
    INCOMPLETE = "incomplete"
    EMPTY = "empty"


@dataclass
class EvalResult:
    """Result of evaluating code in the REPL."""

    type: ResultType
    value: Any = None
    output: str = ""
    error: Optional[str] = None
    error_type: Optional[str] = None
    traceback: Optional[str] = None

    def is_success(self) -> bool:
        return self.type == ResultType.VALUE or self.type == ResultType.EMPTY

    def is_error(self) -> bool:
        return self.type == ResultType.ERROR

    def is_incomplete(self) -> bool:
        return self.type == ResultType.INCOMPLETE


@dataclass
class ReplState:
    """Maintains the state of a REPL session."""

    env: dict[str, Any] = field(default_factory=dict)
    history: list[tuple[str, EvalResult]] = field(default_factory=list)
    counter: int = 0
    namespace: str = "user"  # Current namespace (default is "user")

    def __post_init__(self):
        """Initialize the environment with standard bindings."""
        # Initialize source roots for the REPL
        init_source_roots(include_cwd=True)

        if not self.env:
            self.env = {
                "__name__": self.namespace,
                "Symbol": Symbol,
                "Keyword": Keyword,
                "Vector": Vector,
                "spork_try": spork_try,
                "spork_raise": spork_raise,
                "__builtins__": __builtins__,
            }
            # Populate with standard library functions
            setup_runtime_env(self.env)

    def add_to_history(self, code: str, result: EvalResult):
        """Add an evaluation to the history."""
        self.history.append((code, result))
        if result.is_success():
            self.counter += 1

    def get_env_value(self, name: str) -> Any:
        """Get a value from the environment."""
        return self.env.get(name)

    def set_env_value(self, name: str, value: Any):
        """Set a value in the environment."""
        self.env[name] = value

    def clear_history(self):
        """Clear evaluation history."""
        self.history.clear()
        self.counter = 0


class ReplBackend:
    """
    Generic REPL backend that handles evaluation logic.

    This backend is frontend-agnostic and can be used with any
    input/output mechanism.
    """

    def __init__(self, state: Optional[ReplState] = None):
        """
        Initialize the REPL backend.

        Args:
            state: Optional ReplState to use. If None, creates a new one.
        """
        self.state = state or ReplState()
        self.buffer = ""
        self.macro_env = MACRO_ENV.copy()
        # Inspector state
        self.inspect_table: dict[int, Any] = {}
        self.next_inspect_handle = 1

    def is_complete(self, code: str) -> bool:
        """
        Check if the given code is syntactically complete.

        Args:
            code: The code to check.

        Returns:
            True if the code is complete, False otherwise.
        """
        if not code.strip():
            return True

        # Count parentheses, brackets, and braces
        paren_count = 0
        bracket_count = 0
        brace_count = 0
        in_string = False
        escape_next = False

        for char in code:
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1
            elif char == "[":
                bracket_count += 1
            elif char == "]":
                bracket_count -= 1
            elif char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1

        return (
            paren_count == 0
            and bracket_count == 0
            and brace_count == 0
            and not in_string
        )

    def eval(self, code: str, capture_output: bool = False) -> EvalResult:
        """
        Evaluate code in the REPL environment.

        Args:
            code: The code to evaluate.
            capture_output: If True, capture stdout/stderr.

        Returns:
            An EvalResult containing the result of evaluation.
        """
        if not code.strip():
            return EvalResult(type=ResultType.EMPTY)

        # Check if code is complete
        if not self.is_complete(code):
            return EvalResult(type=ResultType.INCOMPLETE)

        # Set up output capture if requested
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture: Optional[io.StringIO] = (
            io.StringIO() if capture_output else None
        )
        stderr_capture: Optional[io.StringIO] = (
            io.StringIO() if capture_output else None
        )

        try:
            if capture_output and stdout_capture and stderr_capture:
                sys.stdout = stdout_capture  # type: ignore
                sys.stderr = stderr_capture  # type: ignore

            # Phase 1: Read
            forms = read_str(code)

            if not forms:
                return EvalResult(type=ResultType.EMPTY)

            # Check for (using-ns ...) special form - REPL only
            if len(forms) == 1 and self._is_using_ns_form(forms[0]):
                return self._handle_using_ns(forms[0], capture_output, stdout_capture)

            # Check for (ns ...) form - update REPL namespace after processing
            ns_form_ns_name = None
            if len(forms) >= 1 and self._is_ns_form(forms[0]):
                ns_form_ns_name = self._extract_ns_name(forms[0])

            # Phase 1.5: Process defmacros
            forms = process_defmacros(forms, self.macro_env)

            # Phase 2: Macroexpand
            forms = macroexpand_all(forms)

            # If there's exactly one form, try to evaluate it as an expression
            # But skip statement-only forms like def, defn, defmacro, etc.
            if len(forms) == 1:
                form = forms[0]
                is_statement_form = False

                # Check if it's a statement-only form
                if isinstance(form, list) and len(form) > 0:
                    first = form[0]
                    if isinstance(first, Symbol):
                        statement_forms = {
                            "def",
                            "defn",
                            "defmacro",
                            "defclass",
                            "import",
                            "import-macros",
                            "ns",
                        }
                        if first.name in statement_forms:
                            is_statement_form = True

                if not is_statement_form:
                    try:
                        expr = compile_expr(forms[0])
                        nested = get_compile_context().get_and_clear_functions()

                        # Assign the expression result to a special variable
                        assign = ast.Assign(
                            targets=[ast.Name(id="__repl_result__", ctx=ast.Store())],
                            value=expr,
                        )

                        # Include nested functions before the assignment
                        body_stmts = nested + [assign]
                        mod = ast.Module(body=body_stmts, type_ignores=[])  # type: ignore
                        ast.fix_missing_locations(mod)
                        code_obj = compile(mod, "<repl>", "exec")

                        exec(code_obj, self.state.env, self.state.env)
                        result = self.state.env.get("__repl_result__")

                        output = (
                            stdout_capture.getvalue()
                            if (capture_output and stdout_capture)
                            else ""
                        )
                        return EvalResult(
                            type=ResultType.VALUE, value=result, output=output
                        )

                    except (SyntaxError, TypeError):
                        # If it can't be compiled as an expression, fall through
                        pass

            # Phase 3 & 4: Analyze & Lower (as statements)
            mod = compile_module(forms, filename="<repl>")
            code_obj = compile(mod, "<repl>", "exec")
            exec(code_obj, self.state.env, self.state.env)

            # If we processed a (ns ...) form, update the REPL namespace
            if ns_form_ns_name:
                self.state.namespace = ns_form_ns_name

            output = (
                stdout_capture.getvalue() if (capture_output and stdout_capture) else ""
            )
            return EvalResult(type=ResultType.EMPTY, output=output)

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            tb = traceback.format_exc()

            output = (
                stdout_capture.getvalue() if (capture_output and stdout_capture) else ""
            )

            return EvalResult(
                type=ResultType.ERROR,
                error=error_msg,
                error_type=error_type,
                traceback=tb,
                output=output,
            )
        finally:
            if capture_output:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

    def _is_using_ns_form(self, form) -> bool:
        """Check if form is a (using-ns ...) form."""
        if not isinstance(form, list) or len(form) < 2:
            return False
        head = form[0]
        return isinstance(head, Symbol) and head.name == "using-ns"

    def _is_ns_form(self, form) -> bool:
        """Check if form is a (ns ...) form."""
        if not isinstance(form, list) or len(form) < 2:
            return False
        head = form[0]
        return isinstance(head, Symbol) and head.name == "ns"

    def _extract_ns_name(self, form) -> Optional[str]:
        """Extract the namespace name from a (ns name ...) form."""
        if not isinstance(form, list) or len(form) < 2:
            return None
        ns_name_form = form[1]
        if isinstance(ns_name_form, Symbol):
            return ns_name_form.name
        return None

    def _handle_using_ns(
        self, form, capture_output: bool, stdout_capture: Optional[io.StringIO]
    ) -> EvalResult:
        """
        Handle (using-ns namespace) form.

        This switches the REPL's current namespace context.
        If the namespace isn't loaded, attempts to load it.
        """
        if len(form) != 2:
            return EvalResult(
                type=ResultType.ERROR,
                error="using-ns requires exactly one argument: the namespace name",
                error_type="SyntaxError",
            )

        ns_form = form[1]
        if not isinstance(ns_form, Symbol):
            return EvalResult(
                type=ResultType.ERROR,
                error="using-ns argument must be a symbol",
                error_type="SyntaxError",
            )

        ns_name = ns_form.name

        try:
            # Check if namespace is already loaded
            ns_info = get_namespace(ns_name)

            if ns_info is None:
                # Try to find and load the namespace
                spork_file = find_spork_file_for_ns(ns_name)
                if spork_file is None:
                    return EvalResult(
                        type=ResultType.ERROR,
                        error=f"Namespace '{ns_name}' not found",
                        error_type="FileNotFoundError",
                    )

                # Load the file
                env = exec_file(spork_file)

                # Check if it registered itself
                ns_info = get_namespace(ns_name)
                if ns_info is None:
                    # Register it ourselves
                    import os

                    register_namespace(
                        name=ns_name,
                        file=os.path.abspath(spork_file),
                        env=env,
                        macros=env.get("__spork_macros__", {}),
                    )
                    ns_info = get_namespace(ns_name)

            # Switch to the namespace
            self.state.namespace = ns_name

            # Optionally merge the namespace's env into REPL env
            # This makes the namespace's definitions available
            if ns_info and ns_info.env:
                for key, value in ns_info.env.items():
                    if not key.startswith("_"):
                        self.state.env[key] = value

                # Also merge macros
                if ns_info.macros:
                    self.macro_env.update(ns_info.macros)

            output = (
                stdout_capture.getvalue() if (capture_output and stdout_capture) else ""
            )
            return EvalResult(
                type=ResultType.VALUE,
                value=f"Switched to namespace: {ns_name}",
                output=output,
            )

        except Exception as e:
            import traceback

            return EvalResult(
                type=ResultType.ERROR,
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )

    def eval_with_buffer(self, line: str) -> EvalResult:
        """
        Evaluate a line of code, using a buffer for incomplete expressions.

        Args:
            line: A line of code to evaluate.

        Returns:
            An EvalResult. If incomplete, returns INCOMPLETE type.
        """
        self.buffer += line + "\n"

        if self.is_complete(self.buffer):
            code = self.buffer
            self.buffer = ""
            result = self.eval(code)
            self.state.add_to_history(code, result)
            return result
        else:
            return EvalResult(type=ResultType.INCOMPLETE)

    def reset_buffer(self):
        """Clear the input buffer."""
        self.buffer = ""

    def get_completions(self, prefix: str) -> list[str]:
        """
        Get completions for the given prefix.

        Args:
            prefix: The prefix to complete.

        Returns:
            A list of possible completions.
        """
        completions = []

        # Complete from environment
        for key in self.state.env.keys():
            if key.startswith(prefix) and not key.startswith("__"):
                completions.append(key)

        # Complete from macros
        for key in self.macro_env.keys():
            if key.startswith(prefix):
                completions.append(key)

        return sorted(completions)

    def get_doc(self, symbol: str) -> Optional[str]:
        """
        Get documentation for a symbol.

        Args:
            symbol: The symbol to get documentation for.

        Returns:
            The documentation string, or None if not found.
        """
        obj = self.state.get_env_value(symbol)
        if obj is not None:
            doc = getattr(obj, "__doc__", None)
            if doc:
                return doc

        # Check macros
        if symbol in self.macro_env:
            macro = self.macro_env[symbol]
            doc = getattr(macro, "__doc__", None)
            if doc:
                return doc

        return None

    def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """
        Get rich metadata for a symbol.

        Returns a dict with:
        - name: the symbol name
        - ns: the namespace where this symbol is defined
        - type: "function", "macro", "protocol", "protocol-fn", "var", "class"
        - doc: docstring if available
        - arglists: argument lists if it's a function/macro
        - protocol: protocol name if it's a protocol function
        - impls: list of implementing types if it's a protocol
        - source: {"file": ..., "line": ..., "col": ...} if available
        """
        from spork.runtime.ns import NAMESPACE_REGISTRY

        info: dict[str, Any] = {"name": symbol}

        # Helper to find which namespace a symbol came from
        def find_symbol_namespace(sym: str, obj: Any) -> Optional[str]:
            """Find which namespace defines this symbol."""
            py_sym = normalize_name(sym)
            # First check if it's in the current namespace
            current_ns = self.state.namespace
            if current_ns in NAMESPACE_REGISTRY:
                ns_info = NAMESPACE_REGISTRY[current_ns]
                if sym in ns_info.env or py_sym in ns_info.env:
                    env_obj = ns_info.env.get(sym) or ns_info.env.get(py_sym)
                    if env_obj is obj:
                        return current_ns
                # Check if it was referred from another namespace
                if sym in ns_info.refers:
                    return ns_info.refers[sym]
            # Search all namespaces for this symbol
            for ns_name, ns_info in NAMESPACE_REGISTRY.items():
                if sym in ns_info.env or py_sym in ns_info.env:
                    env_obj = ns_info.env.get(sym) or ns_info.env.get(py_sym)
                    if env_obj is obj:
                        return ns_name
            return None

        # Normalize the symbol name (hyphen to underscore) for Python lookup
        py_name = normalize_name(symbol)

        # Check if it's a macro
        if symbol in self.macro_env:
            macro = self.macro_env[symbol]
            info["type"] = "macro"
            info["ns"] = self.state.namespace  # Macros are in current namespace context
            info["doc"] = getattr(macro, "__doc__", None)
            # Try to get arglists from signature
            import inspect

            try:
                sig = inspect.signature(macro)
                params = list(sig.parameters.keys())
                info["arglists"] = [params]
            except (ValueError, TypeError):
                pass
            return info

        # Check if it's a protocol
        if symbol in _PROTOCOLS:
            proto = _PROTOCOLS[symbol]
            info["type"] = "protocol"
            info["ns"] = "spork.core"  # Protocols are in core namespace
            info["doc"] = proto.get("doc")
            info["methods"] = proto.get("methods", [])
            info["structural"] = proto.get("structural", False)
            # Get implementing types
            impls = _PROTOCOL_IMPLS.get(symbol, {})
            info["impls"] = [t.__name__ for t in impls.keys()]
            return info

        # Check if it's a protocol function (method)
        for proto_name, proto in _PROTOCOLS.items():
            if symbol in proto.get("methods", []):
                info["type"] = "protocol-fn"
                info["ns"] = "spork.core"  # Protocol functions are in core namespace
                info["protocol"] = proto_name
                info["doc"] = proto.get("doc")
                # Get implementing types for this protocol
                impls = _PROTOCOL_IMPLS.get(proto_name, {})
                info["impls"] = [t.__name__ for t in impls.keys()]
                return info

        # Check in environment (try both original and normalized name)
        obj = self.state.get_env_value(symbol)
        if obj is None and py_name != symbol:
            obj = self.state.get_env_value(py_name)
        if obj is not None:
            import inspect

            # Find which namespace this symbol is from
            ns = find_symbol_namespace(symbol, obj)
            if ns:
                info["ns"] = ns

            if isinstance(obj, type):
                info["type"] = "class"
                info["doc"] = getattr(obj, "__doc__", None)
            elif callable(obj):
                info["type"] = "function"
                info["doc"] = getattr(obj, "__doc__", None)
                try:
                    sig = inspect.signature(obj)
                    params = list(sig.parameters.keys())
                    info["arglists"] = [params]
                except (ValueError, TypeError):
                    pass
                # Try to get source location
                try:
                    source_file = inspect.getfile(obj)
                    source_lines, start_line = inspect.getsourcelines(obj)
                    info["source"] = {
                        "file": source_file,
                        "line": start_line,
                        "col": 0,
                    }
                except (TypeError, OSError):
                    pass
            else:
                info["type"] = "var"
                info["value-type"] = type(obj).__name__

            # If we still don't have a namespace, use current
            if "ns" not in info:
                info["ns"] = self.state.namespace

            return info

        # Symbol not found
        info["status"] = "not-found"
        return info

    def get_source(self, symbol: str) -> Optional[str]:
        """
        Get source code for a symbol.

        Args:
            symbol: The symbol to get source for.

        Returns:
            The source code string, or None if not available.
        """
        import inspect

        obj = self.state.get_env_value(symbol)
        if obj is not None:
            try:
                return inspect.getsource(obj)
            except (TypeError, OSError):
                pass

        return None

    def get_source_location(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        Get source location for a symbol (file, line, col).

        Args:
            symbol: The symbol to get location for.

        Returns:
            A dict with file, line, col keys, or None if not found.
        """
        import inspect

        # Normalize the symbol name (hyphen to underscore) for Python lookup
        py_name = normalize_name(symbol)

        # Check if it's a macro
        if symbol in self.macro_env:
            macro = self.macro_env[symbol]
            try:
                source_file = inspect.getfile(macro)
                source_lines, start_line = inspect.getsourcelines(macro)
                return {
                    "file": source_file,
                    "line": start_line,
                    "col": 0,
                }
            except (TypeError, OSError):
                pass

        # Check in environment (try both original and normalized name)
        obj = self.state.get_env_value(symbol)
        if obj is None and py_name != symbol:
            obj = self.state.get_env_value(py_name)
        if obj is not None and callable(obj):
            try:
                source_file = inspect.getfile(obj)
                source_lines, start_line = inspect.getsourcelines(obj)
                return {
                    "file": source_file,
                    "line": start_line,
                    "col": 0,
                }
            except (TypeError, OSError):
                pass

        return None


class ReplFrontend(ABC):
    """
    Abstract base class for REPL frontends.

    Subclasses should implement the run method to provide
    specific input/output behavior.
    """

    def __init__(self, backend: Optional[ReplBackend] = None):
        """
        Initialize the frontend.

        Args:
            backend: Optional ReplBackend to use. If None, creates a new one.
        """
        self.backend = backend or ReplBackend()

    @abstractmethod
    def run(self):
        """Run the REPL frontend."""
        pass


class TerminalRepl(ReplFrontend):
    """
    Terminal-based REPL frontend with readline support.
    """

    def __init__(
        self,
        backend: Optional[ReplBackend] = None,
        continuation_prompt: str = "... ",
    ):
        """
        Initialize the terminal REPL.

        Args:
            backend: Optional ReplBackend to use.
            continuation_prompt: The prompt for continuation lines.
        """
        super().__init__(backend)
        self.continuation_prompt = continuation_prompt
        self.setup_readline()

    @property
    def prompt(self) -> str:
        """Get the prompt showing the current namespace."""
        return f"{self.backend.state.namespace}> "

    def setup_readline(self):
        """Setup readline for better line editing."""
        try:
            import readline

            self.readline = readline

            # Set up completion
            readline.set_completer(self.complete)
            readline.parse_and_bind("tab: complete")

            # Set up history
            try:
                readline.read_history_file(".spork_history")
            except FileNotFoundError:
                pass

            import atexit

            atexit.register(lambda: readline.write_history_file(".spork_history"))

        except ImportError:
            self.readline = None

    def complete(self, text: str, state: int) -> Optional[str]:
        """Completion function for readline."""
        if state == 0:
            self.completions = self.backend.get_completions(text)

        try:
            return self.completions[state]
        except IndexError:
            return None

    def format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, str):
            return repr(value)
        else:
            return str(value)

    def print_result(self, result: EvalResult):
        """Print an evaluation result."""
        if result.is_error():
            print(f"Error: {result.error_type}: {result.error}", file=sys.stderr)
            if result.traceback and "--verbose" in sys.argv:
                print(result.traceback, file=sys.stderr)
        elif result.type == ResultType.VALUE:
            if result.value is not None:
                print(self.format_value(result.value))

    def run(self):
        """Run the terminal REPL."""
        print("Spork REPL - A Lisp for Python")
        print("Type (help) for help, Ctrl-D or (exit) to quit.")
        print()

        current_prompt = self.prompt

        while True:
            try:
                line = input(current_prompt)
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                self.backend.reset_buffer()
                current_prompt = self.prompt
                continue

            # Check for special commands
            if line.strip() in ["(exit)", "(quit)"]:
                break

            if line.strip() == "(help)":
                self.show_help()
                continue

            if line.strip().startswith("(doc "):
                symbol = line.strip()[5:-1].strip()
                doc = self.backend.get_doc(symbol)
                if doc:
                    print(doc)
                else:
                    print(f"No documentation found for {symbol}")
                continue

            if not line.strip():
                continue

            result = self.backend.eval_with_buffer(line)

            if result.is_incomplete():
                current_prompt = self.continuation_prompt
            else:
                self.print_result(result)
                current_prompt = self.prompt

    def show_help(self):
        """Show help message."""
        print("""
Spork REPL Commands:
  (help)           - Show this help message
  (doc symbol)     - Show documentation for a symbol
  (exit), (quit)   - Exit the REPL
  Ctrl-D           - Exit the REPL

Spork is a Lisp dialect that compiles to Python. Key features:
  - Immutable data structures
  - Pattern matching
  - Macros
  - Python interop

Example expressions:
  (+ 1 2 3)                    ; => 6
  (def x 10)                   ; Define a variable
  (defn square [x] (* x x))    ; Define a function
  (map square [1 2 3 4])       ; => [1, 4, 9, 16]

For more information, see the documentation.
""")


class SimpleRepl(ReplFrontend):
    """
    Minimal REPL frontend without readline support.
    Useful for embedding or when readline is not available.
    """

    def __init__(self, backend: Optional[ReplBackend] = None, prompt: str = "λ> "):
        """
        Initialize the simple REPL.

        Args:
            backend: Optional ReplBackend to use.
            prompt: The prompt string.
        """
        super().__init__(backend)
        self.prompt = prompt

    def run(self):
        """Run the simple REPL."""
        print("Spork REPL. Ctrl-D to exit.")

        while True:
            try:
                line = input(self.prompt)
            except EOFError:
                print()
                break

            if not line.strip():
                continue

            result = self.backend.eval(line)

            if result.is_error():
                print(f"Error: {result.error}")
            elif result.type == ResultType.VALUE and result.value is not None:
                print(result.value)


# Forms that should have their body indented (special forms)
_INDENT_FORMS = {
    "do",
    "let",
    "fn",
    "defn",
    "defmacro",
    "defclass",
    "def",
    "if",
    "when",
    "cond",
    "case",
    "match",
    "try",
    "catch",
    "finally",
    "loop",
    "for",
    "while",
    "doseq",
    "dotimes",
    "extend-type",
    "extend-protocol",
    "defprotocol",
    "with",
    "binding",
    "async-for",
}

# Threshold for breaking a list onto multiple lines
_LINE_LENGTH_THRESHOLD = 60


def format_spork_form(form: Any, indent: int = 0, pretty: bool = True) -> str:
    """
    Format a Spork form as a readable string (printer).

    This converts internal AST representations back to
    human-readable Spork code.

    Args:
        form: The form to format.
        indent: Current indentation level.
        pretty: Whether to use pretty-printing with newlines.
    """
    return _format_form(form, indent, pretty)


def _format_form(form: Any, indent: int = 0, pretty: bool = True) -> str:
    """Internal formatting function."""
    if form is None:
        return "nil"
    elif isinstance(form, bool):
        return "true" if form else "false"
    elif isinstance(form, str):
        # Escape the string properly
        escaped = form.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    elif isinstance(form, Symbol):
        return form.name
    elif isinstance(form, Keyword):
        return f":{form.name}"
    elif isinstance(form, (list, SourceList)):
        return _format_list(form, indent, pretty)
    elif isinstance(form, VectorLiteral):
        return _format_vector(form, indent, pretty)
    elif isinstance(form, MapLiteral):
        return _format_map(form.pairs, indent, pretty)
    elif isinstance(form, dict):
        pairs = list(form.items())
        return _format_map(pairs, indent, pretty)
    elif isinstance(form, (int, float)):
        return str(form)
    else:
        return str(form)


def _format_list(form: list, indent: int, pretty: bool) -> str:
    """Format a list/sexp with smart indentation."""
    if not form:
        return "()"

    # Get the head of the form
    head = form[0]
    head_name = head.name if isinstance(head, Symbol) else None

    # First, try formatting on a single line
    single_line = "(" + " ".join(_format_form(f, 0, False) for f in form) + ")"

    # If it fits or we're not pretty-printing, use single line
    if not pretty or len(single_line) <= _LINE_LENGTH_THRESHOLD:
        return single_line

    # For special forms, use indented multi-line formatting
    if head_name in _INDENT_FORMS:
        return _format_indented_form(form, head_name, indent)

    # For other long forms, break after head
    return _format_long_form(form, indent)


def _format_indented_form(form: list, head_name: str, indent: int) -> str:
    """Format a special form with proper indentation."""
    head = _format_form(form[0], indent, False)
    body_indent = indent + 2
    indent_str = " " * body_indent

    if head_name == "do":
        # (do body...)
        body_parts = [_format_form(f, body_indent, True) for f in form[1:]]
        body = ("\n" + indent_str).join(body_parts)
        return f"({head}\n{indent_str}{body})"

    elif head_name in ("let", "loop", "binding"):
        # (let [bindings] body...)
        if len(form) >= 2:
            bindings = form[1]
            body = form[2:]
            bindings_str = _format_form(bindings, body_indent, True)
            body_parts = [_format_form(f, body_indent, True) for f in body]
            body_str = ("\n" + indent_str).join(body_parts)
            if body_str:
                return f"({head} {bindings_str}\n{indent_str}{body_str})"
            else:
                return f"({head} {bindings_str})"
        return _format_long_form(form, indent)

    elif head_name in ("defn", "defmacro"):
        # (defn name [args] body...)
        if len(form) >= 3:
            name = _format_form(form[1], indent, False)
            rest = form[2:]
            # Check for docstring
            if rest and isinstance(rest[0], str):
                docstring = _format_form(rest[0], body_indent, False)
                rest = rest[1:]
                if rest:
                    args = _format_form(rest[0], body_indent, False)
                    body = rest[1:]
                    body_parts = [_format_form(f, body_indent, True) for f in body]
                    body_str = ("\n" + indent_str).join(body_parts)
                    return f"({head} {name}\n{indent_str}{docstring}\n{indent_str}{args}\n{indent_str}{body_str})"
            elif rest:
                args = _format_form(rest[0], body_indent, False)
                body = rest[1:]
                body_parts = [_format_form(f, body_indent, True) for f in body]
                body_str = ("\n" + indent_str).join(body_parts)
                if body_str:
                    return f"({head} {name} {args}\n{indent_str}{body_str})"
                else:
                    return f"({head} {name} {args})"
        return _format_long_form(form, indent)

    elif head_name in ("extend-type", "extend-protocol"):
        # (extend-type Type Protocol (method [args] body)...)
        if len(form) >= 2:
            type_name = _format_form(form[1], indent, False)
            rest = form[2:]
            parts = [f"({head} {type_name}"]
            for item in rest:
                parts.append(indent_str + _format_form(item, body_indent, True))
            return "\n".join(parts) + ")"
        return _format_long_form(form, indent)

    elif head_name == "defprotocol":
        # (defprotocol Name "doc" (method [args])...)
        if len(form) >= 2:
            name = _format_form(form[1], indent, False)
            rest = form[2:]
            parts = [f"({head} {name}"]
            for item in rest:
                parts.append(indent_str + _format_form(item, body_indent, True))
            return "\n".join(parts) + ")"
        return _format_long_form(form, indent)

    else:
        # Generic indented form
        return _format_long_form(form, indent)


def _format_long_form(form: list, indent: int) -> str:
    """Format a long form by breaking after the first element."""
    if not form:
        return "()"

    head = _format_form(form[0], indent, False)
    if len(form) == 1:
        return f"({head})"

    body_indent = indent + 2
    indent_str = " " * body_indent
    body_parts = [_format_form(f, body_indent, True) for f in form[1:]]
    body = ("\n" + indent_str).join(body_parts)
    return f"({head}\n{indent_str}{body})"


def _format_vector(form: VectorLiteral, indent: int, pretty: bool) -> str:
    """Format a vector."""
    if not form.items:
        return "[]"

    single_line = "[" + " ".join(_format_form(f, 0, False) for f in form.items) + "]"
    if not pretty or len(single_line) <= _LINE_LENGTH_THRESHOLD:
        return single_line

    # Multi-line vector
    body_indent = indent + 1
    indent_str = " " * body_indent
    parts = [_format_form(f, body_indent, True) for f in form.items]
    return "[" + ("\n" + indent_str).join(parts) + "]"


def _format_map(pairs: list, indent: int, pretty: bool) -> str:
    """Format a map/dict."""
    if not pairs:
        return "{}"

    formatted_pairs = [
        f"{_format_form(k, 0, False)} {_format_form(v, 0, False)}" for k, v in pairs
    ]
    single_line = "{" + " ".join(formatted_pairs) + "}"

    if not pretty or len(single_line) <= _LINE_LENGTH_THRESHOLD:
        return single_line

    # Multi-line map
    body_indent = indent + 1
    indent_str = " " * body_indent
    parts = [
        f"{_format_form(k, body_indent, True)} {_format_form(v, body_indent, True)}"
        for k, v in pairs
    ]
    return "{" + ("\n" + indent_str).join(parts) + "}"


def make_inspector_summary(val: Any) -> dict[str, Any]:
    """
    Create a JSON-friendly summary of a value for the inspector.

    Returns:
        A dict with type, count/size (if applicable), preview, keys, etc.
    """
    summary: dict[str, Any] = {"type": type(val).__name__}

    if val is None:
        summary["value"] = "nil"
    elif isinstance(val, bool):
        summary["value"] = "true" if val else "false"
    elif isinstance(val, (int, float, str)):
        summary["value"] = str(val)
    elif isinstance(val, (list, tuple)):
        summary["count"] = len(val)
        # Preview first few elements
        preview = [str(v)[:50] for v in val[:5]]
        if len(val) > 5:
            preview.append("...")
        summary["preview"] = preview
    elif isinstance(val, dict):
        summary["count"] = len(val)
        # Show keys
        keys = list(val.keys())[:10]
        summary["keys"] = [str(k) for k in keys]
        if len(val) > 10:
            summary["keys"].append("...")
    elif hasattr(val, "__dict__"):
        # Object with attributes
        attrs = [k for k in dir(val) if not k.startswith("_")][:10]
        summary["attrs"] = attrs
        if len([k for k in dir(val) if not k.startswith("_")]) > 10:
            summary["attrs"].append("...")
    elif hasattr(val, "__iter__"):
        # Try to get count for iterables
        try:
            count = len(val)
            summary["count"] = count
        except TypeError:
            summary["count"] = "?"

    return summary


def navigate_value(container: Any, path: list[Any]) -> Any:
    """
    Navigate into a value by following a path.

    path elements can be:
    - integers for list/tuple/vector indexing
    - strings for dict keys or object attributes
    - strings starting with ":" for keyword keys (colon is stripped)
    """
    current = container
    for step in path:
        if isinstance(step, int):
            if isinstance(current, (list, tuple)):
                current = current[step]
            elif hasattr(current, "__getitem__"):
                current = current[step]
            else:
                raise KeyError(f"Cannot index into {type(current).__name__}")
        elif isinstance(step, str):
            # Handle keyword-style keys (strip leading colon)
            key = step[1:] if step.startswith(":") else step
            # Check for dict-like objects (dict, Map, etc.) - they have 'get' method
            if hasattr(current, "get") and hasattr(current, "__getitem__"):
                # Try the key as-is first, then try without colon
                if current.get(step) is not None:
                    current = current[step]
                elif current.get(key) is not None:
                    current = current[key]
                else:
                    raise KeyError(f"Key {step} not found in {type(current).__name__}")
            elif hasattr(current, key):
                current = getattr(current, key)
            else:
                raise KeyError(f"Cannot access {step} on {type(current).__name__}")
        else:
            # Try as dict key
            if hasattr(current, "__getitem__"):
                current = current[step]
            else:
                raise KeyError(f"Unknown path element type: {type(step)}")
    return current


class NReplProtocol:
    """
    nREPL-style protocol for editor integration.

    This provides a simple message-based protocol that can be used
    by editors and other tools to interact with the REPL.
    """

    def __init__(self, backend: Optional[ReplBackend] = None):
        """Initialize the nREPL protocol."""
        self.backend = backend or ReplBackend()
        self.session_id = 0

    def handle_eval(
        self,
        code: str,
        session: Optional[str] = None,
        file_path: Optional[str] = None,
        ns: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Handle an eval request.

        Args:
            code: The code to evaluate.
            session: Optional session identifier.
            file_path: Optional source file path for namespace context.
            ns: Optional namespace to evaluate in.

        Returns:
            A response dictionary.
        """
        # Set up source roots if file path is provided
        if file_path:
            from spork.runtime.ns import init_source_roots

            # Initialize source roots based on the file
            init_source_roots(current_file=file_path, include_cwd=True)

        result = self.backend.eval(code, capture_output=True)

        response = {
            "session": session or f"session-{self.session_id}",
        }

        # Include any output
        if result.output:
            response["out"] = result.output

        if result.is_success():
            if result.type == ResultType.VALUE and result.value is not None:
                response["value"] = str(result.value)
            response["status"] = ["done"]  # type: ignore
        elif result.is_error():
            response["status"] = ["error"]  # type: ignore
            response["error"] = result.error or ""
            response["error-type"] = result.error_type or ""
            if result.traceback:
                response["traceback"] = result.traceback
        elif result.is_incomplete():
            response["status"] = ["incomplete"]  # type: ignore

        return response

    def handle_complete(self, prefix: str) -> dict[str, Any]:
        """
        Handle a completion request.

        Args:
            prefix: The prefix to complete.

        Returns:
            A response dictionary with completions.
        """
        completions = self.backend.get_completions(prefix)
        return {"completions": completions, "status": ["done"]}  # type: ignore

    def handle_doc(self, symbol: str) -> dict[str, Any]:
        """
        Handle a documentation request.

        Args:
            symbol: The symbol to get documentation for.

        Returns:
            A response dictionary with documentation.
        """
        doc = self.backend.get_doc(symbol)

        if doc:
            return {"doc": doc, "status": ["done"]}  # type: ignore
        else:
            return {"status": ["error"]}  # type: ignore

    def handle_macroexpand(self, code: str) -> dict[str, Any]:
        """
        Handle a macroexpand request.

        Args:
            code: The code to macroexpand.

        Returns:
            A response dictionary with the expansion.
        """
        try:
            forms = read_str(code)
            if not forms:
                return {"expansion": "", "status": ["done"]}
            expanded = macroexpand_all(forms, self.backend.macro_env)
            # Format the expanded forms
            if len(expanded) == 1:
                expansion = format_spork_form(expanded[0])
            else:
                expansion = "\n".join(format_spork_form(f) for f in expanded)
            return {"expansion": expansion, "status": ["done"]}
        except Exception as e:
            return {"status": ["error"], "error": str(e)}

    def handle_transpile(self, code: str) -> dict[str, Any]:
        """
        Handle a transpile request - convert Spork code to Python.

        Args:
            code: The Spork code to transpile.

        Returns:
            A response dictionary with the Python output.
        """
        try:
            forms = read_str(code)
            if not forms:
                return {"python": "", "status": ["done"]}
            # First expand macros
            expanded = macroexpand_all(forms, self.backend.macro_env)
            # Compile to Python AST
            mod = compile_module(expanded, filename="<transpile>")
            # Convert AST to Python source
            python_code = ast.unparse(mod)
            return {"python": python_code, "status": ["done"]}
        except Exception as e:
            return {"status": ["error"], "error": str(e)}

    def handle_info(self, symbol: str) -> dict[str, Any]:
        """
        Handle an info request (rich metadata).

        Args:
            symbol: The symbol to get info for.

        Returns:
            A response dictionary with symbol metadata.
        """
        info = self.backend.get_symbol_info(symbol)
        info["status"] = ["done"]
        return info

    def handle_find_def(self, symbol: str) -> dict[str, Any]:
        """
        Handle a find-def request (jump to definition).

        Args:
            symbol: The symbol to find.

        Returns:
            A response dictionary with file, line, col.
        """
        loc = self.backend.get_source_location(symbol)
        if loc:
            return {
                "file": loc["file"],
                "line": loc["line"],
                "col": loc["col"],
                "status": ["done"],
            }
        else:
            return {"status": ["error"], "error": f"Definition not found: {symbol}"}

    def handle_using_ns(self, ns_name: str) -> dict[str, Any]:
        """
        Handle a using-ns request (switch namespace).

        Args:
            ns_name: The namespace to switch to.

        Returns:
            A response dictionary with the new namespace.
        """
        # Create a using-ns form and evaluate it
        result = self.backend.eval(f"(using-ns {ns_name})", capture_output=True)

        if result.is_success():
            return {
                "ns": self.backend.state.namespace,
                "status": ["done"],
            }
        else:
            return {
                "status": ["error"],
                "error": result.error or f"Failed to switch to namespace: {ns_name}",
            }

    def handle_ns_list(self) -> dict[str, Any]:
        """
        Handle a ns-list request (list all loaded namespaces).

        Returns:
            A response dictionary with list of namespace names.
        """
        from spork.runtime.ns import list_namespaces

        namespaces = list_namespaces()
        return {
            "namespaces": namespaces,
            "current-ns": self.backend.state.namespace,
            "status": ["done"],
        }

    def handle_ns_info(self, ns_name: str) -> dict[str, Any]:
        """
        Handle a ns-info request (get info about a namespace).

        Args:
            ns_name: The namespace to get info for.

        Returns:
            A response dictionary with namespace metadata.
        """
        ns_info = get_namespace(ns_name)
        if ns_info is None:
            return {
                "status": ["error"],
                "error": f"Namespace not found: {ns_name}",
            }

        return {
            "name": ns_info.name,
            "file": ns_info.file,
            "loaded": ns_info.loaded,
            "aliases": ns_info.aliases,
            "refers": ns_info.refers,
            "status": ["done"],
        }

    def handle_inspect_start(self, code: str) -> dict[str, Any]:
        """
        Start an inspector session for a value.

        Args:
            code: The code to evaluate and inspect.

        Returns:
            A response with handle and summary.
        """
        result = self.backend.eval(code, capture_output=False)

        if result.is_error():
            return {
                "status": ["error"],
                "error": result.error or "Evaluation failed",
            }

        val = result.value
        handle = self.backend.next_inspect_handle
        self.backend.inspect_table[handle] = val
        self.backend.next_inspect_handle += 1

        return {
            "handle": handle,
            "summary": make_inspector_summary(val),
            "status": ["done"],
        }

    def handle_inspect_nav(self, handle: int, path: list[Any]) -> dict[str, Any]:
        """
        Navigate into an inspected value.

        Args:
            handle: The handle of the value to navigate from.
            path: The path to navigate (list of indices/keys/attrs).

        Returns:
            A response with new handle and summary.
        """
        if handle not in self.backend.inspect_table:
            return {"status": ["error"], "error": f"Unknown handle: {handle}"}

        try:
            container = self.backend.inspect_table[handle]
            val = navigate_value(container, path)

            new_handle = self.backend.next_inspect_handle
            self.backend.inspect_table[new_handle] = val
            self.backend.next_inspect_handle += 1

            return {
                "handle": new_handle,
                "summary": make_inspector_summary(val),
                "status": ["done"],
            }
        except Exception as e:
            return {"status": ["error"], "error": str(e)}

    def handle_protocols(self) -> dict[str, Any]:
        """
        Return information about all registered protocols.

        Returns:
            A response with protocol information.
        """
        protocols = {}
        for name, proto in _PROTOCOLS.items():
            impls = _PROTOCOL_IMPLS.get(name, {})
            protocols[name] = {
                "methods": proto.get("methods", []),
                "doc": proto.get("doc"),
                "structural": proto.get("structural", False),
                "impls": [t.__name__ for t in impls.keys()],
            }
        return {"protocols": protocols, "status": ["done"]}


def create_repl(mode: str = "terminal", **kwargs) -> ReplFrontend:
    """
    Factory function to create a REPL frontend.

    Args:
        mode: The mode of REPL to create ("terminal" or "simple").
        **kwargs: Additional arguments to pass to the frontend.

    Returns:
        A ReplFrontend instance.
    """
    if mode == "terminal":
        return TerminalRepl(**kwargs)
    elif mode == "simple":
        return SimpleRepl(**kwargs)
    else:
        raise ValueError(f"Unknown REPL mode: {mode}")


def main():
    """Main entry point for the REPL."""
    import sys

    # Check for mode argument
    mode = "terminal"
    if len(sys.argv) > 1 and sys.argv[1] == "--simple":
        mode = "simple"

    repl = create_repl(mode)
    repl.run()


if __name__ == "__main__":
    main()
