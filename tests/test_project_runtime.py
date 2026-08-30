"""Tests for source project loading shared by core and extension commands."""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path

import pytest

import spork.cli as cli
from spork.commands import (
    CommandProvider,
    CommandSpec,
    ProjectRequiredError,
    create_command_context,
    invoke_command,
)
from spork.project import (
    InvalidProjectEntryError,
    ProjectConfig,
    ProjectEntryNotCallableError,
    ProjectEntryNotFoundError,
    ProjectEnvironmentError,
    ProjectNamespaceNotFoundError,
    ProjectRuntime,
)
from spork.project.manager import ProjectManager
from spork.runtime import ns as runtime_ns


@pytest.fixture(autouse=True)
def restore_runtime_state():
    original_roots = list(runtime_ns.SOURCE_ROOTS)
    original_registry = dict(runtime_ns.NAMESPACE_REGISTRY)
    original_sys_path = list(sys.path)
    try:
        yield
    finally:
        runtime_ns.SOURCE_ROOTS = original_roots
        runtime_ns.NAMESPACE_REGISTRY.clear()
        runtime_ns.NAMESPACE_REGISTRY.update(original_registry)
        sys.path[:] = original_sys_path


def create_source_project(root: Path) -> tuple[ProjectConfig, Path]:
    source = root / "app-src" / "fixture"
    source.mkdir(parents=True)
    (root / "spork.it").write_text(
        """{:name "runtime-fixture"
 :version "0.1.0"
 :source-paths ["app-src"]
 :main "fixture.core:main"
 :site {:target "fixture.core:site-title"
        :watch ["spork.it" "app-src"]
        :options {:drafts false}}}
""",
        encoding="utf-8",
    )
    (source / "values.spork").write_text(
        """(ns fixture.values)
(def base-status 5)
""",
        encoding="utf-8",
    )
    entrypoint = source / "core.spork"
    entrypoint.write_text(
        """(ns fixture.core
  (:require [fixture.values :refer [base-status]]))

(def site-title "Source project")
(def ready? true)

(defn greet-user [name]
  (+ "Hello, " name))

(defn status [& args]
  (+ base-status (count args)))

(defn no-status []
  "done")

(defn main [& args]
  (count args))
""",
        encoding="utf-8",
    )
    return ProjectConfig.load(str(root)), entrypoint


def source_runtime(config: ProjectConfig) -> ProjectRuntime:
    return ProjectRuntime(config, ensure_environment=False)


def test_load_entry_reads_source_values_and_normalized_names(tmp_path: Path):
    config, _ = create_source_project(tmp_path)
    runtime = source_runtime(config)

    assert runtime.load_entry("fixture.core:site-title") == "Source project"
    assert runtime.load_entry("fixture.core:ready?") is True
    greet = runtime.load_entry("fixture.core:greet-user")
    assert callable(greet)
    assert greet("Spork") == "Hello, Spork"
    assert not (tmp_path / ".spork-out").exists()


def test_invoke_entry_supports_dependencies_statuses_and_default_main(tmp_path: Path):
    config, _ = create_source_project(tmp_path)
    runtime = source_runtime(config)

    assert runtime.invoke_entry("fixture.core:status", ["one", "two"]) == 7
    assert runtime.invoke_entry("fixture.core:no-status", []) == 0
    assert runtime.invoke_entry("fixture.core", ["one", "two", "three"]) == 3


def test_runtime_finds_installed_spork_namespaces_in_project_environment(
    tmp_path: Path,
):
    config, _ = create_source_project(tmp_path)
    python = Path(config.venv_python)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    if os.name == "nt":
        site_packages = Path(config.venv_path) / "Lib" / "site-packages"
    else:
        site_packages = Path(config.venv_path) / "lib" / "python-test" / "site-packages"
    package = site_packages / "installed_fixture"
    package.mkdir(parents=True)
    (package / "core.spork").write_text(
        """(ns installed_fixture.core)
(def installed-value 42)
""",
        encoding="utf-8",
    )

    runtime = ProjectRuntime(config)

    assert runtime.load_entry("installed_fixture.core:installed-value") == 42
    assert str(site_packages) in sys.path


def test_runtime_prepares_missing_environment_once(tmp_path: Path):
    config, _ = create_source_project(tmp_path)
    calls: list[object] = []

    class Manager:
        installed = False

        def has_venv(self):
            calls.append("has")
            return self.installed

        def install_dependencies(self, quiet=False):
            calls.append(("install", quiet))
            self.installed = True
            return True

        def inject_venv_paths(self):
            calls.append("inject")
            return True

    manager = Manager()
    runtime = ProjectRuntime(config, manager=manager)  # type: ignore[arg-type]

    assert runtime.environment_missing
    runtime.prepare()
    runtime.prepare()

    assert calls.count(("install", False)) == 1
    assert calls.count("inject") == 1


def test_runtime_reports_environment_setup_failure(tmp_path: Path):
    config, _ = create_source_project(tmp_path)

    class Manager:
        def has_venv(self):
            return False

        def install_dependencies(self, quiet=False):
            return False

    runtime = ProjectRuntime(config, manager=Manager())  # type: ignore[arg-type]

    with pytest.raises(ProjectEnvironmentError, match="Failed to initialize"):
        runtime.prepare()


