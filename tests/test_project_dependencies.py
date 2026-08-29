"""Tests for editing dependencies in a project manifest."""

from pathlib import Path

from spork.cli import _main
from spork.project.config import ProjectConfig
from spork.project.dependencies import add_dependencies, remove_dependencies


def write_manifest(project: Path, dependencies: str = "[]") -> Path:
    project.mkdir(parents=True)
    manifest = project / "spork.it"
    manifest.write_text(
        f'''{{:name "dependency-fixture"
 :version "0.1.0"
 :dependencies {dependencies}
 :source-paths ["src"]}}
''',
        encoding="utf-8",
    )
    return manifest


def test_add_command_walks_up_and_reports_the_manifest(
    tmp_path: Path, monkeypatch, capsys
):
    manifest = write_manifest(tmp_path / "project")
    nested = manifest.parent / "src" / "fixture" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert _main(["add", "httpx", "rich>=13"]) == 0

    assert ProjectConfig.load(str(manifest)).dependencies == ["httpx", "rich>=13"]
    assert capsys.readouterr().out.splitlines() == [
        f"Adding httpx to {manifest.resolve()}",
        f"Adding rich>=13 to {manifest.resolve()}",
    ]


def test_remove_command_uses_closest_project_and_matches_distribution_name(
    tmp_path: Path, monkeypatch, capsys
):
    outer_manifest = write_manifest(tmp_path / "outer", '["outer-package"]')
    inner_manifest = write_manifest(
        outer_manifest.parent / "inner", '["HTTPX[socks]>=0.27" "rich"]'
    )
    nested = inner_manifest.parent / "src" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert _main(["remove", "httpx", "missing-package"]) == 0

    assert ProjectConfig.load(str(inner_manifest)).dependencies == ["rich"]
    assert ProjectConfig.load(str(outer_manifest)).dependencies == ["outer-package"]
    assert capsys.readouterr().out.splitlines() == [
        f"Removing httpx from {inner_manifest.resolve()}",
        f"missing-package is not in {inner_manifest.resolve()}",
    ]


def test_dependency_edits_preserve_surrounding_manifest_source(tmp_path: Path):
    manifest = write_manifest(
        tmp_path / "project",
        '''["httpx>=0.27" ; HTTP client
                "rich"]''',
    )

    changes = add_dependencies(manifest, ["httpx>=0.28", "anyio"])

    assert [change.action for change in changes] == ["updated", "added"]
    content = manifest.read_text(encoding="utf-8")
    assert "; HTTP client" in content
    assert ProjectConfig.load(str(manifest)).dependencies == [
        "httpx>=0.28",
        "rich",
        "anyio",
    ]

    changes = remove_dependencies(manifest, ["httpx", "anyio"])

    assert [change.action for change in changes] == ["removed", "removed"]
    assert "; HTTP client" in manifest.read_text(encoding="utf-8")
    assert ProjectConfig.load(str(manifest)).dependencies == ["rich"]


def test_add_inserts_dependencies_field_when_manifest_omits_it(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / "spork.it"
    manifest.write_text(
        '''{:name "dependency-fixture"
 :version "0.1.0"}
''',
        encoding="utf-8",
    )

    changes = add_dependencies(manifest, ["httpx"])

    assert [change.action for change in changes] == ["added"]
    assert ProjectConfig.load(str(manifest)).dependencies == ["httpx"]


def test_add_without_a_parent_project_returns_an_error(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    assert _main(["add", "httpx"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Could not find spork.it" in captured.err
