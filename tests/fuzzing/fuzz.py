#!/usr/bin/env python3
"""Base fuzzing framework for Spork.

This module provides a base class for fuzz tests and a runner to execute them.

Usage:
    python -m tests.fuzzing.fuzz [--examples N] [--steps N] [--seed N] [pattern...]

Example:
    python -m tests.fuzzing.fuzz                    # Run all fuzz tests
    python -m tests.fuzzing.fuzz vector             # Run tests matching 'vector'
    python -m tests.fuzzing.fuzz --examples 5000    # Run with custom params
"""

import abc
import argparse
import gc
import importlib
import random
import resource
import sys
import time
from pathlib import Path
from typing import Any


def get_mem_mb() -> float:
    """Get current RSS memory in MB."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def random_value() -> Any:
    """Generate a random hashable value."""
    choice = random.randint(0, 5)
    if choice == 0:
        return random.randint(-10000, 10000)
    elif choice == 1:
        return random.random() * 1000
    elif choice == 2:
        return "".join(random.choices("abcdefghij", k=random.randint(0, 20)))
    elif choice == 3:
        return None
    elif choice == 4:
        return random.choice([True, False])
    else:
        return (random.randint(0, 100), random.randint(0, 100))


class Fuzzer(abc.ABC):
    """Base class for fuzz tests.

    Subclasses must implement:
        - name: class attribute with the fuzzer name
        - reset(): reset state for a new example
        - do_random_operation(): perform one random operation
        - check_invariants(): verify state is correct

    Optionally override:
        - setup(): called once before running
        - teardown(): called once after running
        - get_stats(): return dict of stats to display
    """

    name: str = "unnamed"

    def __init__(self):
        self.operations = 0
        self.op_counts: dict[str, int] = {}

    def record_op(self, name: str):
        """Record that an operation was performed."""
        self.operations += 1
        self.op_counts[name] = self.op_counts.get(name, 0) + 1

    def setup(self):
        """Called once before running. Override if needed."""
        pass

    def teardown(self):
        """Called once after running. Override if needed."""
        pass

    @abc.abstractmethod
    def reset(self):
        """Reset state for a new example."""
        pass

    @abc.abstractmethod
    def do_random_operation(self):
        """Perform one random operation."""
        pass

    @abc.abstractmethod
    def check_invariants(self):
        """Verify that the current state is correct.

        Should raise AssertionError if invariants are violated.
        """
        pass

    def get_stats(self) -> dict[str, Any]:
        """Return additional stats to display. Override if needed."""
        return {}


class FuzzRunner:
    """Runs fuzz tests and reports results."""

    def __init__(
        self,
        examples: int = 1000,
        steps: int = 200,
        seed: int | None = None,
        memory_limit_mb: float = 100,
    ):
        self.examples = examples
        self.steps = steps
        self.memory_limit_mb = memory_limit_mb

        if seed is not None:
            self.seed = seed
        else:
            self.seed = random.randint(0, 2**32)
        random.seed(self.seed)

    def run(self, fuzzer: Fuzzer) -> bool:
        """Run a fuzzer. Returns True if passed, False if failed."""
        print(f"Fuzz: {fuzzer.name}")
        print(f"  Examples: {self.examples:,}")
        print(f"  Steps per example: {self.steps}")
        print(f"  Seed: {self.seed}")
        print()

        initial_mem = get_mem_mb()
        start_time = time.time()
        last_print = start_time
        example = 0
        step = 0

        fuzzer.setup()

        try:
            for example in range(self.examples):
                fuzzer.reset()

                for step in range(self.steps):
                    fuzzer.do_random_operation()
                    fuzzer.check_invariants()

                # Progress output every second
                now = time.time()
                if now - last_print >= 1.0:
                    elapsed = now - start_time
                    rate = (example + 1) / elapsed
                    current_mem = get_mem_mb()
                    delta_mem = current_mem - initial_mem

                    print(
                        f"[{elapsed:6.1f}s] "
                        f"ex:{example + 1:>6,} | "
                        f"ops:{fuzzer.operations:>8,} | "
                        f"{rate:>5.1f}/s | "
                        f"rss:{current_mem:.0f}MB ({delta_mem:+.0f}MB)"
                    )
                    last_print = now

            # Final stats
            elapsed = time.time() - start_time
            final_mem = get_mem_mb()
            delta_mem = final_mem - initial_mem

            print()
            print(
                f"Completed {self.examples:,} examples, "
                f"{fuzzer.operations:,} operations in {elapsed:.1f}s"
            )
            print(f"  Operations: {fuzzer.op_counts}")

            # Show custom stats
            custom_stats = fuzzer.get_stats()
            for key, value in custom_stats.items():
                print(f"  {key}: {value}")

            print(
                f"  Memory: {initial_mem:.0f}MB -> {final_mem:.0f}MB "
                f"({delta_mem:+.0f}MB)"
            )

            fuzzer.teardown()

            if delta_mem > self.memory_limit_mb:
                print(
                    f"  FAILED: Memory grew by {delta_mem:.0f}MB "
                    f"(limit: {self.memory_limit_mb}MB)"
                )
                return False
            else:
                print("  PASSED")
                return True

        except AssertionError as e:
            print()
            print(f"FAILED at example {example + 1}, step {step + 1}!")
            print(f"  Seed: {self.seed}")
            print(f"  Error: {e}")
            fuzzer.teardown()
            return False

        except KeyboardInterrupt:
            print()
            print(f"Interrupted at example {example + 1}")
            fuzzer.teardown()
            return False


def discover_fuzzers() -> list[type[Fuzzer]]:
    """Discover all Fuzzer subclasses in the fuzzing package."""
    fuzzers = []

    # Get the directory containing this file
    fuzzing_dir = Path(__file__).parent

    # Import all fuzz_*.py modules
    for path in fuzzing_dir.glob("fuzz_*.py"):
        module_name = path.stem
        try:
            module = importlib.import_module(f"tests.fuzzing.{module_name}")

            # Find Fuzzer subclasses in the module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Fuzzer)
                    and attr is not Fuzzer
                ):
                    fuzzers.append(attr)
        except ImportError as e:
            print(f"Warning: Could not import {module_name}: {e}")

    return fuzzers


def run_suite(
    examples: int = 1000,
    steps: int = 200,
    seed: int | None = None,
    patterns: list[str] | None = None,
    memory_limit_mb: float = 100,
) -> int:
    """Run the fuzz test suite.

    Args:
        examples: Number of examples per fuzzer
        steps: Steps per example
        seed: Random seed (None for random)
        patterns: Optional list of patterns to filter fuzzers by name
        memory_limit_mb: Memory growth limit before failing

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    fuzzers = discover_fuzzers()

    if not fuzzers:
        print("No fuzzers found!")
        return 1

    # Filter by patterns if provided
    if patterns:
        filtered = []
        for fuzzer_cls in fuzzers:
            for pattern in patterns:
                if pattern.lower() in fuzzer_cls.name.lower():
                    filtered.append(fuzzer_cls)
                    break
        fuzzers = filtered

    if not fuzzers:
        print("No fuzzers matched the given patterns!")
        return 1

    print(f"Running {len(fuzzers)} fuzzer(s)")
    print("=" * 60)
    print()

    results = []
    runner = FuzzRunner(
        examples=examples,
        steps=steps,
        seed=seed,
        memory_limit_mb=memory_limit_mb,
    )

    for fuzzer_cls in fuzzers:
        fuzzer = fuzzer_cls()
        passed = runner.run(fuzzer)
        results.append((fuzzer.name, passed))
        print()
        print("=" * 60)
        print()

        # Force GC between fuzzers
        gc.collect()

    # Summary
    print("Summary")
    print("-" * 40)

    passed = sum(1 for _, p in results if p)
    failed = sum(1 for _, p in results if not p)

    for name, result in results:
        status = "PASSED" if result else "FAILED"
        print(f"  {name}: {status}")

    print()
    print(f"Passed: {passed}, Failed: {failed}")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Run fuzz test suite")
    parser.add_argument(
        "--examples",
        "-n",
        type=int,
        default=1000,
        help="Number of examples per fuzzer (default: 1000)",
    )
    parser.add_argument(
        "--steps",
        "-s",
        type=int,
        default=200,
        help="Steps per example (default: 200)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--memory-limit",
        type=float,
        default=100,
        help="Memory growth limit in MB (default: 100)",
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        help="Optional patterns to filter fuzzers by name",
    )
    args = parser.parse_args()

    sys.exit(
        run_suite(
            examples=args.examples,
            steps=args.steps,
            seed=args.seed,
            patterns=args.patterns if args.patterns else None,
            memory_limit_mb=args.memory_limit,
        )
    )


if __name__ == "__main__":
    main()
