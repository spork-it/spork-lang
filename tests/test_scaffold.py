from pathlib import Path

from spork.project.scaffold import create_project


def test_hyphenated_project_uses_normalized_namespace_directory(tmp_path: Path):
    project = Path(create_project("hello-spork", str(tmp_path)))

    assert project.name == "hello-spork"
    assert (project / "src" / "hello_spork" / "core.spork").is_file()
    assert ':main "hello-spork.core:main"' in (project / "spork.it").read_text()
    assert "src/hello_spork/core.spork" in (project / "README.md").read_text()
