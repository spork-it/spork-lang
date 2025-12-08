"""
spork.lsp.protocol - JSON-RPC 2.0 Protocol Implementation for LSP

This module provides low-level JSON-RPC 2.0 protocol handling for the
Language Server Protocol. It handles:
- Message framing with Content-Length headers
- JSON-RPC request/response/notification patterns
- Reading from stdin and writing to stdout
- Error handling according to JSON-RPC spec

The LSP uses JSON-RPC 2.0 over stdio with HTTP-style headers:
    Content-Length: <length>\r\n
    \r\n
    <JSON body>
"""

import json
import sys
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional, Union

# =============================================================================
# JSON-RPC Error Codes
# =============================================================================


class ErrorCode(IntEnum):
    """JSON-RPC and LSP error codes."""

    # JSON-RPC defined errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # LSP defined errors
    SERVER_NOT_INITIALIZED = -32002
    UNKNOWN_ERROR_CODE = -32001

    # LSP request errors
    REQUEST_CANCELLED = -32800
    CONTENT_MODIFIED = -32801


class JsonRpcError(Exception):
    """Exception representing a JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-RPC error object."""
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            error["data"] = self.data
        return error


# =============================================================================
# Message Types
# =============================================================================


@dataclass
class Request:
    """A JSON-RPC request message."""

    id: Union[int, str]
    method: str
    params: Optional[dict[str, Any]] = None


@dataclass
class Response:
    """A JSON-RPC response message."""

    id: Union[int, str, None]
    result: Any = None
    error: Optional[dict[str, Any]] = None


@dataclass
class Notification:
    """A JSON-RPC notification message (no id, no response expected)."""

    method: str
    params: Optional[dict[str, Any]] = None


Message = Union[Request, Response, Notification]


# =============================================================================
# Protocol Transport
# =============================================================================


class ProtocolReader:
    """
    Reads LSP messages from an input stream.

    LSP messages have HTTP-style headers followed by a JSON body:
        Content-Length: <length>\r\n
        \r\n
        <JSON body>
    """

    def __init__(self, input_stream=None):
        """
        Initialize the reader.

        Args:
            input_stream: The input stream to read from (default: sys.stdin.buffer)
        """
        self.input = input_stream or sys.stdin.buffer
        self._lock = threading.Lock()

    def read_message(self) -> Optional[dict[str, Any]]:
        """
        Read and parse a single LSP message.

        Returns:
            The parsed JSON message as a dict, or None if EOF.

        Raises:
            JsonRpcError: If the message is malformed.
        """
        with self._lock:
            try:
                # Read headers
                content_length = self._read_headers()
                if content_length is None:
                    return None

                # Read body
                body = self.input.read(content_length)
                if len(body) < content_length:
                    return None

                # Parse JSON
                try:
                    return json.loads(body.decode("utf-8"))
                except json.JSONDecodeError as e:
                    raise JsonRpcError(
                        ErrorCode.PARSE_ERROR,
                        f"Invalid JSON: {e}",
                    )

            except Exception as e:
                if isinstance(e, JsonRpcError):
                    raise
                raise JsonRpcError(
                    ErrorCode.INTERNAL_ERROR,
                    f"Error reading message: {e}",
                )

    def _read_headers(self) -> Optional[int]:
        """
        Read LSP headers and return the Content-Length.

        Returns:
            The content length, or None if EOF.
        """
        content_length = None

        while True:
            line = self.input.readline()
            if not line:
                return None

            line = line.decode("ascii").strip()

            if not line:
                # Empty line marks end of headers
                break

            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise JsonRpcError(
                        ErrorCode.PARSE_ERROR,
                        f"Invalid Content-Length: {line}",
                    )
            # Ignore other headers (like Content-Type)

        if content_length is None:
            raise JsonRpcError(
                ErrorCode.PARSE_ERROR,
                "Missing Content-Length header",
            )

        return content_length


class ProtocolWriter:
    """
    Writes LSP messages to an output stream.

    Formats messages with proper Content-Length headers.
    """

    def __init__(self, output_stream=None):
        """
        Initialize the writer.

        Args:
            output_stream: The output stream to write to (default: sys.stdout.buffer)
        """
        self.output = output_stream or sys.stdout.buffer
        self._lock = threading.Lock()

    def write_message(self, message: dict[str, Any]) -> None:
        """
        Write a JSON-RPC message with proper LSP framing.

        Args:
            message: The message to write as a dict.
        """
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")

        with self._lock:
            self.output.write(header)
            self.output.write(body)
            self.output.flush()


