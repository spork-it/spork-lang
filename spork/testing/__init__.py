"""Native discovery and execution support for Spork tests."""

from spork.testing.discovery import (
    DiscoveredTestFile,
    TestDiscoveryError,
    discover_test_files,
    has_deftest,
)

__all__ = [
    "DiscoveredTestFile",
    "TestDiscoveryError",
    "discover_test_files",
    "has_deftest",
]
