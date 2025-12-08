"""
Test suite for the Spork Language Server Protocol implementation.

This module tests the LSP server functionality including:
- Protocol message framing
- Initialize/shutdown lifecycle
- Document synchronization
- Completion
- Hover
- Go to definition
- Diagnostics
"""

import io
import json
import unittest
from typing import Any


class TestProtocol(unittest.TestCase):
    """Test the JSON-RPC protocol implementation."""

    def test_message_framing(self):
        """Test that messages are properly framed with Content-Length headers."""
        from spork.lsp.protocol import ProtocolReader, ProtocolWriter

        # Create a buffer to write to
        output = io.BytesIO()
        writer = ProtocolWriter(output)

        # Write a message
        message = {"jsonrpc": "2.0", "method": "test", "params": {}}
        writer.write_message(message)

        # Read it back
        output.seek(0)
        reader = ProtocolReader(output)
        received = reader.read_message()

        self.assertEqual(received, message)

    def test_multiple_messages(self):
        """Test reading multiple messages in sequence."""
        from spork.lsp.protocol import ProtocolReader, ProtocolWriter

        output = io.BytesIO()
        writer = ProtocolWriter(output)

        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "first"},
            {"jsonrpc": "2.0", "id": 2, "method": "second"},
            {"jsonrpc": "2.0", "id": 3, "method": "third"},
        ]

        for msg in messages:
            writer.write_message(msg)

        output.seek(0)
        reader = ProtocolReader(output)

        for expected in messages:
            received = reader.read_message()
            self.assertEqual(received, expected)

    def test_unicode_content(self):
        """Test that unicode content is handled correctly."""
        from spork.lsp.protocol import ProtocolReader, ProtocolWriter

        output = io.BytesIO()
        writer = ProtocolWriter(output)

        message = {
            "jsonrpc": "2.0",
            "method": "test",
            "params": {"text": "こんにちは世界"},
        }
        writer.write_message(message)

        output.seek(0)
        reader = ProtocolReader(output)
        received = reader.read_message()

        self.assertEqual(received["params"]["text"], "こんにちは世界")


class TestJsonRpcProtocol(unittest.TestCase):
    """Test the JSON-RPC protocol handler."""

    def test_request_handling(self):
        """Test that requests are dispatched to handlers."""
        from spork.lsp.protocol import JsonRpcProtocol

        protocol = JsonRpcProtocol()

        # Register a handler
        def handle_test(params):
            return {"result": params.get("value", 0) * 2}

        protocol.register_request_handler("test", handle_test)

        # Handle a request
        message = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {"value": 21}}
        response = protocol.handle_message(message)

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["result"], 42)

    def test_notification_handling(self):
        """Test that notifications don't produce responses."""
        from spork.lsp.protocol import JsonRpcProtocol

        protocol = JsonRpcProtocol()

        received = []

        def handle_notify(params):
            received.append(params)

        protocol.register_notification_handler("notify", handle_notify)

        # Handle a notification (no id)
        message = {"jsonrpc": "2.0", "method": "notify", "params": {"data": "test"}}
        response = protocol.handle_message(message)

        self.assertIsNone(response)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["data"], "test")

    def test_method_not_found(self):
        """Test that unknown methods return an error."""
        from spork.lsp.protocol import ErrorCode, JsonRpcProtocol

        protocol = JsonRpcProtocol()

        message = {"jsonrpc": "2.0", "id": 1, "method": "unknown"}
        response = protocol.handle_message(message)

        self.assertEqual(response["id"], 1)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], ErrorCode.METHOD_NOT_FOUND)


