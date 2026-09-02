"""Managed global plugin registry, discovery, and dispatch tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import spork.command_discovery as discovery
from spork.command_discovery import CommandProviderLoadError
from spork.commands import COMMAND_API_VERSION, create_command_context, invoke_command
from spork.plugins import (
    GlobalPluginRecord,
    PluginInstallationError,
    PluginManager,
    PluginRegistryError,
    discover_global_commands,
    plugin_environment_python,
    plugin_home,
)
from spork.project.config import ProjectConfig


def write_distribution(
    site_packages: Path,
    name: str,
    version: str,
    *,
    commands: dict[str, str] | None = None,
) -> None:
    normalized = name.replace("-", "_")
    dist_info = site_packages / f"{normalized}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    if commands:
        entries = ["[spork.commands.v1]"]
        entries.extend(f"{name} = {target}" for name, target in commands.items())
        (dist_info / "entry_points.txt").write_text(
            "\n".join(entries) + "\n", encoding="utf-8"
        )


def plugin_record(
    manager: PluginManager,
    name: str = "fixture-provider",
    *,
    version: str = "1.2.3",
    commands: tuple[str, ...] = ("greet",),
    host_version: str = "0.6.0",
) -> GlobalPluginRecord:
    environment = manager.plugins_path / name / ".venv"
    site_packages = environment / "lib" / "python-test" / "site-packages"
    site_packages.mkdir(parents=True)
    python = plugin_environment_python(environment)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    write_distribution(site_packages, "spork-lang", host_version)
    write_distribution(
        site_packages,
        name,
        version,
        commands={command: "fixture_provider.cli:command" for command in commands},
    )
    return GlobalPluginRecord(
        requirement=name,
        distribution=name,
        display_name=name,
        version=version,
        api_version=COMMAND_API_VERSION,
        commands=commands,
        environment=environment,
        site_packages=site_packages,
        host_version=host_version,
        installed_at="2026-01-01T00:00:00+00:00",
        installation_host={"python": "3.14"},
    )


def save_records(
    manager: PluginManager, records: dict[str, GlobalPluginRecord]
) -> None:
    manager._write_records_unlocked(records)


def write_local_plugin_project(
    project_root: Path,
    *,
    name: str = "local-provider",
    commands: bool = True,
) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    command_declaration = (
        '\n :commands {"local" {:main "local-provider.cli:command"}}'
        if commands
        else ""
    )
    (project_root / "spork.it").write_text(
        f'''{{:name "{name}"
 :version "1.0.0"
 :spork-version ">=0.6,<0.7"
 :source-paths ["src"]
 :test-paths []{command_declaration}}}\n''',
        encoding="utf-8",
    )
    source = project_root / "src" / "local_provider" / "cli.spork"
    source.parent.mkdir(parents=True)
    source.write_text(
        "(ns local-provider.cli)\n"
        "(defn ^int command [context argv] 0)\n",
        encoding="utf-8",
    )


def test_plugin_home_honors_override(tmp_path: Path, monkeypatch):
    selected = tmp_path / "portable-home"
    monkeypatch.setenv("SPORK_HOME", str(selected))
    assert plugin_home() == selected.resolve()


def test_registry_round_trip_is_typed_and_paths_are_relative(tmp_path: Path):
    manager = PluginManager(tmp_path / "home")
    record = plugin_record(manager)
    save_records(manager, {record.distribution: record})

    loaded = manager.records()
    assert loaded == (record,)
    raw = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    stored = raw["plugins"]["fixture-provider"]
    assert stored["environment"] == "plugins/fixture-provider/.venv"
    assert stored["site_packages"] == "lib/python-test/site-packages"
    assert not Path(stored["environment"]).is_absolute()


def test_corrupt_registry_has_actionable_diagnostics(tmp_path: Path):
    manager = PluginManager(tmp_path / "home")
    manager.home.mkdir(parents=True)
    manager.registry_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(PluginRegistryError, match="registry.*corrupt"):
        manager.records()
    catalog = discover_global_commands(manager)
    assert catalog.commands == {}
    assert "registry" in catalog.diagnostics[0].message
    assert "reinstall plugins" in catalog.diagnostics[0].message


def test_staged_package_without_commands_is_rejected(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    environment = tmp_path / "stage" / ".venv"
    site_packages = environment / "lib" / "python-test" / "site-packages"
    site_packages.mkdir(parents=True)
    write_distribution(site_packages, "spork-lang", "0.6.0")
    write_distribution(site_packages, "plain-package", "1.0.0")
    monkeypatch.setattr(
        "spork.plugins._venv_site_packages", lambda selected: site_packages
    )

    with pytest.raises(PluginInstallationError, match="exposes no.*entry points"):
        manager._inspect_staged(
            environment,
            "plain-package",
            "plain-package",
        )


def test_staged_package_with_reserved_command_is_rejected(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    environment = tmp_path / "stage" / ".venv"
    site_packages = environment / "lib" / "python-test" / "site-packages"
    site_packages.mkdir(parents=True)
    write_distribution(site_packages, "spork-lang", "0.6.0")
    write_distribution(
        site_packages,
        "bad-provider",
        "1.0.0",
        commands={"run": "bad_provider.cli:command"},
    )
    monkeypatch.setattr(
        "spork.plugins._venv_site_packages", lambda selected: site_packages
    )

    with pytest.raises(PluginInstallationError, match="reserved by spork-lang"):
        manager._inspect_staged(
            environment,
            "bad-provider",
            "bad-provider",
        )


def test_global_discovery_validates_environment_without_loading_provider(
    tmp_path: Path,
):
    manager = PluginManager(tmp_path / "home")
    record = plugin_record(manager)
    save_records(manager, {record.distribution: record})

    catalog = discover_global_commands(manager)

    assert catalog.diagnostics == ()
    selected = catalog.commands["greet"]
    assert selected.provider.scope == "global"
    assert selected.provider.name == "fixture-provider"
    assert selected.execution_python == record.python
    assert selected.host_version == "0.6.0"

    record.python.unlink()
    broken = discover_global_commands(manager)
    assert "greet" not in broken.commands
    diagnostic = broken.diagnostics_for("greet")[0].message
    assert "Python executable" in diagnostic
    assert "spork plugin remove fixture-provider" in diagnostic


def test_global_command_runs_with_isolated_python_and_raw_arguments(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    record = plugin_record(manager)
    save_records(manager, {record.distribution: record})
    command = discover_global_commands(manager).commands["greet"]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(discovery.subprocess, "run", fake_run)
    spec = command.create_spec()
    context = create_command_context(spec, cwd=tmp_path)
    arguments = ["nested", "--output=some path", "λ", ""]

    assert invoke_command(spec, arguments, context=context) == 7
    argv, kwargs = calls[0]
    assert argv == [str(record.python), "-m", "spork", "greet", *arguments]
    assert kwargs["cwd"] == tmp_path.resolve()
    assert kwargs["env"][discovery.MANAGED_PLUGIN_INVOCATION_ENV] == (
        "fixture-provider"
    )
    assert kwargs["env"][discovery.MANAGED_PLUGIN_COMMAND_ENV] == "greet"
    assert arguments == ["nested", "--output=some path", "λ", ""]


def test_incompatible_global_host_recommends_project_install(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    record = plugin_record(manager)
    save_records(manager, {record.distribution: record})
    command = discover_global_commands(manager).commands["greet"]
    project = ProjectConfig(
        name="consumer",
        version="0.1.0",
        project_root=str(tmp_path),
        spork_version=">=0.7,<0.8",
    )
    spec = command.create_spec()
    context = create_command_context(spec, project=project)
    monkeypatch.setattr(
        discovery.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("incompatible provider must not run"),
    )

    with pytest.raises(CommandProviderLoadError) as raised:
        invoke_command(spec, [], context=context)
    assert "does not satisfy" in str(raised.value)
    assert "spork add fixture-provider" in str(raised.value)
    assert "spork sync" in str(raised.value)


def test_successful_add_moves_staged_environment_and_updates_registry(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, environment):
            selected = Path(environment)
            site_packages = selected / "lib" / "python-test" / "site-packages"
            site_packages.mkdir(parents=True)
            python = plugin_environment_python(selected)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")

    def fake_inspect(environment, requirement, distribution):
        selected = Path(environment)
        site_packages = selected / "lib" / "python-test" / "site-packages"
        record = GlobalPluginRecord(
            requirement=requirement,
            distribution=distribution,
            display_name="fixture-provider",
            version="2.0.0",
            api_version=COMMAND_API_VERSION,
            commands=("greet", "wave"),
            environment=selected,
            site_packages=site_packages,
            host_version="0.6.0",
            installed_at="2026-01-01T00:00:00+00:00",
        )
        return record, site_packages.relative_to(selected)

    monkeypatch.setattr("spork.plugins.venv.EnvBuilder", FakeBuilder)
    monkeypatch.setattr(manager, "_run_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_inspect_staged", fake_inspect)

    installed = manager.add("fixture_provider>=2")

    assert installed.environment == (
        manager.plugins_path / "fixture-provider" / ".venv"
    )
    assert installed.environment.is_dir()
    assert manager.records() == (installed,)
    assert not any(
        path.name.endswith(".tmp") for path in manager.plugins_path.iterdir()
    )


def test_local_spork_project_add_builds_temporary_wheel_and_records_source(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "provider source"
    write_local_plugin_project(project)
    manager = PluginManager(tmp_path / "home")
    build_calls = []
    install_calls = []

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, environment):
            selected = Path(environment)
            site_packages = selected / "lib" / "python-test" / "site-packages"
            site_packages.mkdir(parents=True)
            python = plugin_environment_python(selected)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")

    def fake_create_dist(**kwargs):
        build_calls.append(kwargs)
        wheel = Path(kwargs["dist_dir"]) / "local_provider-1.0.0.whl"
        wheel.parent.mkdir(parents=True)
        wheel.write_bytes(b"wheel")
        return SimpleNamespace(success=True, wheel_path=wheel, error=None)

    def fake_install(environment, requirement, **kwargs):
        selected = Path(requirement)
        assert selected.is_file()
        install_calls.append((Path(environment), selected, kwargs))

    def fake_inspect(environment, requirement, distribution):
        selected = Path(environment)
        site_packages = selected / "lib" / "python-test" / "site-packages"
        return (
            GlobalPluginRecord(
                requirement=requirement,
                distribution=distribution,
                display_name="local-provider",
                version="1.0.0",
                api_version=COMMAND_API_VERSION,
                commands=("local",),
                environment=selected,
                site_packages=site_packages,
                host_version="0.6.2",
                installed_at="2026-01-01T00:00:00+00:00",
            ),
            site_packages.relative_to(selected),
        )

    monkeypatch.chdir(project)
    monkeypatch.setattr("spork.plugins.venv.EnvBuilder", FakeBuilder)
    monkeypatch.setattr("spork.project.dist.create_dist", fake_create_dist)
    monkeypatch.setattr(manager, "_run_install", fake_install)
    monkeypatch.setattr(manager, "_inspect_staged", fake_inspect)

    installed = manager.add(".", quiet=True)

    expected_requirement = f"local-provider @ {project.resolve().as_uri()}"
    assert installed.requirement == expected_requirement
    assert installed.distribution == "local-provider"
    assert manager.records() == (installed,)
    assert len(build_calls) == 1
    build_call = build_calls[0]
    assert build_call["project_root"] == project.resolve()
    assert build_call["wheel"] is True
    assert build_call["sdist"] is False
    assert build_call["clean"] is True
    assert build_call["verbose"] is False
    assert not (project / ".spork-out").exists()
    assert not (project / "dist").exists()
    assert len(install_calls) == 1
    _environment, temporary_wheel, install_options = install_calls[0]
    assert install_options["display_requirement"] == expected_requirement
    assert not temporary_wheel.exists()
    assert sorted(path.name for path in installed.plugin_root.iterdir()) == [
        ".venv"
    ]
    broken = discover_global_commands(manager)
    repair = broken.diagnostics_for("local")[0].message
    assert f"spork plugin add {json.dumps(expected_requirement)}" in repair


def test_named_local_file_requirement_resolves_back_to_spork_project(
    tmp_path: Path,
):
    from spork.plugins import _resolve_install_target

    project = tmp_path / "provider"
    write_local_plugin_project(project)
    requirement = f"local-provider @ {project.resolve().as_uri()}"

    target = _resolve_install_target(requirement)

    assert target.requirement == requirement
    assert target.distribution == "local-provider"
    assert target.local_project == project.resolve()

    with pytest.raises(PluginInstallationError, match="named.*not 'other-provider'"):
        _resolve_install_target(f"other-provider @ {project.resolve().as_uri()}")


def test_local_spork_project_without_commands_is_rejected(tmp_path: Path):
    project = tmp_path / "plain-project"
    write_local_plugin_project(project, commands=False)

    with pytest.raises(PluginInstallationError, match="does not declare.*:commands"):
        PluginManager(tmp_path / "home").add(str(project))


def test_local_build_failure_preserves_previous_installation(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "provider"
    write_local_plugin_project(project)
    manager = PluginManager(tmp_path / "home")
    previous = plugin_record(manager, "local-provider", commands=("local",))
    marker = previous.plugin_root / "previous.txt"
    marker.write_text("kept", encoding="utf-8")
    save_records(manager, {previous.distribution: previous})
    original_registry = manager.registry_path.read_bytes()

    monkeypatch.setattr(
        "spork.project.dist.create_dist",
        lambda **kwargs: SimpleNamespace(
            success=False,
            wheel_path=None,
            error="source compilation failed",
        ),
    )

    with pytest.raises(PluginInstallationError, match="source compilation failed"):
        manager.add(str(project), quiet=True)

    assert manager.registry_path.read_bytes() == original_registry
    assert marker.read_text(encoding="utf-8") == "kept"
    assert manager.records() == (previous,)
    assert not any(
        path.name.endswith(".tmp") for path in manager.plugins_path.iterdir()
    )
    assert not (project / ".spork-out").exists()
    assert not (project / "dist").exists()


def test_explicit_non_project_path_has_actionable_error(tmp_path: Path):
    with pytest.raises(PluginInstallationError, match="has no spork.it"):
        PluginManager(tmp_path / "home").add(str(tmp_path))


def test_global_collision_rejects_new_plugin_and_preserves_owner(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    owner = plugin_record(manager)
    save_records(manager, {owner.distribution: owner})

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, environment):
            selected = Path(environment)
            site_packages = selected / "lib" / "python-test" / "site-packages"
            site_packages.mkdir(parents=True)

    def fake_inspect(environment, requirement, distribution):
        selected = Path(environment)
        site_packages = selected / "lib" / "python-test" / "site-packages"
        return (
            GlobalPluginRecord(
                requirement=requirement,
                distribution=distribution,
                display_name=distribution,
                version="1.0.0",
                api_version=COMMAND_API_VERSION,
                commands=("greet",),
                environment=selected,
                site_packages=site_packages,
                host_version="0.6.0",
                installed_at="2026-01-01T00:00:00+00:00",
            ),
            site_packages.relative_to(selected),
        )

    monkeypatch.setattr("spork.plugins.venv.EnvBuilder", FakeBuilder)
    monkeypatch.setattr(manager, "_run_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_inspect_staged", fake_inspect)

    with pytest.raises(PluginInstallationError, match="collision.*greet"):
        manager.add("other-provider")

    assert manager.records() == (owner,)
    assert owner.environment.is_dir()
    assert not (manager.plugins_path / "other-provider").exists()


def test_failed_replacement_preserves_previous_registry_and_environment(
    tmp_path: Path, monkeypatch
):
    manager = PluginManager(tmp_path / "home")
    previous = plugin_record(manager)
    marker = previous.plugin_root / "previous.txt"
    marker.write_text("kept", encoding="utf-8")
    save_records(manager, {previous.distribution: previous})
    original_registry = manager.registry_path.read_bytes()

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, environment):
            Path(environment).mkdir(parents=True)

    monkeypatch.setattr("spork.plugins.venv.EnvBuilder", FakeBuilder)
    monkeypatch.setattr(
        manager,
        "_run_install",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PluginInstallationError("staged install failed")
        ),
    )

    with pytest.raises(PluginInstallationError, match="staged install failed"):
        manager.add("fixture-provider")

    assert manager.registry_path.read_bytes() == original_registry
    assert marker.read_text(encoding="utf-8") == "kept"
    assert manager.records()[0].version == previous.version


def test_remove_deletes_only_selected_environment(tmp_path: Path):
    manager = PluginManager(tmp_path / "home")
    first = plugin_record(manager, "first-provider", commands=("first",))
    second = plugin_record(manager, "second-provider", commands=("second",))
    save_records(
        manager,
        {first.distribution: first, second.distribution: second},
    )

    removed = manager.remove("first_provider")

    assert removed.distribution == "first-provider"
    assert not first.plugin_root.exists()
    assert second.plugin_root.exists()
    assert [record.distribution for record in manager.records()] == [
        "second-provider"
    ]


def test_managed_child_marker_skips_project_delegation(monkeypatch):
    monkeypatch.setenv(discovery.MANAGED_PLUGIN_INVOCATION_ENV, "fixture-provider")
    from spork.cli import _delegate_to_project_toolchain

    assert _delegate_to_project_toolchain(["greet", "nested"]) is None
