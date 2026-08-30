from pathlib import Path

from spork.project.scaffold import create_project


def test_hyphenated_project_uses_normalized_namespace_directory(tmp_path: Path):
    project = Path(create_project("hello-spork", str(tmp_path)))

    assert project.name == "hello-spork"
    assert (project / "src" / "hello_spork" / "core.spork").is_file()
    assert (project / "tests" / "hello_spork" / "core_test.spork").is_file()
    manifest = (project / "spork.it").read_text()
    assert ':main "hello-spork.core:main"' in manifest
    assert ':spork-version ">=0.5.0,<0.6"' in manifest
    assert ":dev-dependencies []" in manifest
    generated_test = (
        project / "tests" / "hello_spork" / "core_test.spork"
    ).read_text()
    assert "(deftest greet-works" in generated_test
    assert "run-tests" not in generated_test
    assert "src/hello_spork/core.spork" in (project / "README.md").read_text()
