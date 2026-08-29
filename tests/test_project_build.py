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
 :spork-version ">=0.3.2,<0.4"
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
 :python-api {:package "fixture-lib"
              :from "fixture-lib.core"
              :exports ["Marker" "Box" "make-marker" "make-box" "result"]
              :aliases {"make-box" "box"}
              :version true
              :typed true}}
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
    assert (result.out_dir / "fixture_lib" / "py.typed").is_file()
    assert (result.out_dir / "fixture_lib" / "extras" / "__init__.py").is_file()
    assert not (project / "src" / "fixture_lib" / "__init__.py").exists()
    assert not (project / "src" / "fixture_lib" / "__init__.pyi").exists()

    initializer = (result.out_dir / "fixture_lib" / "__init__.py").read_text()
    assert "from .core import (" in initializer
    assert "make_box as make_box" in initializer
    assert "make_box as box" in initializer
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
        assert "fixture_lib/__init__.pyi" in names
        assert "fixture_lib/core.pyi" in names
        assert "fixture_lib/models.pyi" in names
        assert "fixture_lib/py.typed" in names
        assert "fixture_lib/extras/__init__.py" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode()
        assert 'Summary: A "quoted" fixture' in metadata
        assert "Requires-Dist: spork-lang<0.4,>=0.3.2" in metadata
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
        """(ns consumer (:require [fixture-lib.core :as fixture]))
(def consumed (fixture.result 11))
"""
    )
    assert env["consumed"][Keyword("answer")] == 12


def test_generated_python_api_refuses_to_overwrite_handwritten_initializer(
    tmp_path: Path,
):
    project = create_library_project(tmp_path)
    initializer = project / "src" / "fixture_lib" / "__init__.py"
    initializer.write_text("HANDWRITTEN = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hand-written file"):
        build_project(project_root=project, clean=True, verbose=False)


def test_project_config_loads_distribution_and_development_metadata(tmp_path: Path):
    project = create_library_project(tmp_path)
    config = ProjectConfig.load(str(project))

    assert config.dev_dependencies == ["pytest>=8"]
    assert config.optional_dependencies == {"test": ["pytest>=8"]}
    assert config.authors == [
        {"name": "Spork Tester", "email": "test@example.com"}
    ]
    assert config.spork_version == ">=0.3.2,<0.4"
    assert config.python_api is not None
    assert config.python_api.package == "fixture-lib"
    assert config.python_api.source_module == "fixture-lib.core"
    assert config.python_api.exports == [
        "Marker",
        "Box",
        "make-marker",
        "make-box",
        "result",
    ]
    assert config.python_api.aliases == {"make-box": "box"}
    assert config.python_api.include_version
    assert config.python_api.typed
