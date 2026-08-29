"""End-to-end tests for building distributable Spork libraries."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from spork.compiler.loader import compile_file_to_python
from spork.project.build import build_project
from spork.project.config import ProjectConfig
from spork.project.dist import create_dist
from spork.runtime import Keyword
from spork.runtime.ns import clear_registry, init_source_roots


def create_library_project(root: Path) -> Path:
    package = root / "src" / "fixture_lib"
    extras = package / "extras"
    extras.mkdir(parents=True)

    (root / "spork.it").write_text(
        """{:name "fixture-lib"
 :version "1.2.3"
 :description "A \\"quoted\\" fixture"
 :requires-python ">=3.10"
 :spork-version ">=0.4.0,<0.5"
 :readme "README.md"
 :license "MIT"
 :license-file "LICENSE"
 :authors [{:name "Spork Tester" :email "test@example.com"}]
 :keywords ["spork" "state"]
 :classifiers ["Programming Language :: Python :: 3"]
 :urls {"Homepage" "https://example.com/fixture"}
 :dependencies []
 :dev-dependencies ["pytest>=8"]
 :optional-dependencies {:test ["pytest>=8"]}
 :source-paths ["src"]
 :test-paths ["tests"]
 :api {:from "fixture-lib.core"
       :spork {:namespace "fixture-lib"
               :exports ["Marker" "Box" "make-marker" "make-box" "marker?" "result"]}
       :python {:package "fixture-lib"
                :exports ["Marker" "Box" "make-marker" "make-box" "result"]
                :aliases {"make-box" "box"}
                :version true
                :typed true}}}
""",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Fixture library\n", encoding="utf-8")
    (root / "LICENSE").write_text("Fixture license\n", encoding="utf-8")

    (package / "models.spork").write_text(
        """(ns fixture-lib.models
  (:import [typing :refer [Generic TypeVar]]))

(def T (TypeVar "T"))

(defclass Marker []
  (defn __init__ [self ^int value]
    (set! self.value value)))

(defclass Box [(Generic T)]
  (defn __init__ [self ^T value]
    (set! self._value value))

  (defn ^property ^T boxed-value [self]
    self._value))

(defn ^(Box T) make-box [^T value]
  (Box value))