# =============================================================================
# JSON-RPC Protocol Handler
# =============================================================================


@dataclass
class JsonRpcProtocol:
    """
    High-level JSON-RPC protocol handler.

    Handles dispatching requests to registered handlers and
    managing the request/response lifecycle.
    """

    reader: ProtocolReader = field(default_factory=ProtocolReader)
    writer: ProtocolWriter = field(default_factory=ProtocolWriter)

    # Request handlers: method -> callable
    _request_handlers: dict[str, Callable] = field(default_factory=dict)

    # Notification handlers: method -> callable
    _notification_handlers: dict[str, Callable] = field(default_factory=dict)

    # Pending requests (for client mode): id -> callback
    _pending_requests: dict[Union[int, str], Callable] = field(default_factory=dict)

    # Request ID counter for outgoing requests
    _next_id: int = 1
    _id_lock: threading.Lock = field(default_factory=threading.Lock)

    def register_request_handler(
        self, method: str, handler: Callable[[dict], Any]
    ) -> None:
        """
        Register a handler for a request method.

        The handler receives the params dict and should return a result
        or raise JsonRpcError.

        Args:
            method: The JSON-RPC method name.
            handler: The handler function.
        """
        self._request_handlers[method] = handler

    def register_notification_handler(
        self, method: str, handler: Callable[[dict], None]
    ) -> None:
        """
        Register a handler for a notification method.

        The handler receives the params dict and should not return anything.

        Args:
            method: The JSON-RPC method name.
            handler: The handler function.
        """
        self._notification_handlers[method] = handler

    def handle_message(self, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Handle an incoming JSON-RPC message.

        Args:
            message: The parsed JSON message.

        Returns:
            A response message if the input was a request, None otherwise.
        """
        # Check if it's a response to a pending request
        if "result" in message or "error" in message:
            return self._handle_response(message)

        # Check if it's a request or notification
        method = message.get("method")
        if method is None:
            return self._make_error_response(
                message.get("id"),
                ErrorCode.INVALID_REQUEST,
                "Missing method field",
            )

        msg_id = message.get("id")
        params = message.get("params", {})

        if msg_id is not None:
            # It's a request
            return self._handle_request(msg_id, method, params)
        else:
            # It's a notification
            self._handle_notification(method, params)
            return None

    def _handle_request(
        self,
        msg_id: Union[int, str],
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle an incoming request."""
        handler = self._request_handlers.get(method)

        if handler is None:
            return self._make_error_response(
                msg_id,
                ErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

        try:
            result = handler(params)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result,
            }
        except JsonRpcError as e:
            return self._make_error_response(msg_id, e.code, e.message, e.data)
        except Exception as e:
            return self._make_error_response(
                msg_id,
                ErrorCode.INTERNAL_ERROR,
                str(e),
            )

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        """Handle an incoming notification."""
        handler = self._notification_handlers.get(method)

        if handler is not None:
            try:
                handler(params)
            except Exception:
                # Notifications don't get responses, so we just log/ignore errors
                pass

    def _handle_response(self, message: dict[str, Any]) -> None:
        """Handle a response to a pending request."""
        msg_id = message.get("id")
        if msg_id is not None and msg_id in self._pending_requests:
            callback = self._pending_requests.pop(msg_id)
            if "error" in message:
                callback(None, message["error"])
            else:
                callback(message.get("result"), None)
        return None

    def _make_error_response(
        self,
        msg_id: Optional[Union[int, str]],
        code: int,
        message: str,
        data: Any = None,
    ) -> dict[str, Any]:
        """Create a JSON-RPC error response."""
        error: dict[str, Any] = {
            "code": code,
            "message": message,
        }
        if data is not None:
            error["data"] = data

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": error,
        }

    def send_notification(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> None:
        """
        Send a notification to the client.

        Args:
            method: The notification method name.
            params: Optional parameters.
        """
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params

        self.writer.write_message(message)

    def send_request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        callback: Optional[Callable[[Any, Any], None]] = None,
    ) -> Union[int, str]:
        """
        Send a request to the client.

        Args:
            method: The request method name.
            params: Optional parameters.
            callback: Optional callback for the response (result, error).

        Returns:
            The request ID.
        """
        with self._id_lock:
            msg_id = self._next_id
            self._next_id += 1

        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        if callback is not None:
            self._pending_requests[msg_id] = callback

        self.writer.write_message(message)
        return msg_id

    def run(self) -> None:
        """
        Run the protocol handler main loop.

        Reads messages from the input stream and dispatches them
        to registered handlers. Continues until EOF or an error.
        """
        while True:
            try:
                message = self.reader.read_message()
                if message is None:
                    # EOF
                    break

                response = self.handle_message(message)
                if response is not None:
                    self.writer.write_message(response)

            except JsonRpcError as e:
                # Protocol-level error
                error_response = self._make_error_response(
                    None, e.code, e.message, e.data
                )
                self.writer.write_message(error_response)
            except Exception:
                # Unexpected error, try to keep going
                pass