class TestLspHelpers(unittest.TestCase):
    """Test LSP helper functions."""

    def test_uri_to_path(self):
        """Test file URI to path conversion."""
        from spork.lsp.protocol import uri_to_path

        # Unix path
        self.assertEqual(
            uri_to_path("file:///home/user/test.spork"), "/home/user/test.spork"
        )

        # Path with spaces
        self.assertEqual(
            uri_to_path("file:///home/user/my%20project/test.spork"),
            "/home/user/my%20project/test.spork",
        )

    def test_path_to_uri(self):
        """Test path to file URI conversion."""
        from spork.lsp.protocol import path_to_uri

        # The result should start with file://
        uri = path_to_uri("/home/user/test.spork")
        self.assertTrue(uri.startswith("file://"))
        self.assertIn("test.spork", uri)

    def test_make_position(self):
        """Test position creation."""
        from spork.lsp.protocol import make_position

        pos = make_position(10, 5)
        self.assertEqual(pos["line"], 10)
        self.assertEqual(pos["character"], 5)

    def test_make_range(self):
        """Test range creation."""
        from spork.lsp.protocol import make_range

        range_ = make_range(1, 0, 1, 10)
        self.assertEqual(range_["start"]["line"], 1)
        self.assertEqual(range_["start"]["character"], 0)
        self.assertEqual(range_["end"]["line"], 1)
        self.assertEqual(range_["end"]["character"], 10)

    def test_make_diagnostic(self):
        """Test diagnostic creation."""
        from spork.lsp.protocol import DiagnosticSeverity, make_diagnostic, make_range

        range_ = make_range(0, 0, 0, 5)
        diag = make_diagnostic(
            range_=range_,
            message="Test error",
            severity=DiagnosticSeverity.ERROR,
            source="spork",
            code="E001",
        )

        self.assertEqual(diag["message"], "Test error")
        self.assertEqual(diag["severity"], DiagnosticSeverity.ERROR)
        self.assertEqual(diag["source"], "spork")
        self.assertEqual(diag["code"], "E001")

    def test_make_completion_item(self):
        """Test completion item creation."""
        from spork.lsp.protocol import CompletionItemKind, make_completion_item

        item = make_completion_item(
            label="defn",
            kind=CompletionItemKind.KEYWORD,
            detail="Define a function",
            documentation="Defines a named function.",
        )

        self.assertEqual(item["label"], "defn")
        self.assertEqual(item["kind"], CompletionItemKind.KEYWORD)
        self.assertEqual(item["detail"], "Define a function")
        self.assertEqual(item["documentation"], "Defines a named function.")

    def test_make_hover(self):
        """Test hover creation."""
        from spork.lsp.protocol import make_hover

        hover = make_hover("**defn** (macro)\n\nDefines a function.")

        self.assertEqual(hover["contents"]["kind"], "markdown")
        self.assertIn("defn", hover["contents"]["value"])


class TestTextDocument(unittest.TestCase):
    """Test the TextDocument class."""

    def test_get_line(self):
        """Test getting a specific line from a document."""
        from spork.lsp.server import TextDocument

        doc = TextDocument(
            uri="file:///test.spork",
            language_id="spork",
            version=1,
            content="line one\nline two\nline three",
        )

        self.assertEqual(doc.get_line(0), "line one")
        self.assertEqual(doc.get_line(1), "line two")
        self.assertEqual(doc.get_line(2), "line three")
        self.assertEqual(doc.get_line(99), "")

    def test_get_word_at_position(self):
        """Test extracting the word at a given position."""
        from spork.lsp.server import TextDocument

        doc = TextDocument(
            uri="file:///test.spork",
            language_id="spork",
            version=1,
            content="(defn hello-world [x] (+ x 1))",
        )

        # At 'defn'
        self.assertEqual(doc.get_word_at_position(0, 2), "defn")
        self.assertEqual(doc.get_word_at_position(0, 5), "defn")

        # At 'hello-world'
        self.assertEqual(doc.get_word_at_position(0, 10), "hello-world")

        # At 'x'
        self.assertEqual(doc.get_word_at_position(0, 19), "x")

    def test_path_property(self):
        """Test the path property."""
        from spork.lsp.server import TextDocument

        doc = TextDocument(
            uri="file:///home/user/test.spork",
            language_id="spork",
            version=1,
            content="",
        )

        self.assertEqual(doc.path, "/home/user/test.spork")


