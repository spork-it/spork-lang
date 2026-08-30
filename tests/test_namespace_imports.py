"""Tests for the separation between Spork requires and Python imports."""

import tempfile
import unittest
from pathlib import Path


class TestNamespaceImports(unittest.TestCase):
    def test_python_backed_std_require_supports_refers_and_macros(self):
        from spork.compiler.pipeline import eval_str

        environment = eval_str(
            """(ns tests.runtime-std
  (:require [std.string :refer [starts-with?]]
            [std.prelude :as prelude]))
(def string-result (starts-with? "spork" "spo"))
(def macro-result (prelude.when true 42))
"""
        )

        self.assertTrue(environment["string_result"])
        self.assertEqual(environment["macro_result"], 42)

    def test_require_rejects_python_module(self):
        from spork.compiler.pipeline import compile_forms_to_code

        source = "(ns tests.require-python (:require [json :as j]))"
        with self.assertRaisesRegex(
            SyntaxError, r"Use :import for ordinary Python modules"
        ):
            compile_forms_to_code(source, "require_python.spork")

    def test_exec_file_preserves_preconfigured_project_source_roots(self):
        from spork.compiler.pipeline import exec_file
        from spork.runtime import ns as runtime_ns

        original_roots = list(runtime_ns.SOURCE_ROOTS)
        original_registry = dict(runtime_ns.NAMESPACE_REGISTRY)
        try:
            with tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                source_root = project / "src"
                package = source_root / "sample"
                package.mkdir(parents=True)
                (project / "spork.it").write_text(
                    '{:name "sample" :version "0.1.0" :source-paths ["src"]}',
                    encoding="utf-8",
                )
                (package / "dependency.spork").write_text(
                    "(ns sample.dependency)\n(def answer 42)\n",
                    encoding="utf-8",
                )
                entrypoint = package / "core.spork"
                entrypoint.write_text(
                    """(ns sample.core
  (:require [sample.dependency :refer [answer]]))
(def result answer)
""",
                    encoding="utf-8",
                )

                runtime_ns.clear_registry()
                runtime_ns.init_source_roots(
                    extra_paths=[str(source_root)], include_cwd=False
                )
                configured_roots = list(runtime_ns.SOURCE_ROOTS)

                environment = exec_file(str(entrypoint))

                self.assertEqual(environment["result"], 42)
                self.assertEqual(runtime_ns.SOURCE_ROOTS, configured_roots)
        finally:
            runtime_ns.NAMESPACE_REGISTRY.clear()
            runtime_ns.NAMESPACE_REGISTRY.update(original_registry)
            runtime_ns.SOURCE_ROOTS = original_roots


if __name__ == "__main__":
    unittest.main()
