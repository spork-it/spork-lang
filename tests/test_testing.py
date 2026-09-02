import sys
from argparse import Namespace
from pathlib import Path

import pytest

from spork.cli import cmd_test
from spork.compiler import compile_file_to_python, compile_forms_to_code, eval_str
from spork.project import ProjectConfig, ProjectManager
from spork.project.scaffold import generate_test_spork
from spork.testing.discovery import (
    TestDiscoveryError as _TestDiscoveryError,
    discover_test_files,
    has_deftest,
)
from spork.testing.runner import run_test_file


def test_deftest_registers_without_running_and_preserves_metadata():
    env = eval_str(
        """(ns sample.core)
(def calls (list))

(deftest addition-works
  "Addition remains useful."
  (calls.append :ran)
  (assert (= (+ 2 3) 5)))
"""
    )

    assert env["calls"] == []
    assert len(env["__spork_tests__"]) == 1

    test = env["__spork_tests__"][0]
    assert test.name == "addition-works"
    assert test.qualified_name == "sample.core/addition-works"
    assert test.line == 4
    assert test.function.__doc__ == "Addition remains useful."

    test.function()
    assert len(env["calls"]) == 1


def test_deftest_can_pass_multiple_inline_anonymous_functions():
    source = """(defn invoke [function value] (function value))
(deftest anonymous-callbacks
  (assert (= (invoke (fn [value] (+ value 1)) 1) 2))
  (def second (invoke (fn [value] (+ value 2)) 1))
  (assert (= second 3)))
"""

    runtime_env = eval_str(source)
    runtime_env["__spork_tests__"][0].function()

    python_source, _ = compile_file_to_python(source, "anonymous_callbacks.spork")
    aot_env = {
        "__name__": "anonymous_callbacks",
        "__file__": "anonymous_callbacks.py",
    }
    exec(compile(python_source, "anonymous_callbacks.py", "exec"), aot_env, aot_env)
    aot_env["__spork_tests__"][0].function()


def test_deftest_can_define_a_local_generator_without_becoming_a_generator():
    env = eval_str(
        """(deftest local-generator
  (def generate (fn ^generator [] (yield 1) (yield 2)))
  (assert (= (vec (generate)) [1 2])))
"""
    )

    env["__spork_tests__"][0].function()


def test_deftest_is_private_in_aot_output():
    python_source, _ = compile_file_to_python(
        """(ns sample.aot)
(def answer 42)
(deftest answer-works
  (assert (= answer 42)))
""",
        "sample/aot.spork",
    )
    env = {"__name__": "sample.aot", "__file__": "sample/aot.py"}
    exec(compile(python_source, "sample/aot.py", "exec"), env, env)

    assert env["__all__"] == ["answer"]
    assert len(env["__spork_tests__"]) == 1
    assert "__spork_test_answer_works_1" in env


def test_deftest_rejects_invalid_placement_and_duplicate_normalized_names():
    with pytest.raises(SyntaxError, match="module top level"):
        compile_forms_to_code("(defn outer [] (deftest nested true))")

    with pytest.raises(SyntaxError, match="duplicate deftest name"):
        compile_forms_to_code(
            "(deftest same-name true)\n(deftest same_name true)"
        )

    with pytest.raises(SyntaxError, match="name must be symbol"):
        compile_forms_to_code('(deftest "not-a-symbol" true)')

    with pytest.raises(SyntaxError, match="invalid deftest name"):
        compile_forms_to_code("(deftest invalid.name true)")

    with pytest.raises(SyntaxError, match=r"only supports \^async"):
        compile_forms_to_code("(deftest ^generator unsupported (yield 1))")

    with pytest.raises(SyntaxError, match="requires a body"):
        compile_forms_to_code("(deftest empty)")

    with pytest.raises(SyntaxError, match="body after its docstring"):
        compile_forms_to_code('(deftest empty "docs only")')


