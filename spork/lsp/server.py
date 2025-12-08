"""
spork.lsp.server - Spork Language Server Implementation

This module provides the main LSP server for Spork. It leverages the
ReplBackend for evaluation and symbol information, and integrates with
the project system for workspace awareness.

Features:
- Code completion
- Hover documentation
- Go to definition
- Diagnostics (parse errors, compile errors)
- Document synchronization

Usage:
    The server is started via `spork lsp` and communicates over stdio.
"""

import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from spork.lsp.protocol import (
    CompletionItemKind,
    DiagnosticSeverity,
    ErrorCode,
    JsonRpcError,
    JsonRpcProtocol,
    ProtocolReader,
    ProtocolWriter,
    TextDocumentSyncKind,
    make_completion_item,
    make_diagnostic,
    make_hover,
    make_location,
    make_range,
    path_to_uri,
    uri_to_path,
)


@dataclass
class TextDocument:
    """Represents an open text document."""

    uri: str
    language_id: str
    version: int
    content: str

    @property
    def path(self) -> str:
        """Get the file system path for this document."""
        return uri_to_path(self.uri)

    def get_line(self, line: int) -> str:
        """Get a specific line (0-based)."""
        lines = self.content.split("\n")
        if 0 <= line < len(lines):
            return lines[line]
        return ""

    def get_word_at_position(self, line: int, character: int) -> Optional[str]:
        """
        Get the word at the given position.

        Returns the symbol/word under or before the cursor.
        """
        line_text = self.get_line(line)
        if not line_text or character > len(line_text):
            return None

        # Find word boundaries
        # Spork symbols can contain: letters, digits, -, _, /, ., ?, !, +, *, <, >, =, &, #, ^
        # Based on LANG.md: identifiers like my-variable, valid?, math/sin are valid
        def is_symbol_char(c: str) -> bool:
            return c.isalnum() or c in "-_/.?!+*<>=:&^#"

        # Find start of word
        start = character
        while start > 0 and is_symbol_char(line_text[start - 1]):
            start -= 1

        # Find end of word
        end = character
        while end < len(line_text) and is_symbol_char(line_text[end]):
            end += 1

        if start == end:
            return None

        return line_text[start:end]

    def offset_to_position(self, offset: int) -> tuple[int, int]:
        """Convert a character offset to (line, character)."""
        line = 0
        col = 0
        for i, c in enumerate(self.content):
            if i == offset:
                break
            if c == "\n":
                line += 1
                col = 0
            else:
                col += 1
        return line, col


