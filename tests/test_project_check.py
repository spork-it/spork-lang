"""Project-wide checks, diagnostics, and CLI output."""

from __future__ import annotations

import json
from pathlib import Path

from spork.cli import _main, create_parser
from spork.project.check import (
    COMPILE_ERROR,
    DUPLICATE_NAMESPACE,
    INVALID_API,
    INVALID_MAIN,
    MISSING_EXPORT,
    MISSING_SOURCE_ROOT,
    NO_SOURCE_FILES,
    MISSING_NAMESPACE,
    NAMESPACE_MISMATCH,
    PARSE_ERROR,
    UNRESOLVED_NAMESPACE,
    UNRESOLVED_PYTHON_MODULE,
    check_project,
    expected_namespace_for_path,
)
from spork.project.config import ProjectConfig


def write_project(root: Path, *, invalid_test: bool = False) -> Path:
    (root / "src" / "sample_app").mkdir(parents=True)
    (root / "tests" / "sample_app").mkdir(parents=True)
    (root / "spork.it").write_text(
        """{:name "sample-app"
 :version "0.1.0"
 :source-paths ["src"]
 :test-paths ["tests"]
 :main "sample-app.core:main"
 :api {:from "sample-app.core"
       :spork {:namespace "sample-app" :exports ["main" "result"]}
       :python {:package "sample-app" :exports ["main" "result"] :typed true}}}
""",
        encoding="utf-8",
    )
    (root / "src" / "sample_app" / "util.spork").write_text(
        """(ns sample-app.util)
(def answer 42)
""",
        encoding="utf-8",
    )
    (root / "src" / "sample_app" / "helpers.py").write_text(
        "def serialize(value):\n    return str(value)\n", encoding="utf-8"
    )
    (root / "src" / "sample_app" / "core.spork").write_text(
        """(ns sample-app.core
  (:require [sample-app.util :refer [answer]])
  (:import [sample_app.helpers :refer [serialize]]))
(def result (serialize {:answer answer}))
(defn main [] 0)
""",
        encoding="utf-8",
    )
    test_source = (
        "(ns sample-app.core-test (:require [sample-app :as app]))\n"
        "(deftest public-api-works (assert (= (app.main) 0)))\n"
    )
    if invalid_test:
        test_source = "(ns sample-app.core-test\n"
    (root / "tests" / "sample_app" / "core.spork").write_text(
        test_source,
        encoding="utf-8",
    )
    return root


def test_expected_namespace_uses_hyphens_and_package_initializers(tmp_path: Path):
    root = tmp_path / "src"
    assert (
        expected_namespace_for_path(root / "my_app" / "core_test.spork", root)
        == "my-app.core-test"
    )
    assert (
        expected_namespace_for_path(root / "my_app" / "__init__.spork", root)
        == "my-app"
    )


def test_check_validates_sources_tests_generated_api_and_compilation(tmp_path: Path):
    project = write_project(tmp_path)

    result = check_project(ProjectConfig.load(str(project)))

    assert result.success
    assert result.files_checked == 3
    assert result.namespaces_checked == 4
    assert result.diagnostics == []
    assert not (project / ".spork-out").exists()
    assert result.index.namespaces["sample-app.core"].definitions["main"].kind == "function"
    assert result.to_dict()["success"] is True


def test_check_never_executes_ordinary_required_module_forms(tmp_path: Path):
    project = write_project(tmp_path)
    marker = project / "executed.txt"
    util = project / "src" / "sample_app" / "util.spork"
    util.write_text(
        f"""(ns sample-app.util
  (:import [pathlib :refer [Path]]))
(def answer 42)
(defmacro twice [value] `(* 2 ~value))
(.write-text (Path {json.dumps(str(marker))}) "should not run")
""",
        encoding="utf-8",
    )
    (project / "src" / "sample_app" / "core.spork").write_text(
        """(ns sample-app.core
  (:require [sample-app.util :refer [answer twice]]))
(def result (twice answer))
(defn main [] 0)
""",
        encoding="utf-8",
    )

    from spork.compiler.macros import MACRO_EXEC_ENV

    assert "twice" not in MACRO_EXEC_ENV
    result = check_project(ProjectConfig.load(str(project)))

    assert result.success
    assert not marker.exists()
    assert "twice" not in MACRO_EXEC_ENV


