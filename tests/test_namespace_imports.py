"""Tests for the separation between Spork requires and Python imports."""

import unittest


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


if __name__ == "__main__":
    unittest.main()