def test_runtime_has_actionable_entry_diagnostics(tmp_path: Path):
    config, _ = create_source_project(tmp_path)
    runtime = source_runtime(config)

    with pytest.raises(InvalidProjectEntryError, match="non-empty"):
        runtime.load_entry("")
    with pytest.raises(InvalidProjectEntryError, match="namespace:value"):
        runtime.load_entry("fixture.core:")
    with pytest.raises(ProjectNamespaceNotFoundError, match="missing.core") as missing:
        runtime.load_entry("missing.core:value")
    assert str(tmp_path / "app-src") in str(missing.value)
    with pytest.raises(ProjectEntryNotFoundError, match="missing-value"):
        runtime.load_entry("fixture.core:missing-value")
    with pytest.raises(ProjectEntryNotCallableError, match="not callable"):
        runtime.invoke_entry("fixture.core:site-title", [])
    with pytest.raises(TypeError, match="arguments must be strings"):
        runtime.invoke_entry("fixture.core:main", [1])  # type: ignore[list-item]


def test_runtime_traceback_retains_spork_source_location(tmp_path: Path):
    config, entrypoint = create_source_project(tmp_path)
    entrypoint.write_text(
        """(ns fixture.core)
(defn explode []
  (/ 1 0))
""",
        encoding="utf-8",
    )
    runtime = source_runtime(config)

    with pytest.raises(ZeroDivisionError) as raised:
        runtime.invoke_entry("fixture.core:explode", [])

    frames = traceback.extract_tb(raised.value.__traceback__)
    source_frames = [frame for frame in frames if Path(frame.filename) == entrypoint]
    assert source_frames
    assert source_frames[-1].lineno == 3


def test_command_context_loads_and_invokes_source_entries(tmp_path: Path):
    config, _ = create_source_project(tmp_path)
    runtime = source_runtime(config)
    provider = CommandProvider("fixture-provider", "project", version="1.0")

    def handler(context, argv):
        assert context.load_entry("fixture.core:site-title") == "Source project"
        return context.invoke_entry("fixture.core:status", argv)

    spec = CommandSpec("fixture", "Fixture command", handler, provider)
    context = create_command_context(spec, project=config, runtime=runtime)

    assert invoke_command(spec, ["one"], context=context) == 6
    assert context.project is config
    assert context.project_root == tmp_path.resolve()
    assert context.require_project() is config


def test_command_context_reports_when_project_is_required():
    provider = CommandProvider("fixture-provider", "active", version="1.0")
    spec = CommandSpec("fixture", "Fixture command", lambda context, argv: 0, provider)
    context = create_command_context(spec)

    with pytest.raises(ProjectRequiredError, match="requires a Spork project"):
        context.require_project()
    with pytest.raises(ProjectRequiredError, match="spork.it"):
        context.load_entry("fixture.core:value")


def test_manifest_exposes_recursive_read_only_plugin_configuration(tmp_path: Path):
    config, _ = create_source_project(tmp_path)

    site = config.get_plugin_config("site")
    assert isinstance(config.manifest, Mapping)
    assert isinstance(site, Mapping)
    assert site["target"] == "fixture.core:site-title"
    assert site["watch"] == ("spork.it", "app-src")
    assert site["options"]["drafts"] is False
    assert config.get("site") is site
    assert config.get_plugin_config("missing", "fallback") == "fallback"

    with pytest.raises(TypeError):
        config.manifest["site"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        site["target"] = "other.core:site"  # type: ignore[index]
    with pytest.raises(TypeError):
        site["options"]["drafts"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty"):
        config.get_plugin_config("")


def test_spork_run_uses_project_runtime_without_building(tmp_path: Path, monkeypatch):
    _, _ = create_source_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(ProjectManager, "has_venv", lambda self: True)
    monkeypatch.setattr(ProjectManager, "inject_venv_paths", lambda self: True)

    assert cli._main(["run", "one", "two"]) == 2
    assert cli._main(["run", "--main", "fixture.core:status", "one"]) == 6
    assert not (tmp_path / ".spork-out").exists()


def test_spork_run_preserves_unexpected_source_tracebacks(
    tmp_path: Path, monkeypatch, capsys
):
    _, entrypoint = create_source_project(tmp_path)
    entrypoint.write_text(
        """(ns fixture.core)
(defn main [& args]
  (/ 1 0))
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(ProjectManager, "has_venv", lambda self: True)
    monkeypatch.setattr(ProjectManager, "inject_venv_paths", lambda self: True)

    assert cli._main(["run"]) == 1

    error = capsys.readouterr().err
    assert "Traceback" in error
    assert f'File "{entrypoint}", line 3' in error
    assert "ZeroDivisionError" in error


def test_spork_run_reports_expected_runtime_errors_without_traceback(
    tmp_path: Path, monkeypatch, capsys
):
    create_source_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(ProjectManager, "has_venv", lambda self: True)
    monkeypatch.setattr(ProjectManager, "inject_venv_paths", lambda self: True)

    assert cli._main(["run", "--main", "fixture.core:missing"]) == 1

    error = capsys.readouterr().err
    assert "Entry 'missing' not found" in error
    assert "Traceback" not in error