def test_discovery_finds_only_files_with_declared_tests(tmp_path: Path):
    source_root = tmp_path / "src"
    test_root = tmp_path / "tests"
    source_root.mkdir()
    test_root.mkdir()

    inline = source_root / "core.spork"
    inline.write_text(
        "(ns sample.inline)\n(deftest inline-test (assert true))\n",
        encoding="utf-8",
    )
    (source_root / "plain.spork").write_text(
        '; (deftest commented-out true)\n(def text "(deftest in-a-string)")\n',
        encoding="utf-8",
    )
    undeclared = test_root / "test_undeclared.spork"
    undeclared.write_text("(assert true)\n", encoding="utf-8")
    declared = test_root / "arbitrary_name.spork"
    declared.write_text("(deftest declared (assert true))\n", encoding="utf-8")
    (test_root / "helper.spork").write_text("(def helper 1)\n", encoding="utf-8")

    discovered = discover_test_files([source_root], [test_root])
    by_name = {item.path.name: item for item in discovered}

    assert list(sorted(by_name)) == ["arbitrary_name.spork", "core.spork"]
    assert by_name["core.spork"].tests[0].name == "inline-test"
    assert by_name["core.spork"].tests[0].qualified_name == (
        "sample.inline/inline-test"
    )


def test_discovery_reports_invalid_source(tmp_path: Path):
    source = tmp_path / "broken.spork"
    source.write_text("(deftest broken", encoding="utf-8")

    with pytest.raises(_TestDiscoveryError, match="broken.spork"):
        has_deftest(source)


def test_native_runner_continues_after_failure_and_awaits_async_tests(
    tmp_path: Path, capsys
):
    test_file = tmp_path / "runner.spork"
    test_file.write_text(
        """(ns sample.runner
  (:import [asyncio]))
(def seen (list))

(deftest first
  (seen.append :first))

(deftest fails
  (assert false "intentional"))

(deftest ^async last
  (await (asyncio.sleep 0))
  (seen.append :last)
  (assert (= (len seen) 2)))
""",
        encoding="utf-8",
    )

    summary = run_test_file(test_file)
    output = capsys.readouterr().out

    assert summary.passed == 2
    assert summary.failed == 1
    assert "[pass] sample.runner/first" in output
    assert "[fail] sample.runner/fails" in output
    assert "[pass] sample.runner/last" in output
    assert "runner.spork" in output
    assert "line 9" in output
    assert "AssertionError: intentional" in output


def test_native_runner_selects_exact_names_and_substring_filters(
    tmp_path: Path, capsys
):
    test_file = tmp_path / "runner_filter.spork"
    test_file.write_text(
        """(ns sample.filter)
(deftest worker-starts (assert true))
(deftest worker-stops (assert true))
(deftest parser-starts (assert false))
""",
        encoding="utf-8",
    )

    exact = run_test_file(
        test_file, test_names={"sample.filter/worker-starts"}
    )
    exact_output = capsys.readouterr().out
    filtered = run_test_file(test_file, filter_pattern="worker")
    filtered_output = capsys.readouterr().out

    assert (exact.selected, exact.passed, exact.failed) == (1, 1, 0)
    assert "worker-starts" in exact_output
    assert "worker-stops" not in exact_output
    assert (filtered.selected, filtered.passed, filtered.failed) == (2, 2, 0)
    assert "worker-starts" in filtered_output
    assert "worker-stops" in filtered_output
    assert "parser-starts" not in filtered_output


def test_native_runner_rejects_files_without_declarations(tmp_path: Path, capsys):
    test_file = tmp_path / "test_undeclared.spork"
    test_file.write_text("(def value 42)\n", encoding="utf-8")

    summary = run_test_file(test_file)

    assert summary.passed == 0
    assert summary.failed == 1
    assert "[error] no declared tests found" in capsys.readouterr().out


class _FakeConfig:
    def __init__(self, root: Path):
        self.project_root = str(root)
        self.venv_python = sys.executable
        self.api = None

    def get_absolute_source_paths(self) -> list[str]:
        return [str(Path(self.project_root) / "src")]

    def get_absolute_test_paths(self) -> list[str]:
        return [str(Path(self.project_root) / "tests")]