def test_check_resolves_python_submodules_without_importing_packages(tmp_path: Path):
    package = tmp_path / "src" / "safe_app"
    support = tmp_path / "src" / "python_support"
    package.mkdir(parents=True)
    support.mkdir(parents=True)
    marker = tmp_path / "python-imported.txt"
    (tmp_path / "spork.it").write_text(
        '{:name "safe-app" :version "0.1.0" :source-paths ["src"] :test-paths []}\n',
        encoding="utf-8",
    )
    (package / "core.spork").write_text(
        "(ns safe-app.core (:import [python_support.helper :as helper]))\n"
        "(def value helper.VALUE)\n",
        encoding="utf-8",
    )
    (support / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    (support / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")

    result = check_project(ProjectConfig.load(str(tmp_path)))

    assert result.success
    assert not marker.exists()


def test_check_reports_project_structure_import_export_and_compile_errors(tmp_path: Path):
    source = tmp_path / "src" / "broken_app"
    source.mkdir(parents=True)
    (tmp_path / "spork.it").write_text(
        """{:name "broken-app"
 :version "0.1.0"
 :source-paths ["src"]
 :test-paths []
 :main "broken-app.core:missing-main"
 :api {:from "broken-app.core"
       :python {:package "broken-app" :exports ["missing-api"]}}}
""",
        encoding="utf-8",
    )
    (source / "target.spork").write_text(
        "(ns broken-app.target)\n(def present 1)\n", encoding="utf-8"
    )
    (source / "core.spork").write_text(
        """(ns broken-app.core
  (:require [missing.library :as missing]
            [broken-app.target :refer [absent]])
  (:import [module_that_does_not_exist_anywhere :as nope]))
(defn valid [] 1)
""",
        encoding="utf-8",
    )
    (source / "malformed.spork").write_text(
        "(ns broken-app.malformed)\n(defn malformed not-a-vector 1)\n",
        encoding="utf-8",
    )
    (source / "one.spork").write_text("(ns shared.name)\n", encoding="utf-8")
    (source / "two.spork").write_text("(ns shared.name)\n", encoding="utf-8")
    (source / "no_namespace.spork").write_text("(def value 1)\n", encoding="utf-8")

    result = check_project(ProjectConfig.load(str(tmp_path)))
    codes = {item.code for item in result.diagnostics}

    assert not result.success
    assert {
        MISSING_NAMESPACE,
        NAMESPACE_MISMATCH,
        DUPLICATE_NAMESPACE,
        UNRESOLVED_NAMESPACE,
        MISSING_EXPORT,
        UNRESOLVED_PYTHON_MODULE,
        COMPILE_ERROR,
        INVALID_MAIN,
        INVALID_API,
    }.issubset(codes)
    assert any(
        item.code == MISSING_EXPORT and "absent" in item.message
        for item in result.diagnostics
    )
    assert any(
        item.code == COMPILE_ERROR and item.path.name == "malformed.spork"
        for item in result.diagnostics
    )


def test_check_reports_reader_errors_and_can_exclude_tests(tmp_path: Path):
    project = write_project(tmp_path, invalid_test=True)
    config = ProjectConfig.load(str(project))

    with_tests = check_project(config)
    without_tests = check_project(config, include_tests=False)

    assert any(item.code == PARSE_ERROR for item in with_tests.diagnostics)
    assert not with_tests.success
    assert without_tests.success
    assert without_tests.files_checked == 2


def test_check_reports_missing_source_roots_and_empty_projects(tmp_path: Path):
    (tmp_path / "spork.it").write_text(
        '{:name "empty" :version "0.1.0" :source-paths ["missing"] :test-paths []}\n',
        encoding="utf-8",
    )

    result = check_project(ProjectConfig.load(str(tmp_path)))
    codes = {item.code for item in result.diagnostics}

    assert codes == {MISSING_SOURCE_ROOT, NO_SOURCE_FILES}


def test_check_reports_generated_api_file_conflicts(tmp_path: Path):
    project = write_project(tmp_path)
    initializer = project / "src" / "sample_app" / "__init__.py"
    initializer.write_text("HAND_WRITTEN = True\n", encoding="utf-8")

    result = check_project(ProjectConfig.load(str(project)))

    assert any(
        item.code == INVALID_API and item.path == initializer
        for item in result.diagnostics
    )


def test_check_json_cli_is_stable_and_returns_failure(tmp_path: Path, monkeypatch, capsys):
    project = write_project(tmp_path, invalid_test=True)
    monkeypatch.chdir(project / "src" / "sample_app")

    exit_code = _main(["check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["version"] == 1
    assert payload["project"] == "sample-app"
    assert payload["success"] is False
    assert payload["errors"] >= 1
    diagnostic = payload["diagnostics"][0]
    assert set(diagnostic) == {
        "path",
        "line",
        "column",
        "endLine",
        "endColumn",
        "severity",
        "code",
        "message",
    }
    assert not capsys.readouterr().err


def test_check_cli_human_output_and_no_tests(tmp_path: Path, monkeypatch, capsys):
    project = write_project(tmp_path, invalid_test=True)
    monkeypatch.chdir(project)

    assert _main(["check", "--no-tests"]) == 0
    output = capsys.readouterr().out

    assert "Checking sample-app..." in output
    assert "Checked 2 files; no issues found" in output


def test_check_cli_reports_manifest_errors_as_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert _main(["check", "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["project"] is None
    assert payload["errors"] == 1
    assert payload["diagnostics"][0]["code"] == PARSE_ERROR


def test_check_is_a_real_subcommand_not_a_file_argument():
    args = create_parser().parse_args(["check", "--warnings-as-errors"])

    assert args.subcommand == "check"
    assert args.warnings_as_errors