@dataclass
class SporkLanguageServer:
    """
    Spork Language Server Protocol implementation.

    This server provides IDE features for Spork source files.
    """

    # Protocol handler
    protocol: JsonRpcProtocol = field(default_factory=JsonRpcProtocol)

    # Open documents: uri -> TextDocument
    documents: dict[str, TextDocument] = field(default_factory=dict)

    # REPL backend for evaluation and symbol info
    backend: Any = None

    # Project configuration (if in a project)
    project_config: Any = None
    project_manager: Any = None

    # Server state
    initialized: bool = False
    shutdown_requested: bool = False

    # Workspace root
    root_uri: Optional[str] = None
    root_path: Optional[str] = None

    # Logging
    log_file: Any = None

    def __post_init__(self):
        """Set up the server after initialization."""
        self._register_handlers()

    def _log(self, message: str) -> None:
        """Log a message for debugging."""
        if self.log_file:
            self.log_file.write(f"{message}\n")
            self.log_file.flush()
        # Also write to stderr for debugging (LSP clients typically capture this)
        print(f"[spork-lsp] {message}", file=sys.stderr)
        sys.stderr.flush()

    def _register_handlers(self) -> None:
        """Register all LSP method handlers."""
        # Lifecycle
        self.protocol.register_request_handler("initialize", self._handle_initialize)
        self.protocol.register_notification_handler(
            "initialized", self._handle_initialized
        )
        self.protocol.register_request_handler("shutdown", self._handle_shutdown)
        self.protocol.register_notification_handler("exit", self._handle_exit)

        # Text document synchronization
        self.protocol.register_notification_handler(
            "textDocument/didOpen", self._handle_did_open
        )
        self.protocol.register_notification_handler(
            "textDocument/didChange", self._handle_did_change
        )
        self.protocol.register_notification_handler(
            "textDocument/didClose", self._handle_did_close
        )
        self.protocol.register_notification_handler(
            "textDocument/didSave", self._handle_did_save
        )

        # Language features
        self.protocol.register_request_handler(
            "textDocument/completion", self._handle_completion
        )
        self.protocol.register_request_handler("textDocument/hover", self._handle_hover)
        self.protocol.register_request_handler(
            "textDocument/definition", self._handle_definition
        )
        self.protocol.register_request_handler(
            "textDocument/references", self._handle_references
        )
        self.protocol.register_request_handler(
            "textDocument/documentSymbol", self._handle_document_symbol
        )

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the initialize request."""
        self._log("Received initialize request")

        # Get workspace root
        self.root_uri = params.get("rootUri")
        if self.root_uri:
            self.root_path = uri_to_path(self.root_uri)
        else:
            # Fall back to rootPath (deprecated but still used)
            self.root_path = params.get("rootPath")
            if self.root_path:
                self.root_uri = path_to_uri(self.root_path)

        self._log(f"Workspace root: {self.root_path}")

        # Try to load project configuration
        self._load_project()

        # Initialize the REPL backend
        self._init_backend()

        # Return server capabilities
        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": TextDocumentSyncKind.FULL,
                    "save": {"includeText": True},
                },
                "completionProvider": {
                    "triggerCharacters": [".", "/", ":"],
                    "resolveProvider": False,
                },
                "hoverProvider": True,
                "definitionProvider": True,
                "referencesProvider": False,  # Not yet implemented
                "documentSymbolProvider": True,
            },
            "serverInfo": {
                "name": "spork-lsp",
                "version": "0.1.0",
            },
        }

    def _handle_initialized(self, params: dict[str, Any]) -> None:
        """Handle the initialized notification."""
        self._log("Server initialized")
        self.initialized = True

        # If we have a project, we could scan for files here
        if self.project_config:
            self._log(f"Project: {self.project_config.name}")

    def _handle_shutdown(self, params: dict[str, Any]) -> None:
        """Handle the shutdown request."""
        self._log("Shutdown requested")
        self.shutdown_requested = True
        return None

    def _handle_exit(self, params: dict[str, Any]) -> None:
        """Handle the exit notification."""
        self._log("Exit notification received")
        exit_code = 0 if self.shutdown_requested else 1
        sys.exit(exit_code)

    # =========================================================================
    # Document Synchronization
    # =========================================================================

    def _handle_did_open(self, params: dict[str, Any]) -> None:
        """Handle textDocument/didOpen notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        language_id = text_document.get("languageId", "spork")
        version = text_document.get("version", 0)
        content = text_document.get("text", "")

        self._log(f"Document opened: {uri}")

        doc = TextDocument(
            uri=uri,
            language_id=language_id,
            version=version,
            content=content,
        )
        self.documents[uri] = doc

        # Validate the document
        self._validate_document(doc)

    def _handle_did_change(self, params: dict[str, Any]) -> None:
        """Handle textDocument/didChange notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        version = text_document.get("version", 0)
        content_changes = params.get("contentChanges", [])

        if uri not in self.documents:
            self._log(f"Warning: didChange for unknown document: {uri}")
            return

        doc = self.documents[uri]

        # We're using full sync, so take the last content change
        if content_changes:
            doc.content = content_changes[-1].get("text", doc.content)
        doc.version = version

        # Re-validate
        self._validate_document(doc)

    def _handle_did_close(self, params: dict[str, Any]) -> None:
        """Handle textDocument/didClose notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")

        self._log(f"Document closed: {uri}")

        if uri in self.documents:
            del self.documents[uri]

        # Clear diagnostics for closed document
        self._publish_diagnostics(uri, [])

    def _handle_did_save(self, params: dict[str, Any]) -> None:
        """Handle textDocument/didSave notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        text = params.get("text")

        self._log(f"Document saved: {uri}")

        if uri in self.documents and text is not None:
            self.documents[uri].content = text
            self._validate_document(self.documents[uri])

    # =========================================================================
    # Language Features
    # =========================================================================

    def _handle_completion(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle textDocument/completion request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        if uri not in self.documents:
            return {"isIncomplete": False, "items": []}

        doc = self.documents[uri]
        prefix = self._get_completion_prefix(doc, line, character)

        self._log(f"Completion requested at {line}:{character}, prefix: '{prefix}'")

        items = []

        if self.backend:
            try:
                # Get completions from backend
                completions = self.backend.get_completions(prefix)

                for name in completions:
                    # Determine the kind based on symbol info
                    info = self.backend.get_symbol_info(name)
                    sym_type = info.get("type", "var")

                    if sym_type == "function":
                        kind = CompletionItemKind.FUNCTION
                    elif sym_type == "macro":
                        kind = CompletionItemKind.KEYWORD
                    elif sym_type == "class":
                        kind = CompletionItemKind.CLASS
                    elif sym_type == "protocol":
                        kind = CompletionItemKind.INTERFACE
                    elif sym_type == "protocol-fn":
                        kind = CompletionItemKind.METHOD
                    else:
                        kind = CompletionItemKind.VARIABLE

                    doc_string = info.get("doc")
                    detail = info.get("ns")

                    items.append(
                        make_completion_item(
                            label=name,
                            kind=kind,
                            detail=detail,
                            documentation=doc_string,
                        )
                    )
            except Exception as e:
                self._log(f"Completion error: {e}")

        # Add special forms and keywords if no prefix or matching
        # These are the actual special forms from spork/compiler/codegen.py
        special_forms = [
            # Definition forms (from compile_toplevel and compile_stmt)
            "def",
            "defn",
            "defmacro",
            "defclass",
            "fn",
            "let",
            "set!",
            # Control flow (from compile_stmt and compile_expr)
            "if",
            "do",
            "loop",
            "recur",
            "for",
            "while",
            "async-for",
            # Exception handling
            "try",
            "catch",
            "finally",
            "throw",
            "return",
            # Quoting (from compile_expr)
            "quote",
            "quasiquote",
            # Namespace/modules (from compile_toplevel)
            "ns",
            "import",
            # Async/generators (from compile_stmt)
            "await",
            "yield",
            "yield-from",
            # Pattern matching (from compile_expr)
            "match",
            # Python interop
            "with",
            "apply",
            "call",
            # Attribute access
            ".",
        ]

        # Macros from spork/std/prelude.spork
        prelude_macros = [
            # Control flow macros
            "when",
            "unless",
            "cond",
            # Threading macros
            "->",
            "->>",
            # Utility macros
            "comment",
            "fmt",
            "assert",
            # Sequence macros
            "mapv",
            "filterv",
            "doseq",
            "for-all",
            # Function composition
            "comp",
            "partial",
            "identity",
            "constantly",
            "complement",
            # Predicates
            "nil?",
            "some?",
            "string?",
            "number?",
            "int?",
            "float?",
            "bool?",
            "fn?",
            "symbol?",
            "keyword?",
            "vector?",
            "map?",
            "list?",
            "seq?",
            "coll?",
            "dict?",
            "empty?",
            "not-empty",
            "even?",
            "odd?",
            "pos?",
            "neg?",
            "zero?",
            # Collection accessors
            "second",
            "ffirst",
            "last",
            "butlast",
            # Protocol macros
            "defprotocol",
            "extend-type",
            "extend-protocol",
        ]

        for kw in special_forms:
            if kw.startswith(prefix):
                items.append(
                    make_completion_item(
                        label=kw,
                        kind=CompletionItemKind.KEYWORD,
                        detail="special form",
                    )
                )

        for macro in prelude_macros:
            if macro.startswith(prefix):
                items.append(
                    make_completion_item(
                        label=macro,
                        kind=CompletionItemKind.KEYWORD,
                        detail="macro",
                    )
                )

        return {"isIncomplete": False, "items": items}

    def _handle_hover(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Handle textDocument/hover request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        if uri not in self.documents:
            return None

        doc = self.documents[uri]
        word = doc.get_word_at_position(line, character)

        if not word:
            return None

        self._log(f"Hover requested for: {word}")

        if not self.backend:
            return None

        try:
            # Get symbol info from backend
            info = self.backend.get_symbol_info(word)

            if info.get("status") == "not-found":
                return None

            # Build hover content in Markdown
            parts = []

            sym_type = info.get("type", "unknown")
            ns = info.get("ns", "")

            # Type and name (Spork uses / as namespace separator like Clojure)
            if ns:
                parts.append(f"**{ns}/{word}** ({sym_type})")
            else:
                parts.append(f"**{word}** ({sym_type})")

            # Arglists for functions - show in Spork style with brackets
            if "arglists" in info:
                for arglist in info["arglists"]:
                    # Spork uses [arg1 arg2] for parameter vectors
                    args = " ".join(arglist)
                    parts.append(f"\n```spork\n({word} [{args}])\n```")

            # Documentation
            if info.get("doc"):
                parts.append(f"\n{info['doc']}")

            # Protocol info
            if sym_type == "protocol-fn" and info.get("protocol"):
                parts.append(f"\nProtocol: {info['protocol']}")

            if info.get("impls"):
                parts.append(f"\nImplemented by: {', '.join(info['impls'])}")

            content = "\n".join(parts)
            return make_hover(content)

        except Exception as e:
            self._log(f"Hover error: {e}")
            return None

    def _handle_definition(self, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Handle textDocument/definition request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        if uri not in self.documents:
            return None

        doc = self.documents[uri]
        word = doc.get_word_at_position(line, character)

        if not word:
            return None

        self._log(f"Definition requested for: {word}")

        if not self.backend:
            return None

        try:
            # Get source location from backend
            location = self.backend.get_source_location(word)

            if not location:
                return None

            file_path = location.get("file")
            source_line = location.get("line", 1)
            source_col = location.get("col", 0)

            if not file_path or not os.path.isfile(file_path):
                return None

            # LSP uses 0-based line numbers, but inspect uses 1-based
            return make_location(
                uri=path_to_uri(file_path),
                range_=make_range(
                    source_line - 1, source_col, source_line - 1, source_col
                ),
            )

        except Exception as e:
            self._log(f"Definition error: {e}")
            return None

    def _handle_references(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Handle textDocument/references request."""
        # Not yet implemented - would require indexing the project
        return []

    def _handle_document_symbol(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Handle textDocument/documentSymbol request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")

        if uri not in self.documents:
            return []

        doc = self.documents[uri]
        symbols = []

        try:
            # Parse the document to find definitions
            from spork.compiler.reader import read_str

            forms = read_str(doc.content)

            for form in forms:
                symbol = self._extract_definition_symbol(form)
                if symbol:
                    symbols.append(symbol)

        except Exception as e:
            self._log(f"Document symbol error: {e}")

        return symbols

    def _extract_definition_symbol(self, form: Any) -> Optional[dict[str, Any]]:
        """Extract a symbol definition from a form if it's a def/defn/etc."""
        from spork.lsp.protocol import SymbolKind
        from spork.runtime.types import Symbol

        if not isinstance(form, list) or len(form) < 2:
            return None

        head = form[0]
        if not isinstance(head, Symbol):
            return None

        head_name = head.name

        # Map form type to symbol kind
        # Based on actual forms in spork/compiler/codegen.py
        kind_map = {
            "def": SymbolKind.VARIABLE,
            "defn": SymbolKind.FUNCTION,
            "defmacro": SymbolKind.FUNCTION,
            "defclass": SymbolKind.CLASS,
            "defprotocol": SymbolKind.INTERFACE,
        }

        if head_name not in kind_map:
            return None

        name = form[1]
        if not isinstance(name, Symbol):
            return None

        # Get location from the form if available
        line = getattr(form, "line", 1) - 1  # Convert to 0-based
        col = getattr(form, "col", 0)
        end_line = getattr(form, "end_line", line + 1) - 1
        end_col = getattr(form, "end_col", col)

        return {
            "name": name.name,
            "kind": kind_map[head_name],
            "range": make_range(line, col, end_line, end_col),
            "selectionRange": make_range(line, col, line, col + len(name.name)),
        }

    # =========================================================================
    # Validation and Diagnostics
    # =========================================================================

    def _validate_document(self, doc: TextDocument) -> None:
        """Validate a document and publish diagnostics."""
        diagnostics = []

        try:
            from spork.compiler.reader import read_str

            # Try to parse the document
            read_str(doc.content)

        except Exception as e:
            # Parse error
            error_msg = str(e)

            # Try to extract line/col from error message
            line = 0
            col = 0

            # Common error patterns from spork/compiler/reader.py:
            # "unterminated list at line 3, expected )"
            # "unterminated string starting at line 5"
            # "Map literal must have even number of forms at line 10"
            import re

            # Try "at line X" pattern first (most specific)
            line_match = re.search(r"at line (\d+)", error_msg, re.IGNORECASE)
            if not line_match:
                # Try "line X" or "line: X" pattern
                line_match = re.search(r"line[:\s]+(\d+)", error_msg, re.IGNORECASE)

            col_match = re.search(r"col(?:umn)?[:\s]+(\d+)", error_msg, re.IGNORECASE)

            if line_match:
                line = int(line_match.group(1)) - 1  # Convert to 0-based
            if col_match:
                col = int(col_match.group(1))

            diagnostics.append(
                make_diagnostic(
                    range_=make_range(line, col, line, col + 1),
                    message=error_msg,
                    severity=DiagnosticSeverity.ERROR,
                    source="spork",
                )
            )

        # Try to compile and catch any compile-time errors
        if not diagnostics:
            try:
                from spork.compiler import macroexpand_all, read_str
                from spork.compiler.codegen import compile_module

                forms = read_str(doc.content)
                expanded = [macroexpand_all(f) for f in forms]
                compile_module(expanded, filename=doc.path)

            except Exception as e:
                error_msg = str(e)

                # Extract location if available
                line = 0
                col = 0

                import re

                # Try "at line X" pattern first (most specific)
                line_match = re.search(r"at line (\d+)", error_msg, re.IGNORECASE)
                if not line_match:
                    # Try "line X" or "line: X" pattern
                    line_match = re.search(r"line[:\s]+(\d+)", error_msg, re.IGNORECASE)

                col_match = re.search(
                    r"col(?:umn)?[:\s]+(\d+)", error_msg, re.IGNORECASE
                )

                if line_match:
                    line = int(line_match.group(1)) - 1
                if col_match:
                    col = int(col_match.group(1))

                diagnostics.append(
                    make_diagnostic(
                        range_=make_range(line, col, line, col + 1),
                        message=error_msg,
                        severity=DiagnosticSeverity.ERROR,
                        source="spork",
                    )
                )

        self._publish_diagnostics(doc.uri, diagnostics)

    def _publish_diagnostics(self, uri: str, diagnostics: list[dict[str, Any]]) -> None:
        """Publish diagnostics for a document."""
        self.protocol.send_notification(
            "textDocument/publishDiagnostics",
            {
                "uri": uri,
                "diagnostics": diagnostics,
            },
        )

    # =========================================================================
    # Initialization Helpers
    # =========================================================================

    def _load_project(self) -> None:
        """Try to load project configuration from spork.it."""
        if not self.root_path:
            return

        try:
            from spork.project import ProjectConfig, ProjectManager

            self.project_config = ProjectConfig.load(self.root_path)
            self.project_manager = ProjectManager(self.project_config)

            self._log(f"Loaded project: {self.project_config.name}")

            # Ensure venv exists
            if not self.project_manager.has_venv():
                self._log("Project venv not found, initializing...")
                self.project_manager.install_dependencies(quiet=True)

            # Inject venv paths
            self.project_manager.inject_venv_paths()

        except FileNotFoundError:
            self._log("No spork.it project file found")
        except Exception as e:
            self._log(f"Error loading project: {e}")

    def _init_backend(self) -> None:
        """Initialize the REPL backend for language features."""
        try:
            from spork.repl.backend import ReplBackend
            from spork.runtime.ns import init_source_roots

            # Initialize source roots
            if self.project_config:
                for source_path in self.project_config.get_absolute_source_paths():
                    if os.path.isdir(source_path):
                        init_source_roots(extra_paths=[source_path])
            else:
                init_source_roots(include_cwd=True)

            self.backend = ReplBackend()
            self._log("REPL backend initialized")

        except Exception as e:
            self._log(f"Error initializing backend: {e}")
            self.backend = None

    def _get_completion_prefix(
        self, doc: TextDocument, line: int, character: int
    ) -> str:
        """Get the completion prefix at the given position."""
        line_text = doc.get_line(line)

        if not line_text or character == 0:
            return ""

        # Find the start of the current word
        def is_symbol_char(c: str) -> bool:
            return c.isalnum() or c in "-_/.?!+*<>=:"

        start = character
        while start > 0 and is_symbol_char(line_text[start - 1]):
            start -= 1

        return line_text[start:character]

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def run(self) -> None:
        """Run the language server main loop."""
        self._log("Spork Language Server starting")

        try:
            self.protocol.run()
        except KeyboardInterrupt:
            self._log("Interrupted")
        except Exception as e:
            self._log(f"Server error: {e}")
            traceback.print_exc(file=sys.stderr)
        finally:
            self._log("Server stopped")


def start_server(log_path: Optional[str] = None) -> None:
    """
    Start the Spork language server.

    Args:
        log_path: Optional path to a log file for debugging.
    """
    log_file = None
    if log_path:
        log_file = open(log_path, "w")

    try:
        server = SporkLanguageServer()
        if log_file:
            server.log_file = log_file
        server.run()
    finally:
        if log_file:
            log_file.close()


def main() -> None:
    """Main entry point for spork-lsp command."""
    import argparse

    parser = argparse.ArgumentParser(description="Spork Language Server")
    parser.add_argument(
        "--log",
        metavar="FILE",
        help="Log file for debugging",
    )
    args = parser.parse_args()

    start_server(log_path=args.log)


if __name__ == "__main__":
    main()
