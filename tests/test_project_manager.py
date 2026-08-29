"""Tests for isolated project environment installation."""

from contextlib import redirect_stdout
from io import BytesIO, TextIOWrapper
from pathlib import Path

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
            "spork-lang==0.4.0",
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
