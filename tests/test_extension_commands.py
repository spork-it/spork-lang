"""Project-local and active command-provider discovery and dispatch tests."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from dataclasses import FrozenInstanceError
from pathlib import Path
from shutil import copytree

import pytest

import spork.cli as cli
import spork.command_discovery as discovery
import spork.runtime
from spork.command_discovery import (
    CommandCatalog,
    CommandDiscoveryDiagnostic,
    DiscoveredCommand,
    combine_command_catalogs,
    discover_commands,
)
from spork.commands import (
    COMMAND_ENTRY_POINT_GROUP,
    CommandProvider,
    create_command_context,
    invoke_command,
)
from spork.project.config import ProjectConfig
from spork.project.dist import create_dist


class FakeEntryPoint:
    def __init__(self, name: str, value: str, group: str, loader):
        self.name = name
        self.value = value
        self.group = group
        self._loader = loader

    def load(self):
        return self._loader()


class FakeDistribution:
    def __init__(
        self,
        name: str | None,
        version: str,
        entry_points: list[FakeEntryPoint],
        location: Path,
    ):
        self.metadata = {} if name is None else {"Name": name}
        self.version = version
        self.entry_points = entry_points
        self._location = location

    def locate_file(self, path: str) -> Path:
        return self._location / path


def fake_distribution(
    tmp_path: Path,
    *,
    command: str = "greet",
    target: str = "provider.cli:command",
    group: str = COMMAND_ENTRY_POINT_GROUP,
    provider: str = "fixture-provider",
    version: str = "1.2.3",
    loader=lambda: None,
) -> FakeDistribution:
    return FakeDistribution(
        provider,
        version,
        [FakeEntryPoint(command, target, group, loader)],
        tmp_path / provider,
    )


def discovered_command(
    tmp_path: Path,
    handler,
    *,
    command: str = "greet",
    scope: str = "active",
    provider: str = "fixture-provider",
    loader_error: Exception | None = None,
) -> DiscoveredCommand:
    def load():
        if loader_error is not None:
            raise loader_error
        return handler

    entry_point = FakeEntryPoint(
        command,
        "provider.cli:command",
        COMMAND_ENTRY_POINT_GROUP,
        load,
    )
    provenance = CommandProvider(
        name=provider,
        version="1.2.3",
        scope=scope,  # type: ignore[arg-type]
        location=tmp_path / provider,
    )
    return DiscoveredCommand(
        name=command,
        target=entry_point.value,
        provider=provenance,
        entry_point=entry_point,  # type: ignore[arg-type]
    )


def extension_state(
    catalog: CommandCatalog,
    project: ProjectConfig | None = None,
) -> cli._ExtensionCommandState:
    return cli._ExtensionCommandState(catalog=catalog, project=project)


def test_metadata_discovery_is_lazy_and_invocation_uses_common_contract(
    tmp_path: Path, monkeypatch
):
    events = []

    def command(context, argv):
        events.append(("called", context, list(argv)))
        return 7

    def load():
        events.append(("loaded",))
        return command

    distribution = fake_distribution(tmp_path, loader=load)
    monkeypatch.setattr(
        discovery.metadata,
        "distributions",
        lambda **kwargs: [distribution],
    )

    catalog = discover_commands("active")

    assert events == []
    assert list(catalog.commands) == ["greet"]
    selected = catalog.commands["greet"]
    assert selected.target == "provider.cli:command"
    assert selected.provider.name == "fixture-provider"
    assert selected.provider.version == "1.2.3"
    assert selected.provider.scope == "active"
    assert selected.provider.location == (tmp_path / "fixture-provider").resolve()

    spec = selected.create_spec()
    context = create_command_context(spec, cwd=tmp_path)
    arguments = ["nested", "--flag=value", ""]
    assert invoke_command(spec, arguments, context=context) == 7
    assert events[0] == ("loaded",)
    assert events[1][0] == "called"
    assert events[1][1] == context
    assert events[1][2] == arguments
    assert arguments == ["nested", "--flag=value", ""]


def test_discovery_rejects_malformed_and_reserved_metadata_but_ignores_v2(
    tmp_path: Path, monkeypatch
):
    entries = [
        FakeEntryPoint("Bad", "provider.cli:command", COMMAND_ENTRY_POINT_GROUP, None),
        FakeEntryPoint("run", "provider.cli:command", COMMAND_ENTRY_POINT_GROUP, None),
        FakeEntryPoint("broken", "not a target", COMMAND_ENTRY_POINT_GROUP, None),
        FakeEntryPoint("future", "provider.cli:command", "spork.commands.v2", None),
    ]
    distribution = FakeDistribution("broken-provider", "1.0", entries, tmp_path)
    monkeypatch.setattr(
        discovery.metadata,
        "distributions",
        lambda **kwargs: [distribution],
    )

    catalog = discover_commands("active")

    assert catalog.commands == {}
    assert len(catalog.diagnostics) == 3
    messages = [item.message for item in catalog.diagnostics]
    assert any("lowercase letters" in message for message in messages)
    assert any("reserved" in message for message in messages)
    assert any("module:function" in message for message in messages)
    assert not any("future" in message for message in messages)


def test_discovery_reports_missing_distribution_identity(tmp_path: Path, monkeypatch):
    distribution = FakeDistribution(
        None,
        "1.0",
        [
            FakeEntryPoint(
                "greet",
                "provider.cli:command",
                COMMAND_ENTRY_POINT_GROUP,
                None,
            )
        ],
        tmp_path,
    )
    monkeypatch.setattr(
        discovery.metadata,
        "distributions",
        lambda **kwargs: [distribution],
    )

    catalog = discover_commands("active")

    assert catalog.commands == {}
    assert len(catalog.diagnostics) == 1
    assert "no non-empty Name" in catalog.diagnostics[0].message


def test_same_scope_collision_is_deterministic_error(tmp_path: Path, monkeypatch):
    distributions = [
        fake_distribution(tmp_path, provider="provider-z"),
        fake_distribution(tmp_path, provider="provider-a"),
    ]
    monkeypatch.setattr(
        discovery.metadata,
        "distributions",
        lambda **kwargs: distributions,
    )

    catalog = discover_commands("project", paths=[tmp_path])

    assert "greet" not in catalog.commands
    assert len(catalog.diagnostics) == 1
    message = catalog.diagnostics[0].message
    assert "multiple project providers" in message
    assert message.index("provider-a") < message.index("provider-z")


def test_catalog_precedence_prefers_project_over_active(tmp_path: Path):
    project = discovered_command(
        tmp_path,
        lambda context, argv: 1,
        scope="project",
        provider="project-provider",
    )
    active = discovered_command(
        tmp_path,
        lambda context, argv: 2,
        scope="active",
        provider="active-provider",
    )

    catalog = combine_command_catalogs(
        [CommandCatalog({"greet": project}), CommandCatalog({"greet": active})]
    )

    assert catalog.commands["greet"] is project
    with pytest.raises(TypeError):
        catalog.commands["other"] = active  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        project.name = "other"  # type: ignore[misc]


def test_higher_scope_failure_blocks_fallback_but_shadowed_failure_is_ignored(
    tmp_path: Path,
):
    project_failure = CommandDiscoveryDiagnostic(
        command="greet",
        message="project command is malformed",
    )
    active = discovered_command(
        tmp_path,
        lambda context, argv: 2,
        scope="active",
        provider="active-provider",
    )
    blocked = combine_command_catalogs(
        [
            CommandCatalog(diagnostics=(project_failure,)),
            CommandCatalog({"greet": active}),
        ]
    )
    assert "greet" not in blocked.commands
    assert blocked.diagnostics_for("greet") == (project_failure,)

    project = discovered_command(
        tmp_path,
        lambda context, argv: 1,
        scope="project",
        provider="project-provider",
    )
    active_failure = CommandDiscoveryDiagnostic(
        command="greet",
        message="active command is malformed",
    )
    shadowed = combine_command_catalogs(
        [
            CommandCatalog({"greet": project}),
            CommandCatalog(diagnostics=(active_failure,)),
        ]
    )
    assert shadowed.commands["greet"] is project
    assert shadowed.diagnostics_for("greet") == ()


def test_cli_dispatches_active_provider_with_project_context_and_raw_arguments(
    tmp_path: Path, monkeypatch
):
    project = ProjectConfig(
        name="consumer",
        version="0.1.0",
        project_root=str(tmp_path),
    )
    seen = {}

    def handler(context, argv):
        seen["context"] = context
        seen["argv"] = list(argv)
        return 6

    command = discovered_command(tmp_path, handler)
    state = extension_state(CommandCatalog({"greet": command}), project)
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)
    monkeypatch.chdir(tmp_path)

    arguments = ["nested", "--output=some path", "λ", ""]
    assert cli._main(["greet", *arguments]) == 6
    assert seen["argv"] == arguments
    assert seen["context"].command == "greet"
    assert seen["context"].scope == "active"
    assert seen["context"].provider.name == "fixture-provider"
    assert seen["context"].project is project
    assert seen["context"].project_root == tmp_path.resolve()


def test_cli_normalizes_none_and_reports_invalid_provider_result(
    tmp_path: Path, monkeypatch, capsys
):
    result: dict[str, object] = {"value": None}
    command = discovered_command(tmp_path, lambda context, argv: result["value"])
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    assert cli._main(["greet"]) == 0
    result["value"] = True
    assert cli._main(["greet"]) == 1
    error = capsys.readouterr().err
    assert "fixture-provider==1.2.3 (active)" in error
    assert "expected int or None" in error


def test_cli_reports_selected_provider_load_failures(
    tmp_path: Path, monkeypatch, capsys
):
    command = discovered_command(
        tmp_path,
        lambda context, argv: 0,
        loader_error=ModuleNotFoundError("missing_provider_module"),
    )
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    assert cli._main(["greet"]) == 1
    error = capsys.readouterr().err
    assert "fixture-provider==1.2.3 (active)" in error
    assert "could not load command 'greet' from fixture-provider" in error
    assert "missing_provider_module" in error

    not_callable = discovered_command(tmp_path, 42)
    monkeypatch.setattr(
        cli,
        "_discover_extension_state",
        lambda: extension_state(CommandCatalog({"greet": not_callable})),
    )
    assert cli._main(["greet"]) == 1
    assert "resolved to int, not a callable" in capsys.readouterr().err


def test_cli_preserves_unexpected_provider_exceptions(
    tmp_path: Path, monkeypatch, capsys
):
    def handler(context, argv):
        raise RuntimeError("provider exploded")

    command = discovered_command(tmp_path, handler)
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    with pytest.raises(RuntimeError, match="provider exploded"):
        cli._main(["greet"])
    error = capsys.readouterr().err
    assert "fixture-provider==1.2.3 (active)" in error
    assert "raised RuntimeError: provider exploded" in error


def test_provider_owns_nested_help(tmp_path: Path, monkeypatch):
    seen = []

    def handler(context, argv):
        seen.append(list(argv))
        raise SystemExit(0)

    command = discovered_command(tmp_path, handler)
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    with pytest.raises(SystemExit) as exited:
        cli._main(["greet", "nested", "--help"])

    assert exited.value.code == 0
    assert seen == [["nested", "--help"]]


def test_top_level_help_lists_extensions_without_loading_them(
    tmp_path: Path, monkeypatch, capsys
):
    loaded = []
    command = discovered_command(
        tmp_path,
        lambda context, argv: 0,
        command="greet",
        provider="provider-package",
    )

    def load():
        loaded.append(True)
        return lambda context, argv: 0

    command.entry_point._loader = load  # type: ignore[attr-defined]
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    with pytest.raises(SystemExit) as exited:
        cli._main(["--help"])

    assert exited.value.code == 0
    output = capsys.readouterr().out
    assert "extension commands:" in output
    assert "greet  provider-package 1.2.3 (active)" in output
    assert loaded == []


def test_help_warns_about_broken_metadata_without_breaking_core_commands(
    tmp_path: Path, monkeypatch, capsys
):
    diagnostic = CommandDiscoveryDiagnostic(
        command="broken",
        message="invalid active command metadata from broken-provider",
    )
    state = extension_state(CommandCatalog(diagnostics=(diagnostic,)))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    with pytest.raises(SystemExit) as exited:
        cli._main(["--help"])
    assert exited.value.code == 0
    assert "Warning: invalid active command metadata" in capsys.readouterr().err

    monkeypatch.setattr(
        cli,
        "_discover_extension_state",
        lambda: (_ for _ in ()).throw(AssertionError("discovery must remain lazy")),
    )
    assert cli._main(["version"]) == 0


def test_unknown_command_is_clear_and_suggests_known_extensions(
    tmp_path: Path, monkeypatch, capsys
):
    command = discovered_command(tmp_path, lambda context, argv: 0, command="greet")
    state = extension_state(CommandCatalog({"greet": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    assert cli._main(["gret"]) == 2
    error = capsys.readouterr().err
    assert "unknown command 'gret'" in error
    assert "Did you mean 'greet'?" in error


def test_selected_collision_fails_without_loading_any_provider(
    tmp_path: Path, monkeypatch, capsys
):
    diagnostic = CommandDiscoveryDiagnostic(
        command="greet",
        message="command 'greet' has multiple project providers: one, two",
    )
    state = extension_state(CommandCatalog(diagnostics=(diagnostic,)))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)

    assert cli._main(["greet", "nested"]) == 1
    assert "multiple project providers" in capsys.readouterr().err


def test_explicit_paths_remain_files_when_command_name_exists(
    tmp_path: Path, monkeypatch
):
    calls = []

    def command_handler(context, argv):
        calls.append(("command", list(argv)))
        return 8

    def file_handler(path, interactive=False):
        calls.append(("file", path))
        return 4

    command = discovered_command(
        tmp_path,
        command_handler,
        command="site",
    )
    state = extension_state(CommandCatalog({"site": command}))
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(cli, "_discover_extension_state", lambda: state)
    monkeypatch.setattr(cli, "cmd_exec_file", file_handler)

    assert cli._main(["site", "nested"]) == 8
    assert cli._main(["./site"]) == 4
    assert cli._main(["site.spork"]) == 4
    assert calls == [
        ("command", ["nested"]),
        ("file", "./site"),
        ("file", "site.spork"),
    ]


def test_source_only_provider_distribution_runs_from_consumer_environment(
    tmp_path: Path,
):
    repository = Path(__file__).resolve().parents[1]
    provider_project = repository / "examples" / "command-provider"
    result = create_dist(
        project_root=provider_project,
        out_dir=tmp_path / "provider-build",
        dist_dir=tmp_path / "provider-dist",
        clean=True,
        verbose=False,
    )
    assert result.success, result.error
    assert result.wheel_path is not None

    consumer = tmp_path / "consumer"
    copytree(repository / "tests" / "fixtures" / "command-consumer", consumer)
    venv.EnvBuilder(with_pip=False).create(consumer / ".venv")
    project = ProjectConfig.load(str(consumer))
    assert project.venv_site_packages is not None
    site_packages = Path(project.venv_site_packages)
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(site_packages),
            str(result.wheel_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    catalog = discovery.discover_extension_commands(project)
    assert catalog.commands["greet"].provider.scope == "project"
    assert catalog.commands["greet"].provider.name == "spork-greeter"

    environment = os.environ.copy()
    runtime_repository = Path(spork.runtime.__file__).resolve().parents[2]
    host_paths = [str(repository), str(runtime_repository)]
    host_paths.extend(path for path in sys.path if path and path != str(repository))
    existing_python_path = environment.get("PYTHONPATH")
    if existing_python_path:
        host_paths.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(host_paths)
    invoked = subprocess.run(
        [
            project.venv_python,
            "-m",
            "spork",
            "greet",
            "nested",
            "--flag",
            "value",
        ],
        cwd=consumer,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert invoked.returncode == 0, invoked.stdout + invoked.stderr
    assert "Hello from a Spork command provider" in invoked.stdout
    assert invoked.stderr == ""