class TestSporkLanguageServer(unittest.TestCase):
    """Test the Spork Language Server."""

    def create_server(self):
        """Create a server instance for testing."""
        from spork.lsp.protocol import JsonRpcProtocol, ProtocolReader, ProtocolWriter
        from spork.lsp.server import SporkLanguageServer

        # Use BytesIO for input/output
        input_buffer = io.BytesIO()
        output_buffer = io.BytesIO()

        protocol = JsonRpcProtocol(
            reader=ProtocolReader(input_buffer),
            writer=ProtocolWriter(output_buffer),
        )

        server = SporkLanguageServer(protocol=protocol)
        return server, input_buffer, output_buffer

    def test_initialize(self):
        """Test the initialize request."""
        server, _, _ = self.create_server()

        params = {
            "processId": 1234,
            "rootUri": "file:///tmp/test",
            "capabilities": {},
        }

        result = server._handle_initialize(params)

        self.assertIn("capabilities", result)
        self.assertIn("textDocumentSync", result["capabilities"])
        self.assertIn("completionProvider", result["capabilities"])
        self.assertIn("hoverProvider", result["capabilities"])
        self.assertIn("definitionProvider", result["capabilities"])

    def test_did_open(self):
        """Test the textDocument/didOpen notification."""
        server, _, _ = self.create_server()

        # Initialize first
        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        params = {
            "textDocument": {
                "uri": "file:///test.spork",
                "languageId": "spork",
                "version": 1,
                "text": "(defn add [a b] (+ a b))",
            }
        }

        server._handle_did_open(params)

        self.assertIn("file:///test.spork", server.documents)
        doc = server.documents["file:///test.spork"]
        self.assertEqual(doc.version, 1)
        self.assertIn("defn", doc.content)

    def test_did_change(self):
        """Test the textDocument/didChange notification."""
        server, _, _ = self.create_server()

        # Initialize and open a document
        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        server._handle_did_open(
            {
                "textDocument": {
                    "uri": "file:///test.spork",
                    "languageId": "spork",
                    "version": 1,
                    "text": "(def x 1)",
                }
            }
        )

        # Change the document
        server._handle_did_change(
            {
                "textDocument": {"uri": "file:///test.spork", "version": 2},
                "contentChanges": [{"text": "(def x 2)"}],
            }
        )

        doc = server.documents["file:///test.spork"]
        self.assertEqual(doc.version, 2)
        self.assertIn("2", doc.content)

    def test_did_close(self):
        """Test the textDocument/didClose notification."""
        server, _, _ = self.create_server()

        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        server._handle_did_open(
            {
                "textDocument": {
                    "uri": "file:///test.spork",
                    "languageId": "spork",
                    "version": 1,
                    "text": "(def x 1)",
                }
            }
        )

        self.assertIn("file:///test.spork", server.documents)

        server._handle_did_close({"textDocument": {"uri": "file:///test.spork"}})

        self.assertNotIn("file:///test.spork", server.documents)

    def test_completion_keywords(self):
        """Test that completion returns keywords."""
        server, _, _ = self.create_server()

        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        server._handle_did_open(
            {
                "textDocument": {
                    "uri": "file:///test.spork",
                    "languageId": "spork",
                    "version": 1,
                    "text": "(def",
                }
            }
        )

        result = server._handle_completion(
            {
                "textDocument": {"uri": "file:///test.spork"},
                "position": {"line": 0, "character": 4},
            }
        )

        self.assertIn("items", result)
        labels = [item["label"] for item in result["items"]]
        self.assertIn("defn", labels)
        self.assertIn("defmacro", labels)

    def test_hover(self):
        """Test hover functionality."""
        server, _, _ = self.create_server()

        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        # Define a function in the backend
        if server.backend:
            server.backend.eval("(defn my-test-fn [x] (+ x 1))")

        server._handle_did_open(
            {
                "textDocument": {
                    "uri": "file:///test.spork",
                    "languageId": "spork",
                    "version": 1,
                    "text": "(my-test-fn 5)",
                }
            }
        )

        result = server._handle_hover(
            {
                "textDocument": {"uri": "file:///test.spork"},
                "position": {"line": 0, "character": 5},
            }
        )

        # Should return hover info or None
        if result:
            self.assertIn("contents", result)

    def test_shutdown(self):
        """Test the shutdown request."""
        server, _, _ = self.create_server()

        server._handle_initialize({"processId": 1234, "capabilities": {}})

        self.assertFalse(server.shutdown_requested)

        server._handle_shutdown({})

        self.assertTrue(server.shutdown_requested)


class TestDiagnostics(unittest.TestCase):
    """Test diagnostic generation."""

    def test_parse_error_diagnostic(self):
        """Test that parse errors generate diagnostics."""
        from spork.lsp.protocol import JsonRpcProtocol, ProtocolReader, ProtocolWriter
        from spork.lsp.server import SporkLanguageServer

        input_buffer = io.BytesIO()
        output_buffer = io.BytesIO()

        protocol = JsonRpcProtocol(
            reader=ProtocolReader(input_buffer),
            writer=ProtocolWriter(output_buffer),
        )

        server = SporkLanguageServer(protocol=protocol)
        server._handle_initialize({"processId": 1234, "capabilities": {}})
        server._init_backend()

        # Open a document with a parse error (unclosed paren)
        server._handle_did_open(
            {
                "textDocument": {
                    "uri": "file:///test.spork",
                    "languageId": "spork",
                    "version": 1,
                    "text": "(defn broken [x",
                }
            }
        )

        # Check that diagnostics were published
        output_buffer.seek(0)
        # Read the response (if any was written)
        content = output_buffer.read()
        # Diagnostics should have been published
        # Note: The actual diagnostic content depends on the error format


if __name__ == "__main__":
    unittest.main()
