"""
spork.lsp - Language Server Protocol implementation for Spork

This package provides an LSP server for Spork, enabling editor integration
for features like:
- Code completion
- Hover documentation
- Go to definition
- Diagnostics (errors and warnings)
- Symbol information

The LSP server communicates over stdio using JSON-RPC 2.0.
"""

from spork.lsp.server import SporkLanguageServer

__all__ = ["SporkLanguageServer"]