# =============================================================================
# LSP-Specific Types
# =============================================================================


class DiagnosticSeverity(IntEnum):
    """LSP diagnostic severity levels."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


class CompletionItemKind(IntEnum):
    """LSP completion item kinds."""

    TEXT = 1
    METHOD = 2
    FUNCTION = 3
    CONSTRUCTOR = 4
    FIELD = 5
    VARIABLE = 6
    CLASS = 7
    INTERFACE = 8
    MODULE = 9
    PROPERTY = 10
    UNIT = 11
    VALUE = 12
    ENUM = 13
    KEYWORD = 14
    SNIPPET = 15
    COLOR = 16
    FILE = 17
    REFERENCE = 18
    FOLDER = 19
    ENUM_MEMBER = 20
    CONSTANT = 21
    STRUCT = 22
    EVENT = 23
    OPERATOR = 24
    TYPE_PARAMETER = 25


class SymbolKind(IntEnum):
    """LSP symbol kinds."""

    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26


class TextDocumentSyncKind(IntEnum):
    """LSP text document sync kinds."""

    NONE = 0
    FULL = 1
    INCREMENTAL = 2


# =============================================================================
# LSP Helper Functions
# =============================================================================


def make_position(line: int, character: int) -> dict[str, int]:
    """Create an LSP Position object (0-based line and character)."""
    return {"line": line, "character": character}


def make_range(
    start_line: int, start_char: int, end_line: int, end_char: int
) -> dict[str, Any]:
    """Create an LSP Range object."""
    return {
        "start": make_position(start_line, start_char),
        "end": make_position(end_line, end_char),
    }


def make_location(uri: str, range_: dict[str, Any]) -> dict[str, Any]:
    """Create an LSP Location object."""
    return {"uri": uri, "range": range_}


def make_diagnostic(
    range_: dict[str, Any],
    message: str,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    source: str = "spork",
    code: Optional[Union[int, str]] = None,
) -> dict[str, Any]:
    """Create an LSP Diagnostic object."""
    diagnostic: dict[str, Any] = {
        "range": range_,
        "message": message,
        "severity": severity,
        "source": source,
    }
    if code is not None:
        diagnostic["code"] = code
    return diagnostic


def make_completion_item(
    label: str,
    kind: CompletionItemKind = CompletionItemKind.TEXT,
    detail: Optional[str] = None,
    documentation: Optional[str] = None,
    insert_text: Optional[str] = None,
) -> dict[str, Any]:
    """Create an LSP CompletionItem object."""
    item: dict[str, Any] = {
        "label": label,
        "kind": kind,
    }
    if detail is not None:
        item["detail"] = detail
    if documentation is not None:
        item["documentation"] = documentation
    if insert_text is not None:
        item["insertText"] = insert_text
    return item


def make_hover(
    contents: str, range_: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Create an LSP Hover object."""
    hover: dict[str, Any] = {
        "contents": {"kind": "markdown", "value": contents},
    }
    if range_ is not None:
        hover["range"] = range_
    return hover


def uri_to_path(uri: str) -> str:
    """Convert a file URI to a file path."""
    if uri.startswith("file://"):
        path = uri[7:]
        # Handle Windows paths (file:///C:/...)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    return uri


def path_to_uri(path: str) -> str:
    """Convert a file path to a file URI."""
    import os

    # Normalize the path
    path = os.path.abspath(path)

    # Handle Windows paths
    if os.name == "nt":
        path = "/" + path.replace("\\", "/")

    return f"file://{path}"
