"""Tests for the separation between Spork requires and Python imports."""

import unittest


class TestNamespaceImports(unittest.TestCase):
    def test_require_rejects_python_module(self):
        from spork.compiler.codegen import compile_forms_to_code

        source = "(ns tests.require-python (:require [json :as j]))"
        with self.assertRaisesRegex(
            SyntaxError, r"Use :import for Python modules"
        ):
            compile_forms_to_code(source, "require_python.spork")


if __name__ == "__main__":
    unittest.main()
