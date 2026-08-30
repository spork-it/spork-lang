"""Tests for project-local Spork CLI delegation."""

from pathlib import Path
from types import SimpleNamespace

from spork.cli import _delegate_to_project_toolchain
from spork.project.config import ProjectConfig
from spork.project.manager import ProjectManager


def project_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        name="delegation-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
        spork_version=">=0.5,<0.6",
    )


def install_config(monkeypatch, config: ProjectConfig) -> None:
    monkeypatch.setattr(
        ProjectConfig,
        "load",
        classmethod(lambda cls, path=None: config),
    )


def test_project_command_delegates_to_compatible_environment(
    tmp_path: Path, monkeypatch
):
    config = project_config(tmp_path)
    install_config(monkeypatch, config)
    calls = []

    monkeypatch.setattr(
        ProjectManager, "active_spork_version", lambda self: "0.4.2"
    )
    monkeypatch.setattr(
        ProjectManager, "is_running_in_project_venv", lambda self: False
    )
    monkeypatch.setattr(
        ProjectManager, "get_project_spork_version", lambda self: "0.5.3"
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr("spork.cli.subprocess.run", fake_run)
    monkeypatch.chdir(tmp_path)

    assert _delegate_to_project_toolchain(["test"]) == 7
    assert calls == [
        (
            [config.venv_python, "-m", "spork", "test"],
            {"cwd": str(tmp_path), "check": False},
        )
    ]


def test_sync_bootstraps_when_project_toolchain_is_incompatible(
    tmp_path: Path, monkeypatch
):
    config = project_config(tmp_path)
    install_config(monkeypatch, config)

    monkeypatch.setattr(
        ProjectManager, "active_spork_version", lambda self: "0.4.2"
    )
    monkeypatch.setattr(
        ProjectManager, "is_running_in_project_venv", lambda self: False
    )
    monkeypatch.setattr(
        ProjectManager, "get_project_spork_version", lambda self: "0.4.2"
    )

    assert _delegate_to_project_toolchain(["sync"]) is None


def test_incompatible_project_command_requires_sync(
    tmp_path: Path, monkeypatch, capsys
):
    config = project_config(tmp_path)
    install_config(monkeypatch, config)

    monkeypatch.setattr(ProjectManager, "has_venv", lambda self: True)
    monkeypatch.setattr(
        ProjectManager, "active_spork_version", lambda self: "0.4.2"
    )
    monkeypatch.setattr(
        ProjectManager, "is_running_in_project_venv", lambda self: False
    )
    monkeypatch.setattr(
        ProjectManager, "get_project_spork_version", lambda self: "0.4.2"
    )

    assert _delegate_to_project_toolchain(["build"]) == 1
    error = capsys.readouterr().err
    assert "project environment has spork-lang==0.4.2" in error
    assert "Run `spork sync`" in error


def test_project_interpreter_does_not_delegate_again(tmp_path: Path, monkeypatch):
    config = project_config(tmp_path)
    install_config(monkeypatch, config)

    monkeypatch.setattr(
        ProjectManager, "active_spork_version", lambda self: "0.5.3"
    )
    monkeypatch.setattr(
        ProjectManager, "is_running_in_project_venv", lambda self: True
    )

    assert _delegate_to_project_toolchain(["run"]) is None
