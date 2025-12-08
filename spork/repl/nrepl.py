"""
Spork nREPL Server - Network REPL for editor integration.

This provides a network-based REPL server that editors and tools can connect to.
Compatible with nREPL protocol conventions.
"""

import json
import socket
import sys
import threading
import uuid
from typing import Any, Optional

from spork.repl.backend import NReplProtocol, ReplBackend


class NReplServer:
    """
    Network REPL server for editor integration.

    This server listens on a port and handles nREPL-style messages
    for code evaluation, completion, and documentation.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7888):
        """
        Initialize the nREPL server.

        Args:
            host: The host to bind to.
            port: The port to listen on.
        """
        self.host = host
        self.port = port
        self.sessions: dict[str, ReplBackend] = {}
        self.socket = None
        self.running = False

    def create_session(self) -> str:
        """
        Create a new REPL session.

        Returns:
            The session ID.
        """
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = ReplBackend()
        return session_id

    def get_or_create_session(
        self, session_id: Optional[str]
    ) -> tuple[str, ReplBackend]:
        """
        Get an existing session or create a new one.

        Args:
            session_id: Optional session ID.

        Returns:
            A tuple of (session_id, backend).
        """
        if session_id and session_id in self.sessions:
            return session_id, self.sessions[session_id]

        new_session_id = self.create_session()
        return new_session_id, self.sessions[new_session_id]

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        Handle an incoming nREPL message.

        Args:
            message: The message dictionary.

        Returns:
            A response dictionary.
        """
        try:
            # Debug logging - raw message
            print(f"[nREPL] RAW MESSAGE: {message}", file=sys.stderr)
            sys.stderr.flush()

            op = message.get("op")
            msg_id = message.get("id")
            session = message.get("session")

            # Debug logging
            print(
                f"[nREPL] Message: op={op}, session={session}, id={msg_id}",
                file=sys.stderr,
            )
            sys.stderr.flush()

            response = {"id": msg_id}

            if op == "clone":
                # Create a new session
                new_session = self.create_session()
                print(f"[nREPL] Created new session: {new_session}", file=sys.stderr)
                sys.stderr.flush()
                print(
                    f"[nREPL] Active sessions: {list(self.sessions.keys())}",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                response["new-session"] = new_session
                response["status"] = ["done"]

            elif op == "close":
                # Close a session
                print(f"[nREPL] Closing session: {session}", file=sys.stderr)
                sys.stderr.flush()
                if session in self.sessions:
                    del self.sessions[session]
                response["status"] = ["done", "session-closed"]

            elif op == "eval":
                # Evaluate code
                code = message.get("code", "")
                file_path = message.get("file", None)  # Source file path
                ns = message.get("ns", None)  # Namespace context
                print(f"[nREPL] Requested session: {session}", file=sys.stderr)
                sys.stderr.flush()
                print(
                    f"[nREPL] Available sessions: {list(self.sessions.keys())}",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                session_id, backend = self.get_or_create_session(session)

                # Debug logging
                print(
                    f"[nREPL] Using session {session_id} (same as requested: {session_id == session})",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                print(f"[nREPL] Eval code: {code[:80]}...", file=sys.stderr)
                if file_path:
                    print(f"[nREPL] File: {file_path}", file=sys.stderr)
                if ns:
                    print(f"[nREPL] Namespace: {ns}", file=sys.stderr)
                sys.stderr.flush()
                env_keys = [
                    k for k in backend.state.env.keys() if not k.startswith("__")
                ]
                print(
                    f"[nREPL] Backend env has {len(backend.state.env)} keys, non-__ keys: {env_keys[:10]}",
                    file=sys.stderr,
                )
                print(
                    f"[nREPL] Backend ID: {id(backend)}, State ID: {id(backend.state)}, Env ID: {id(backend.state.env)}",
                    file=sys.stderr,
                )
                sys.stderr.flush()

                protocol = NReplProtocol(backend)
                result = protocol.handle_eval(
                    code,
                    session_id,
                    file_path=file_path,
                    ns=ns,  # type: ignore[call-arg]
                )

                # Debug logging after eval
                env_keys_after = [
                    k for k in backend.state.env.keys() if not k.startswith("__")
                ]
                print(
                    f"[nREPL] After eval, non-__ env keys: {env_keys_after[:10]}",
                    file=sys.stderr,
                )
                print(
                    f"[nREPL] After eval - Backend ID: {id(backend)}, State ID: {id(backend.state)}, Env ID: {id(backend.state.env)}",
                    file=sys.stderr,
                )
                sys.stderr.flush()

                response.update(result)
                # Include current namespace in response
                response["ns"] = backend.state.namespace

            elif op == "load-file":
                # Load a file
                file_content = message.get("file", "")
                file_path = message.get("file-path", "<loaded-file>")

                session_id, backend = self.get_or_create_session(session)
                protocol = NReplProtocol(backend)

                result = protocol.handle_eval(
                    file_content,
                    session_id,
                    file_path=file_path,  # type: ignore[call-arg]
                )
                response.update(result)
                # Include current namespace in response
                response["ns"] = backend.state.namespace

            elif op == "complete":
                # Auto-completion
                prefix = message.get("prefix", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_complete(prefix)
                response.update(result)

            elif op == "info":
                # Get symbol info (rich metadata)
                symbol = message.get("symbol", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_info(symbol)
                response.update(result)

            elif op == "macroexpand":
                # Macroexpand code
                code = message.get("code", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_macroexpand(code)
                response.update(result)

            elif op == "transpile":
                # Transpile Spork code to Python
                code = message.get("code", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_transpile(code)
                response.update(result)

            elif op == "find-def":
                # Find definition location
                symbol = message.get("symbol", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_find_def(symbol)
                response.update(result)

            elif op == "inspect-start":
                # Start inspector session
                code = message.get("code", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_inspect_start(code)
                response.update(result)

            elif op == "inspect-nav":
                # Navigate in inspector
                handle = message.get("handle", 0)
                path = message.get("path", [])
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_inspect_nav(handle, path)
                response.update(result)

            elif op == "protocols":
                # Get all registered protocols
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_protocols()
                response.update(result)

            elif op == "using-ns":
                # Switch to a namespace
                ns_name = message.get("ns", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_using_ns(ns_name)
                response.update(result)

            elif op == "ns-list":
                # List all loaded namespaces
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_ns_list()
                response.update(result)

            elif op == "ns-info":
                # Get info about a namespace
                ns_name = message.get("ns", "")
                session_id, backend = self.get_or_create_session(session)

                protocol = NReplProtocol(backend)
                result = protocol.handle_ns_info(ns_name)
                response.update(result)

            elif op == "describe":
                # Describe the server
                response["versions"] = {
                    "spork": {"version-string": "0.1.0"},
                    "python": {"version-string": "3.x"},
                }
                response["ops"] = {
                    "clone": {},
                    "close": {},
                    "eval": {},
                    "load-file": {},
                    "complete": {},
                    "info": {},
                    "describe": {},
                    "macroexpand": {},
                    "find-def": {},
                    "inspect-start": {},
                    "inspect-nav": {},
                    "protocols": {},
                    "using-ns": {},
                    "ns-list": {},
                    "ns-info": {},
                }
                response["status"] = ["done"]

            else:
                response["status"] = ["error", "unknown-op"]
                response["error"] = f"Unknown operation: {op}"

            print(f"[nREPL] Returning response: {response}", file=sys.stderr)
            sys.stderr.flush()
            return response

        except Exception as e:
            print(f"[nREPL] EXCEPTION in handle_message: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return {
                "id": message.get("id"),
                "status": ["error"],
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

    def handle_client(self, client_socket: socket.socket, addr):
        """
        Handle a client connection.

        Args:
            client_socket: The client socket.
            addr: The client address.
        """
        print(f"Client connected from {addr}")
        buffer = b""

        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break

                buffer += data

                # Process complete messages (newline-delimited JSON)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)

                    if not line.strip():
                        continue

                    try:
                        message = json.loads(line.decode("utf-8"))
                        response = self.handle_message(message)

                        # Send response as JSON
                        response_json = json.dumps(response) + "\n"
                        client_socket.sendall(response_json.encode("utf-8"))

                    except json.JSONDecodeError as e:
                        error_response = {
                            "status": ["error"],
                            "error": f"Invalid JSON: {e}",
                        }
                        client_socket.sendall(
                            (json.dumps(error_response) + "\n").encode("utf-8")
                        )
                    except Exception as e:
                        error_response = {
                            "status": ["error"],
                            "error": str(e),
                        }
                        client_socket.sendall(
                            (json.dumps(error_response) + "\n").encode("utf-8")
                        )

        except Exception as e:
            print(f"Error handling client {addr}: {e}")
        finally:
            client_socket.close()
            print(f"Client disconnected from {addr}")

    def start(self):
        """Start the nREPL server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)
        self.running = True

        print(f"Spork nREPL server started on {self.host}:{self.port}")

        # Write port file for editors
        with open(".nrepl-port", "w") as f:
            f.write(str(self.port))

        try:
            while self.running:
                try:
                    client_socket, addr = self.socket.accept()
                    client_thread = threading.Thread(
                        target=self.handle_client, args=(client_socket, addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except OSError:
                    if not self.running:
                        break
                    raise
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stop()

    def stop(self):
        """Stop the nREPL server."""
        self.running = False
        if self.socket:
            self.socket.close()
        print("Server stopped.")


class SimpleNReplClient:
    """
    A simple nREPL client for testing and scripting.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7888):
        """
        Initialize the client.

        Args:
            host: The host to connect to.
            port: The port to connect to.
        """
        self.host = host
        self.port = port
        self.socket = None
        self.session = None
        self.msg_counter = 0

    def connect(self):
        """Connect to the nREPL server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))

        # Create a session
        response = self.send_message({"op": "clone"})
        self.session = response.get("new-session")
        print(f"Connected to {self.host}:{self.port}")
        print(f"Session: {self.session}")

    def send_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        Send a message and receive the response.

        Args:
            message: The message to send.

        Returns:
            The response dictionary.
        """
        if not self.socket:
            raise RuntimeError("Not connected")

        # Add message ID
        self.msg_counter += 1
        message["id"] = str(self.msg_counter)

        # Add session if we have one
        if self.session and "session" not in message:
            message["session"] = self.session

        # Send message
        message_json = json.dumps(message) + "\n"
        self.socket.sendall(message_json.encode("utf-8"))

        # Receive response
        buffer = b""
        while True:
            data = self.socket.recv(4096)
            if not data:
                raise RuntimeError("Connection closed")

            buffer += data
            if b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                return json.loads(line.decode("utf-8"))

    def eval(self, code: str) -> Any:
        """
        Evaluate code on the server.

        Args:
            code: The code to evaluate.

        Returns:
            The evaluation result.
        """
        response = self.send_message({"op": "eval", "code": code})
        return response

    def complete(self, prefix: str) -> list[str]:
        """
        Get completions for a prefix.

        Args:
            prefix: The prefix to complete.

        Returns:
            A list of completions.
        """
        response = self.send_message({"op": "complete", "prefix": prefix})
        return response.get("completions", [])

    def close(self):
        """Close the connection."""
        if self.socket:
            try:
                self.send_message({"op": "close"})
            except Exception:
                pass
            self.socket.close()
            self.socket = None
            print("Disconnected.")


def main():
    """Main entry point for the nREPL server."""
    import argparse

    parser = argparse.ArgumentParser(description="Spork nREPL Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=7888, help="Port to listen on")
    parser.add_argument(
        "--client", action="store_true", help="Run as a test client instead"
    )

    args = parser.parse_args()

    if args.client:
        # Run as client
        client = SimpleNReplClient(args.host, args.port)
        try:
            client.connect()

            print("\nSimple nREPL Client")
            print("Type code to evaluate, or :quit to exit\n")

            while True:
                try:
                    code = input("client> ")
                    if code.strip() == ":quit":
                        break
                    if not code.strip():
                        continue

                    response = client.eval(code)

                    if "value" in response:
                        print(f"=> {response['value']}")
                    elif "error" in response:
                        print(f"Error: {response['error']}")

                except EOFError:
                    break
                except KeyboardInterrupt:
                    print()
                    continue
                except Exception as e:
                    print(f"Error: {e}")
        finally:
            client.close()
    else:
        # Run as server
        server = NReplServer(args.host, args.port)
        server.start()


if __name__ == "__main__":
    main()
