"""Runtime support for declared Spork tests.

Test registries are module-local. Compiled ``deftest`` declarations add
``SporkTest`` descriptors to the current module's ``__spork_tests__`` list,
but test bodies are only invoked by the Spork test runner.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class SporkTest:
    """A test declared by a top-level ``deftest`` form."""

    name: str
    function: Callable[[], Any]
    file: str
    line: int
    namespace: Optional[str] = None

    @property
    def qualified_name(self) -> str:
        """Return the namespace-qualified display name for this test."""
        if self.namespace:
            return f"{self.namespace}/{self.name}"
        return self.name


def register_spork_test(
    registry: list[SporkTest],
    name: str,
    function: Callable[[], Any],
    file: str,
    line: int,
    namespace: Optional[str] = None,
) -> SporkTest:
    """Create a descriptor and append it to a module-local registry."""
    test = SporkTest(
        name=name,
        function=function,
        file=file,
        line=line,
        namespace=namespace,
    )
    registry.append(test)
    return test


__all__ = ["SporkTest", "register_spork_test"]
