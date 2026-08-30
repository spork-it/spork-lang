import asyncio

import pytest

from spork.compiler import compile_forms_to_code, eval_str
from spork.runtime import SortedVector, Vector


def test_for_and_sorted_for_are_eager_expression_forms():
    environment = eval_str(
        """
        (def seen (list))
        (def values
          (for [x [3 1 2]]
            (seen.append x)
            (* x 10)))
        (def ranked
          (sorted-for [x values] x :reverse true))
        """
    )

    assert isinstance(environment["values"], Vector)
    assert environment["values"] == Vector([30, 10, 20])
    assert environment["seen"] == [3, 1, 2]
    assert isinstance(environment["ranked"], SortedVector)
    assert list(environment["ranked"]) == [30, 20, 10]


def test_async_for_eagerly_resolves_to_a_persistent_vector():
    environment = eval_str(
        """
        (defn ^async ^generator source []
          (yield 1)
          (yield 2)
          (yield 3))
        (defn ^async collect []
          (async-for [x (source)] (* x x)))
        """
    )

    result = asyncio.run(environment["collect"]())
    assert isinstance(result, Vector)
    assert result == Vector([1, 4, 9])


def test_iteration_expression_syntax_is_validated():
    with pytest.raises(SyntaxError, match="for requires a body expression"):
        compile_forms_to_code("(def result (for [x [1 2 3]]))")

    with pytest.raises(SyntaxError, match="sorted-for requires a body expression"):
        compile_forms_to_code("(def result (sorted-for [x [1 2 3]]))")

    with pytest.raises(SyntaxError, match="async-for requires a body expression"):
        compile_forms_to_code("(async-for [x values])")

    with pytest.raises(SyntaxError, match="Unknown option in sorted-for"):
        compile_forms_to_code(
            "(def result (sorted-for [x [1 2 3]] x :unknown true))"
        )


def test_old_vector_literal_spelling_is_not_a_comprehension():
    with pytest.raises(NameError):
        eval_str("(def result [for [x [1 2 3]] (* x x)])")


def test_redundant_for_all_macro_is_not_available():
    with pytest.raises(NameError):
        eval_str("(def result (for-all [x [1 2 3]] (* x x)))")
