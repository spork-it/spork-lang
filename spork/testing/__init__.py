"""Native discovery and execution support for Spork tests."""

from spork.testing.discovery import (
    DiscoveredTest,
    DiscoveredTestFile,
    TestDiscoveryError,
    discover_test_files,
    has_deftest,
)

__all__ = [
    "DiscoveredTest",
    "DiscoveredTestFile",
    "TestDiscoveryError",
    "discover_test_files",
    "has_deftest",
]
