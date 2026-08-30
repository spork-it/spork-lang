"""Tests for isolated project environment installation."""

from contextlib import redirect_stdout
from io import BytesIO, TextIOWrapper
from pathlib import Path
from types import SimpleNamespace

import pytest
import spork

from spork.project.config import ProjectConfig
from spork.project.manager import ProjectManager


def test_installed_toolchain_is_pip_installed_with_transitive_dependencies(
    tmp_path: Path, monkeypatch
):
    config = ProjectConfig(
        name="environment-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
        dependencies=["example-runtime>=1"],
        dev_dependencies=["example-dev>=2"],
    )
    manager = ProjectManager(config)
    commands: list[list[str]] = []

    monkeypatch.setattr(manager, "_find_spork_source_dir", lambda: None)
    monkeypatch.setattr(manager, "ensure_venv", lambda: True)
    monkeypatch.setattr(
        manager,
        "_run_pip",
        lambda args, **kwargs: commands.append(args),
    )

    output_bytes = BytesIO()
    output = TextIOWrapper(output_bytes, encoding="cp1252")
    with redirect_stdout(output):
        assert manager.install_dependencies(dev=True, quiet=True)
    output.flush()

    assert "[ok] All dependencies installed" in output_bytes.getvalue().decode("cp1252")
    assert commands == [
        [
            "install",
            f"spork-lang=={spork.__version__}",
            "example-runtime>=1",
            "example-dev>=2",
        ]
    ]


def test_source_toolchain_remains_an_editable_install(tmp_path: Path, monkeypatch):
    config = ProjectConfig(
        name="environment-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
    )
    manager = ProjectManager(config)
    source = tmp_path / "spork-lang"

    monkeypatch.setattr(manager, "_find_spork_source_dir", lambda: str(source))

    assert manager._get_spork_install_spec() == f"-e {source}"


def test_compatible_active_toolchain_is_pinned_during_sync(
    tmp_path: Path, monkeypatch
):
    config = ProjectConfig(
        name="environment-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
        spork_version=">=0.5,<0.6",
    )
    manager = ProjectManager(config)

    monkeypatch.setattr(manager, "_find_spork_source_dir", lambda: None)

    assert manager._get_spork_install_spec() == f"spork-lang=={spork.__version__}"


def test_incompatible_active_toolchain_resolves_manifest_requirement(
    tmp_path: Path, monkeypatch
):
    config = ProjectConfig(
        name="environment-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
        spork_version=">=9,<10",
    )
    manager = ProjectManager(config)
    source = tmp_path / "spork-lang"

    monkeypatch.setattr(manager, "_find_spork_source_dir", lambda: str(source))

    assert manager._get_spork_install_spec() == "spork-lang>=9,<10"


def test_invalid_manifest_toolchain_requirement_is_rejected(tmp_path: Path):
    (tmp_path / "spork.it").write_text(
        '{:name "invalid" :version "0.1.0" :spork-version "not a range"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=":spork-version must be a version specifier"):
        ProjectConfig.load(str(tmp_path))


def test_project_toolchain_version_is_read_from_its_interpreter(
    tmp_path: Path, monkeypatch
):
    config = ProjectConfig(
        name="environment-fixture",
        version="0.1.0",
        project_root=str(tmp_path),
        spork_version=">=0.5,<0.6",
    )
    manager = ProjectManager(config)
    calls = []

    monkeypatch.setattr(manager, "has_venv", lambda: True)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="0.5.3\n")

    monkeypatch.setattr("spork.project.manager.subprocess.run", fake_run)

    assert manager.get_project_spork_version() == "0.5.3"
    assert manager.spork_version_satisfies_project("0.5.3")
    assert not manager.spork_version_satisfies_project("0.4.2")
    assert calls[0][0][0] == config.venv_python
    assert calls[0][1]["cwd"] == str(tmp_path)