(defmacro increment [value]
  `(+ ~value 1))

(defn make-data [value]
  {:answer value})
""",
        encoding="utf-8",
    )
    (package / "core.spork").write_text(
        """(ns fixture-lib.core
  (:require [fixture-lib.models :as models
             :refer [Marker Box make-box make-data increment]]))

(defn ^Marker make-marker [^int value]
  (models.Marker value))

(defn ^bool marker? [value]
  (isinstance value Marker))

(defn result [value]
  (assoc (make-data (increment value)) :more 7))
""",
        encoding="utf-8",
    )
    (extras / "__init__.py").write_text("ENABLED = True\n", encoding="utf-8")
    return root


def forget_fixture_modules() -> None:
    for name in list(sys.modules):
        if name == "fixture_lib" or name.startswith("fixture_lib."):
            del sys.modules[name]


def test_build_compiles_multi_module_library_for_normal_python_import(
    tmp_path: Path, monkeypatch
):
    project = create_library_project(tmp_path)
    monkeypatch.chdir(project / "src" / "fixture_lib")

    result = build_project(clean=True, verbose=False)

    assert result.success
    assert result.out_dir == (project / ".spork-out").resolve()
    generated = (result.out_dir / "fixture_lib" / "core.py").read_text(
        encoding="utf-8"
    )
    assert "setup_runtime_env" in generated
    assert "import fixture_lib.models as models" in generated
    assert "from fixture_lib.models import Marker, Box, make_box, make_data" in generated
    assert "import increment" not in generated
    assert (result.out_dir / "fixture_lib" / "core.spork").is_file()
    assert (result.out_dir / "fixture_lib" / "core.pyi").is_file()
    assert (result.out_dir / "fixture_lib" / "models.pyi").is_file()
    assert (result.out_dir / "fixture_lib" / "__init__.py").is_file()
    assert (result.out_dir / "fixture_lib" / "__init__.pyi").is_file()
    assert (result.out_dir / "fixture_lib" / "__init__.spork").is_file()
    assert (result.out_dir / "fixture_lib" / "py.typed").is_file()
    assert (result.out_dir / "fixture_lib" / "extras" / "__init__.py").is_file()
    assert not (project / "src" / "fixture_lib" / "__init__.py").exists()
    assert not (project / "src" / "fixture_lib" / "__init__.pyi").exists()

    spork_initializer = (
        result.out_dir / "fixture_lib" / "__init__.spork"
    ).read_text()
    assert "(ns fixture-lib" in spork_initializer
    assert (
        "[fixture-lib.core :refer [Marker Box make-marker make-box marker? result]]"
        in spork_initializer
    )

    initializer = (result.out_dir / "fixture_lib" / "__init__.py").read_text()
    assert "from .core import (" in initializer
    assert "make_box as make_box" in initializer
    assert "make_box as box" in initializer
    assert "marker_q as marker_q" in initializer
    assert "__version__ = '1.2.3'" in initializer
    models_stub = (result.out_dir / "fixture_lib" / "models.pyi").read_text()
    assert "T = TypeVar('T')" in models_stub
    assert "class Box(Generic[T])" in models_stub
    assert "def boxed_value(self) -> T" in models_stub
    assert "def make_box(value: T) -> Box[T]" in models_stub

    source_map = (result.out_dir / "fixture_lib" / "core.spork.map.json").read_text(
        encoding="utf-8"
    )
    assert '"spork_file": "fixture_lib/core.spork"' in source_map

    forget_fixture_modules()
    monkeypatch.syspath_prepend(str(result.out_dir))
    fixture = importlib.import_module("fixture_lib")
    marker = fixture.make_marker(3)
    box = fixture.box("typed")
    assert type(marker) is fixture.Marker
    assert fixture.marker_q(marker)
    assert type(box) is fixture.Box
    assert box.boxed_value == "typed"
    assert fixture.__version__ == "1.2.3"
    assert fixture.result(4)[Keyword("answer")] == 5

    usage = project / "typing_usage.py"
    usage.write_text(
        """from fixture_lib import Box, make_box\n\nbox: Box[int] = make_box(3)\nvalue: int = box.boxed_value\n""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["MYPYPATH"] = str(result.out_dir)
    checked = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(usage)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_dist_contains_metadata_sources_and_works_for_both_consumers(
    tmp_path: Path, monkeypatch
):
    project = create_library_project(tmp_path / "project")
    result = create_dist(project_root=project, clean=True, verbose=False)

    assert result.success, result.error
    assert result.wheel_path is not None
    assert result.sdist_path is not None

    with zipfile.ZipFile(result.wheel_path) as wheel:
        names = set(wheel.namelist())
        assert "fixture_lib/core.py" in names
        assert "fixture_lib/core.spork" in names
        assert "fixture_lib/core.spork.map.json" in names
        assert "fixture_lib/models.spork" in names
        assert "fixture_lib/__init__.spork" in names
        assert "fixture_lib/__init__.pyi" in names
        assert "fixture_lib/core.pyi" in names
        assert "fixture_lib/models.pyi" in names
        assert "fixture_lib/py.typed" in names
        assert "fixture_lib/extras/__init__.py" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode()
        assert 'Summary: A "quoted" fixture' in metadata
        assert "Requires-Dist: spork-lang<0.5,>=0.4.0" in metadata
        assert "Provides-Extra: test" in metadata
        assert "Project-URL: Homepage, https://example.com/fixture" in metadata

        installed = tmp_path / "site-packages"
        wheel.extractall(installed)

    with tarfile.open(result.sdist_path) as sdist:
        names = set(sdist.getnames())
        prefix = "fixture_lib-1.2.3"
        assert f"{prefix}/README.md" in names
        assert f"{prefix}/LICENSE" in names
        assert f"{prefix}/fixture_lib/core.py" in names
        assert f"{prefix}/fixture_lib/core.spork" in names
        assert f"{prefix}/fixture_lib/__init__.spork" in names

    forget_fixture_modules()
    monkeypatch.syspath_prepend(str(installed))
    fixture = importlib.import_module("fixture_lib")
    assert type(fixture.make_marker(9)) is fixture.Marker
    assert fixture.result(9)[Keyword("more")] == 7

    # A Spork consumer resolves packaged source directly from site-packages.
    clear_registry()
    init_source_roots(include_cwd=False)
    from spork.compiler.codegen import eval_str

    env = eval_str(
        """(ns consumer (:require [fixture-lib :as fixture]))
(assert (fixture.marker? (fixture.make-marker 1)))
(def consumed (fixture.result 11))
"""
    )
    assert env["consumed"][Keyword("answer")] == 12

    # AOT consumers import the generated Python runtime bridge while retaining
    # the Spork-specific public names from the package namespace.
    generated, _ = compile_file_to_python(
        """(ns aot-consumer (:require [fixture-lib :as fixture]))
(def marker-valid (fixture.marker? (fixture.make-marker 2)))
(def aot-consumed (fixture.result 5))
""",
        str(tmp_path / "aot_consumer.spork"),
    )
    aot_env: dict[str, object] = {}
    exec(compile(generated, "<aot-consumer>", "exec"), aot_env, aot_env)
    assert aot_env["marker_valid"] is True
    assert aot_env["aot_consumed"][Keyword("answer")] == 6


def test_spork_only_api_generates_package_and_aot_bridge(
    tmp_path: Path, monkeypatch
):
    package = tmp_path / "src" / "spork_only"
    package.mkdir(parents=True)
    (tmp_path / "spork.it").write_text(
        """{:name "spork-only"
 :version "1.0.0"
 :source-paths ["src"]
 :api {:from "spork-only.core"
       :spork {:namespace "spork-only"
               :exports ["answer" "answer?"]}}}
""",
        encoding="utf-8",
    )
    (package / "core.spork").write_text(
        """(ns spork-only.core)
(def answer 42)
(defn answer? [value] (= value answer))
""",
        encoding="utf-8",
    )

    result = build_project(project_root=tmp_path, clean=True, verbose=False)

    assert result.success
    assert (result.out_dir / "spork_only" / "__init__.spork").is_file()
    assert (result.out_dir / "spork_only" / "__init__.py").is_file()
    assert not (result.out_dir / "spork_only" / "__init__.pyi").exists()
    assert not (result.out_dir / "spork_only" / "py.typed").exists()

    monkeypatch.syspath_prepend(str(result.out_dir))
    module = importlib.import_module("spork_only")
    assert module.answer == 42
    assert module.answer_q(42)
    assert module.__all__ == []


def test_generated_python_api_refuses_to_overwrite_handwritten_initializer(
    tmp_path: Path,
):
    project = create_library_project(tmp_path)
    initializer = project / "src" / "fixture_lib" / "__init__.py"
    initializer.write_text("HANDWRITTEN = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hand-written file"):
        build_project(project_root=project, clean=True, verbose=False)


def test_generated_spork_api_refuses_to_overwrite_handwritten_initializer(
    tmp_path: Path,
):
    project = create_library_project(tmp_path)
    initializer = project / "src" / "fixture_lib" / "__init__.spork"
    initializer.write_text("(ns fixture-lib)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hand-written file"):
        build_project(project_root=project, clean=True, verbose=False)


def test_legacy_python_api_manifest_key_is_rejected(tmp_path: Path):
    project = create_library_project(tmp_path)
    manifest = project / "spork.it"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(":api {", ":python-api {"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=":python-api was replaced by :api"):
        ProjectConfig.load(str(project))


def test_project_config_loads_distribution_and_development_metadata(tmp_path: Path):
    project = create_library_project(tmp_path)
    config = ProjectConfig.load(str(project))

    assert config.dev_dependencies == ["pytest>=8"]
    assert config.optional_dependencies == {"test": ["pytest>=8"]}
    assert config.authors == [
        {"name": "Spork Tester", "email": "test@example.com"}
    ]
    assert config.spork_version == ">=0.4.0,<0.5"
    assert config.api is not None
    assert config.api.source_module == "fixture-lib.core"
    assert config.api.spork is not None
    assert config.api.spork.namespace == "fixture-lib"
    assert config.api.spork.exports == [
        "Marker",
        "Box",
        "make-marker",
        "make-box",
        "marker?",
        "result",
    ]
    assert config.api.python is not None
    assert config.api.python.package == "fixture-lib"
    assert config.api.python.exports == [
        "Marker",
        "Box",
        "make-marker",
        "make-box",
        "result",
    ]
    assert config.api.python.aliases == {"make-box": "box"}
    assert config.api.python.include_version
    assert config.api.python.typed