def _configure_cli_project(monkeypatch, root: Path) -> None:
    config = _FakeConfig(root)
    monkeypatch.setattr(ProjectConfig, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(ProjectManager, "has_venv", lambda self: True)
    monkeypatch.setattr(ProjectManager, "inject_venv_paths", lambda self: None)


def test_spork_test_runs_declared_tests_but_ignores_python_tests(
    tmp_path: Path, monkeypatch, capsys
):
    source_root = tmp_path / "src"
    test_root = tmp_path / "tests"
    source_root.mkdir()
    test_root.mkdir()
    (source_root / "core.spork").write_text(
        "(ns sample.core)\n(deftest inline (assert (= 2 2)))\n",
        encoding="utf-8",
    )
    (test_root / "core_test.spork").write_text(
        "(deftest test-path-declaration (assert (= 3 3)))\n", encoding="utf-8"
    )
    (test_root / "test_ignored.py").write_text(
        "def test_failure():\n    assert False\n", encoding="utf-8"
    )
    _configure_cli_project(monkeypatch, tmp_path)

    result = cmd_test(Namespace())
    output = capsys.readouterr().out

    assert result == 0
    assert "Passed: 2" in output
    assert "Failed: 0" in output
    assert "Files:  2" in output


def test_spork_test_targets_a_specific_file(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / "src").mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    selected = tests / "selected.spork"
    selected.write_text("(deftest selected (assert true))\n", encoding="utf-8")
    (tests / "not_selected.spork").write_text(
        "(deftest not-selected (assert false))\n", encoding="utf-8"
    )
    _configure_cli_project(monkeypatch, tmp_path)

    result = cmd_test(Namespace(targets=[str(selected)]))
    output = capsys.readouterr().out

    assert result == 0
    assert "Passed: 1" in output
    assert "Failed: 0" in output
    assert "Files:  1" in output


def test_spork_test_targets_an_individual_test(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / "src").mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "selection.spork"
    test_file.write_text(
        """(ns sample.selection)
(deftest wanted (assert true))
(deftest unwanted (assert false))
""",
        encoding="utf-8",
    )
    _configure_cli_project(monkeypatch, tmp_path)

    result = cmd_test(Namespace(targets=[f"{test_file}::wanted"]))
    output = capsys.readouterr().out

    assert result == 0
    assert "Passed: 1" in output
    assert "Failed: 0" in output


def test_spork_test_filters_test_names_across_files(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / "src").mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "worker.spork").write_text(
        "(deftest worker-starts (assert true))\n", encoding="utf-8"
    )
    (tests / "parser.spork").write_text(
        "(deftest parser-starts (assert false))\n", encoding="utf-8"
    )
    _configure_cli_project(monkeypatch, tmp_path)

    result = cmd_test(Namespace(filter_pattern="worker"))
    output = capsys.readouterr().out

    assert result == 0
    assert "Passed: 1" in output
    assert "Failed: 0" in output
    assert "Files:  1" in output


def test_spork_test_aggregates_declared_failures(
    tmp_path: Path, monkeypatch, capsys
):
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "tests").mkdir()
    (source_root / "core.spork").write_text(
        """(ns sample.failure)
(deftest fails (assert false "boom"))
(deftest continues (assert true))
""",
        encoding="utf-8",
    )
    _configure_cli_project(monkeypatch, tmp_path)

    result = cmd_test(Namespace())
    output = capsys.readouterr().out

    assert result == 1
    assert "Passed: 1" in output
    assert "Failed: 1" in output
    assert "Files:  1" in output


def test_spork_test_reports_no_python_only_projects_as_empty(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / "src").mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_only.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    _configure_cli_project(monkeypatch, tmp_path)

    assert cmd_test(Namespace()) == 1
    assert "No matching Spork tests found." in capsys.readouterr().err


def test_scaffold_uses_deftest_without_manual_runner():
    generated = generate_test_spork("hello-spork")

    assert "(deftest greet-works" in generated
    assert "run-tests" not in generated
    assert "(test-greet)" not in generated
