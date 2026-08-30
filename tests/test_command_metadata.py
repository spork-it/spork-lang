"""Package command declaration, checking, and distribution metadata tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

import spork.cli as cli
from spork.cli import CORE_COMMANDS
from spork.commands import COMMAND_ENTRY_POINT_GROUP, RESERVED_COMMAND_NAMES
from spork.project.build import build_project
from spork.project.check import INVALID_COMMAND, check_project
from spork.project.config import CommandConfig, ProjectConfig
from spork.project.dist import create_dist


def write_provider_project(
    root: Path,
    *,
    commands: str | None = None,
    source: str | None = None,
) -> Path:
    package = root / "src" / "fixture_provider"
    package.mkdir(parents=True)
    command_form = commands or (
        '"hello" {:main "fixture-provider.cli:command"\n'
        '           :description "Say hello from a fixture"}\n'
        ' "hello-short" "fixture-provider.cli:command"'
    )
    command_value = (
        command_form[1:] if command_form.startswith("=") else f"{{{command_form}}}"
    )
    (root / "spork.it").write_text(
        f'''{{:name "fixture-provider"
 :version "1.2.3"
 :description "Command provider fixture"
 :requires-python ">=3.10"
 :spork-version ">=0.5.3,<0.6"
 :dependencies []
 :source-paths ["src"]
 :test-paths []
 :commands {command_value}}}
''',
        encoding="utf-8",
    )
    (package / "cli.spork").write_text(
        source
        or """(ns fixture-provider.cli)
(defn ^int command [context argv]
  (count argv))
""",
        encoding="utf-8",
    )
    return root


def test_project_config_parses_typed_map_and_string_command_declarations(
    tmp_path: Path,
):
    project = write_provider_project(tmp_path)

    config = ProjectConfig.load(str(project))

    assert list(config.commands) == ["hello", "hello-short"]
    assert config.commands["hello"] == CommandConfig(
        main="fixture-provider.cli:command",
        description="Say hello from a fixture",
    )
    assert config.commands["hello-short"] == CommandConfig(
        main="fixture-provider.cli:command"
    )
    assert config.commands["hello"].namespace == "fixture-provider.cli"
    assert config.commands["hello"].function == "command"
    assert config.commands["hello"].python_target == "fixture_provider.cli:command"
    assert set(CORE_COMMANDS).issubset(RESERVED_COMMAND_NAMES)
    assert "plugin" in RESERVED_COMMAND_NAMES


@pytest.mark.parametrize(
    ("commands", "message"),
    [
        ("=[]", ":commands must be a map"),
        (':hello "fixture-provider.cli:command"', ":commands names must be strings"),
        ('"" "fixture-provider.cli:command"', ":commands names"),
        ('"Bad" "fixture-provider.cli:command"', ":commands names"),
        ('"bad--name" "fixture-provider.cli:command"', ":commands names"),
        ('"run" "fixture-provider.cli:command"', "reserved"),
        (
            '"hello" "fixture-provider.cli:command" '
            '"hello" "fixture-provider.cli:command"',
            "duplicate name",
        ),
        ('"hello" {}', "missing required field :main"),
        (
            '"hello" {:main "fixture-provider.cli:command" :extra true}',
            "unknown fields",
        ),
        (
            '"hello" {:main "fixture-provider.cli:command" :description ""}',
            ":description must be a non-empty string",
        ),
        ('"hello" 42', "target string or a command map"),
        ('"hello" "fixture-provider.cli"', "namespace:function form"),
        ('"hello" "fixture provider.cli:command"', "dotted Python module"),
        ('"hello" "fixture-provider.cli:not valid"', "Python identifier"),
    ],
)
def test_project_config_rejects_malformed_command_declarations(
    tmp_path: Path, commands: str, message: str
):
    project = write_provider_project(tmp_path, commands=commands)

    with pytest.raises(ValueError, match=message):
        ProjectConfig.load(str(project))


def test_malformed_command_declaration_fails_check_and_dist(
    tmp_path: Path, monkeypatch, capsys
):
    project = write_provider_project(
        tmp_path,
        commands='"run" "fixture-provider.cli:command"',
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)

    assert cli._main(["check", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["code"] == "SPK001"
    assert "reserved" in payload["diagnostics"][0]["message"]

    result = create_dist(project_root=project, clean=True, verbose=False)
    assert not result.success
    assert result.error is not None
    assert result.error.startswith("Failed to load project config:")
    assert "reserved" in result.error


def test_check_validates_command_namespace_function_and_kind(tmp_path: Path):
    missing_namespace = write_provider_project(
        tmp_path / "missing-namespace",
        commands='"hello" "missing.cli:command"',
    )
    missing_function = write_provider_project(
        tmp_path / "missing-function",
        commands='"hello" "fixture-provider.cli:missing-command"',
    )
    wrong_kind = write_provider_project(
        tmp_path / "wrong-kind",
        source="""(ns fixture-provider.cli)
