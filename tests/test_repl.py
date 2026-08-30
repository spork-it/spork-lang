import atexit
import sys
from types import SimpleNamespace

import pytest

from spork.repl.backend import TerminalRepl


def test_terminal_repl_keeps_readline_history_in_memory(monkeypatch):
    calls = []

    def fail_history_access(*args, **kwargs):
        pytest.fail("the terminal REPL must not access a history file")

    readline = SimpleNamespace(
        set_completer=lambda completer: calls.append(("completer", completer)),
        parse_and_bind=lambda binding: calls.append(("binding", binding)),
        read_history_file=fail_history_access,
        write_history_file=fail_history_access,
    )
    monkeypatch.setitem(sys.modules, "readline", readline)
    monkeypatch.setattr(atexit, "register", fail_history_access)

    repl = object.__new__(TerminalRepl)
    repl.setup_readline()

    assert repl.readline is readline
    assert calls == [("completer", repl.complete), ("binding", "tab: complete")]
