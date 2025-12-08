"""
spork.repl - REPL and nREPL Server

This package provides interactive REPL functionality for Spork:

Modules:
- backend.py: Core REPL backend with pluggable frontends (terminal, nREPL)
- nrepl.py: Network REPL server for editor integration

The REPL supports:
- Interactive code evaluation
- Tab completion
- Multi-line input
- History
- Syntax highlighting (terminal mode)
- Editor integration via nREPL protocol
"""

# Re-export from backend
from spork.repl.backend import (
    EvalResult,
    NReplProtocol,
    ReplBackend,
    ReplFrontend,
    ResultType,
    TerminalRepl,
    create_repl,
)

# Re-export from nrepl
from spork.repl.nrepl import (
    NReplServer,
    SimpleNReplClient,
)

__all__ = [
    # Backend
    "ReplBackend",
    "ReplFrontend",
    "TerminalRepl",
    "NReplProtocol",
    "EvalResult",
    "ResultType",
    "create_repl",
    # nREPL
    "NReplServer",
    "SimpleNReplClient",
]