(def command 42)
""",
    )
    mismatched_module = write_provider_project(
        tmp_path / "mismatched-module",
        commands='"hello" "fixture_provider.cli:command"',
        source="""(ns fixture_provider.cli)
(defn command [context argv] 0)
""",
    )
    duplicate_function = write_provider_project(
        tmp_path / "duplicate-function",
        commands='"hello" "fixture-provider.cli:run-command"',
        source="""(ns fixture-provider.cli)
(defn run-command [context argv] 0)
(defn run_command [context argv] 0)
""",
    )

    namespace_result = check_project(ProjectConfig.load(str(missing_namespace)))
    function_result = check_project(ProjectConfig.load(str(missing_function)))
    kind_result = check_project(ProjectConfig.load(str(wrong_kind)))
    module_result = check_project(ProjectConfig.load(str(mismatched_module)))
    duplicate_result = check_project(ProjectConfig.load(str(duplicate_function)))

    assert not namespace_result.success
    assert not function_result.success
    assert not kind_result.success
    assert not module_result.success
    assert not duplicate_result.success
    assert [
        item.code
        for item in namespace_result.diagnostics
        if item.code == INVALID_COMMAND
    ] == [INVALID_COMMAND]
    assert any(
        "not defined by project source" in item.message
        for item in namespace_result.diagnostics
    )
    assert any(
        "missing-command" in item.message for item in function_result.diagnostics
    )
    assert any("not a function" in item.message for item in kind_result.diagnostics)
    assert any(
        "does not match source path" in item.message
        for item in module_result.diagnostics
    )
    assert any(
        "duplicate normalized definitions" in item.message
        for item in duplicate_result.diagnostics
    )

    dist_result = create_dist(
        project_root=mismatched_module, clean=True, verbose=False
    )
    assert not dist_result.success
    assert dist_result.error is not None
    assert "does not match source path" in dist_result.error


def _entry_points_text_from_wheel(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        name = next(
            item
            for item in archive.namelist()
            if item.endswith(".dist-info/entry_points.txt")
        )
        return archive.read(name).decode("utf-8")


def _assert_installed_provider(artifact: Path, target: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-deps",
        "--target",
        str(target),
    ]
    if artifact.name.endswith(".tar.gz"):
        command.append("--no-build-isolation")
    command.append(str(artifact))
    installed = subprocess.run(command, capture_output=True, text=True)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib.metadata import distributions; "
                "dist = next(item for item in distributions() "
                "if item.metadata['Name'] == 'fixture-provider'); "
                "eps = [item for item in dist.entry_points "
                f"if item.group == {COMMAND_ENTRY_POINT_GROUP!r}]; "
                "assert sorted(item.name for item in eps) == ['hello', 'hello-short']; "
                "entry = next(item for item in eps if item.name == 'hello'); "
                "assert entry.value == 'fixture_provider.cli:command'; "
                "assert entry.load()(None, ['one', 'two']) == 2"
            ),
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr


def test_dist_generates_installable_command_metadata_and_payloads(tmp_path: Path):
    project = write_provider_project(tmp_path / "project")

    result = create_dist(project_root=project, clean=True, verbose=False)

    assert result.success, result.error
    assert result.wheel_path is not None
    assert result.sdist_path is not None
    generated = (project / ".spork-out" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert f'[project.entry-points."{COMMAND_ENTRY_POINT_GROUP}"]' in generated
    assert 'hello = "fixture_provider.cli:command"' in generated
    assert 'hello-short = "fixture_provider.cli:command"' in generated

    with zipfile.ZipFile(result.wheel_path) as wheel:
        names = set(wheel.namelist())
        assert "fixture_provider/cli.py" in names
        assert "fixture_provider/cli.spork" in names
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_name).decode("utf-8")
        assert "Requires-Dist: spork-runtime<0.2.0,>=0.1.1" in metadata
        assert "Requires-Dist: spork-lang" not in metadata

    entry_points = _entry_points_text_from_wheel(result.wheel_path)
    assert f"[{COMMAND_ENTRY_POINT_GROUP}]" in entry_points
    assert "hello = fixture_provider.cli:command" in entry_points
    assert "hello-short = fixture_provider.cli:command" in entry_points

    with tarfile.open(result.sdist_path) as sdist:
        names = set(sdist.getnames())
        prefix = "fixture_provider-1.2.3"
        assert f"{prefix}/fixture_provider/cli.py" in names
        assert f"{prefix}/fixture_provider/cli.spork" in names
        assert f"{prefix}/pyproject.toml" in names
        pyproject = sdist.extractfile(f"{prefix}/pyproject.toml")
        assert pyproject is not None
        assert f'[project.entry-points."{COMMAND_ENTRY_POINT_GROUP}"]' in (
            pyproject.read().decode("utf-8")
        )
        assert any(name.endswith(".egg-info/entry_points.txt") for name in names)

    _assert_installed_provider(result.wheel_path, tmp_path / "wheel-install")
    _assert_installed_provider(result.sdist_path, tmp_path / "sdist-install")


def test_dist_rejects_invalid_source_target_before_build(tmp_path: Path):
    project = write_provider_project(
        tmp_path,
        commands='"hello" "fixture-provider.cli:missing"',
    )

    result = create_dist(project_root=project, clean=True, verbose=False)

    assert not result.success
    assert result.error is not None
    assert result.error.startswith("Command validation failed:")
    assert "missing" in result.error
    assert not (project / ".spork-out").exists()


def test_dist_rejects_stale_generated_command_payload(tmp_path: Path):
    project = write_provider_project(tmp_path)
    built = build_project(project_root=project, clean=True, verbose=False)
    assert built.success
    generated = built.out_dir / "fixture_provider" / "cli.py"
    source = generated.read_text(encoding="utf-8")
    generated.write_text(
        source.replace("def command(", "def stale_command("), encoding="utf-8"
    )

    result = create_dist(
        project_root=project,
        build_first=False,
        wheel=False,
        sdist=False,
        verbose=False,
    )

    assert not result.success
    assert result.error is not None
    assert "generated function 'command' is missing" in result.error


def test_check_result_json_includes_stable_command_diagnostic(tmp_path: Path):
    project = write_provider_project(
        tmp_path,
        commands='"hello" "fixture-provider.cli:missing"',
    )

    result = check_project(ProjectConfig.load(str(project)))
    payload = json.loads(result.to_json())
    diagnostics = [
        item for item in payload["diagnostics"] if item["code"] == INVALID_COMMAND
    ]

    assert payload["success"] is False
    assert len(diagnostics) == 1
    assert diagnostics[0]["path"] == "spork.it"
    assert diagnostics[0]["message"].startswith(":commands 'hello'")
