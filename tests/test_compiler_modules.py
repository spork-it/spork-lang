"""Focused tests for the compiler's feature-module boundaries."""

import ast
import importlib.metadata
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packaging.version import Version

import spork.compiler
import spork.runtime
from spork.compiler.arity import is_multi_arity, parse_arity
from spork.compiler.context import compilation_context, get_compile_context
from spork.compiler.destructuring import compile_destructure
from spork.compiler.namespaces import compile_ns
from spork.compiler.pipeline import compile_forms_to_code
from spork.compiler.reader import read_str


def test_compilation_contexts_are_nested_and_isolated():
    with compilation_context(aot_imports=True) as outer:
        outer.current_ns = "outer"
        assert get_compile_context() is outer
        assert outer.aot_imports

        with compilation_context() as inner:
            assert get_compile_context() is inner
            assert inner.current_ns is None
            assert not inner.aot_imports
            inner.current_ns = "inner"

        assert get_compile_context() is outer
        assert outer.current_ns == "outer"


def test_namespace_lowering_tracks_normalized_python_aliases():
    form = read_str("(ns sample (:import [math :as math-lib]))")[0]

    with compilation_context() as ctx:
        statements = compile_ns(form[1:])

        assert ctx.current_ns == "sample"
        assert ctx.ns_aliases == {"math-lib": "math"}
        assert ast.unparse(ast.Module(body=statements, type_ignores=[])) == (
            "import math as math_lib"
        )


def test_python_backed_std_namespace_lowers_to_runtime_module_imports():
    form = read_str(
        "(ns sample (:require [std.string :as string-utils "
        ":refer [starts-with?]]))"
    )[0]

    with compilation_context() as ctx:
        statements = compile_ns(form[1:])

        assert ctx.ns_aliases == {"string-utils": "std.string"}
        assert ctx.ns_refers == {"starts-with?": "std.string"}
        assert ast.unparse(ast.Module(body=statements, type_ignores=[])) == (
            "import spork.std.string as string_utils\n"
            "from spork.std.string import starts_with_q"
        )


def test_runtime_and_stdlib_come_from_spork_runtime_distribution():
    from spork.std import prelude

    repository = Path(__file__).resolve().parents[1]
    runtime_path = Path(spork.runtime.__file__).resolve()

    runtime_version = Version(importlib.metadata.version("spork-runtime"))
    assert Version("0.1.0") <= runtime_version < Version("0.2.0")
    assert not runtime_path.is_relative_to(repository / "spork")
    assert not (repository / "spork" / "runtime").exists()
    assert not (repository / "spork" / "std").exists()
    assert all(
        spork.compiler.MACRO_ENV[name] is macro
        for name, macro in prelude.MACROS.items()
    )


def test_destructuring_is_an_independent_ast_lowerer():
    pattern = read_str("[first second & rest]")[0]
    statements = compile_destructure(
        pattern, ast.Name(id="value", ctx=ast.Load())
    )
    source = ast.unparse(ast.Module(body=statements, type_ignores=[]))

    assert "first = nth(" in source
    assert "second = nth(" in source
    assert "rest = vec(drop(2," in source


def test_arity_analysis_does_not_require_codegen_dispatch():
    arity_form = read_str("([x & rest] x)")[0]

    params, body, minimum, has_vararg, has_kwargs = parse_arity(arity_form)

    assert is_multi_arity([arity_form])
    assert len(params.items) == 3
    assert len(body) == 1
    assert minimum == 1
    assert has_vararg
    assert not has_kwargs


def test_pipeline_cold_import_initializes_recursive_lowering(tmp_path):
    script = textwrap.dedent(
        '''
        from spork.compiler.pipeline import eval_str
        from spork.runtime import Keyword

        source = """
        (def compute
          (fn [n]
            (try
              (loop [i n acc 0]
                (if (= i 0)
                  (match acc
                    6 :ok
                    _ :bad)
                  (recur (- i 1) (+ acc i))))
              (catch Exception error :error))))
        (def result (compute 3))
        """
        environment = eval_str(source)
        assert environment["result"] == Keyword("ok")
        '''
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_loop_expression_does_not_steal_enclosing_binding_helpers():
    source = """
    (defn choose [present]
      (let [prior 0]
        (let [workspace
              (if present
                (let [existing 41] (+ existing 1))
                0)]
          (loop [attempt 1]
            workspace))))
    (def result (choose true))
    """

    from spork.compiler.pipeline import eval_str

    assert eval_str(source)["result"] == 42


def test_parallel_compilations_keep_context_state_isolated():
    jobs = [(index, index % 2 == 0) for index in range(24)]

    def compile_job(job):
        index, aot_imports = job
        namespace = f"parallel.worker-{index}"
        alias = f"math-{index}"
        filename = f"parallel_{index}.spork"
        source = f"""
        (ns {namespace} (:import [math :as {alias}]))
        (def value-{index} ({alias}.sqrt 4))
        """

        with compilation_context(aot_imports=aot_imports) as ctx:
            compile_forms_to_code(source, filename)
            return {
                "namespace": ctx.current_ns,
                "filename": ctx.current_file,
                "aliases": dict(ctx.ns_aliases),
                "refers": dict(ctx.ns_refers),
                "aot_imports": ctx.aot_imports,
            }

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(compile_job, jobs))

    for (index, aot_imports), result in zip(jobs, results):
        assert result == {
            "namespace": f"parallel.worker-{index}",
            "filename": f"parallel_{index}.spork",
            "aliases": {f"math-{index}": "math"},
            "refers": {},
            "aot_imports": aot_imports,
        }


def test_runtime_modules_do_not_import_compiler():
    runtime_dir = Path(spork.runtime.__file__).parent
    offenders = []

    for path in sorted(runtime_dir.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            imported_modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            if any(
                name == "spork.compiler" or name.startswith("spork.compiler.")
                for name in imported_modules
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []


def test_feature_modules_do_not_import_codegen():
    compiler_dir = Path(spork.compiler.__file__).parent
    feature_modules = {
        "annotations.py",
        "arity.py",
        "ast_helpers.py",
        "calls.py",
        "context.py",
        "control_flow.py",
        "destructuring.py",
        "effects.py",
        "exceptions.py",
        "functions.py",
        "generated_names.py",
        "literals.py",
        "loops.py",
        "lowering.py",
        "namespaces.py",
        "patterns.py",
        "quoting.py",
    }
    offenders = []

    for filename in sorted(feature_modules):
        path = compiler_dir / filename
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            imports_codegen = (
                isinstance(node, ast.ImportFrom)
                and node.module == "spork.compiler.codegen"
            ) or (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "spork.compiler.codegen" for alias in node.names
                )
            )
            if imports_codegen:
                offenders.append(f"{filename}:{node.lineno}")

    assert offenders == []
