"""Native runner for one isolated Spork test file."""

import argparse
import asyncio
import inspect
import json
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from spork.compiler import exec_file
from spork.runtime.ns import clear_registry
from spork.runtime.testing import SporkTest


@dataclass
class TestRunSummary:
    """Counts produced while running one Spork test file."""

    passed: int = 0
    failed: int = 0

    @property
    def success(self) -> bool:
        return self.failed == 0


async def _await_result(awaitable: Any) -> Any:
    return await awaitable


def _invoke_test(test: SporkTest) -> None:
    result = test.function()
    if inspect.isawaitable(result):
        asyncio.run(_await_result(result))


def _print_test_exception(exception: Exception) -> None:
    """Print a traceback beginning at the first generated Spork frame."""
    tb = exception.__traceback__
    while tb is not None and not tb.tb_frame.f_code.co_filename.endswith(".spork"):
        tb = tb.tb_next
    traceback.print_exception(type(exception), exception, tb, file=sys.stdout)


def run_test_file(path: Path, *, legacy: bool = False) -> TestRunSummary:
    """Load and run one test file, continuing after declared test failures."""
    summary = TestRunSummary()
    clear_registry()

    try:
        env = exec_file(str(path))
    except Exception:
        print("[error] file setup failed", flush=True)
        traceback.print_exc(file=sys.stdout)
        summary.failed += 1
        return summary

    tests = env.get("__spork_tests__", [])
    if tests:
        for test in tests:
            try:
                _invoke_test(test)
            except Exception as exc:
                print(f"[fail] {test.qualified_name}", flush=True)
                _print_test_exception(exc)
                summary.failed += 1
            else:
                print(f"[pass] {test.qualified_name}", flush=True)
                summary.passed += 1
        return summary

    if legacy:
        # Loading the file already executed its top-level assertions and other
        # script-style checks. Reaching this point means the legacy file passed.
        print("[pass] legacy file", flush=True)
        summary.passed += 1
        return summary

    print("[error] no declared tests found", flush=True)
    summary.failed += 1
    return summary


def _write_result(path: Path, summary: TestRunSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary)), encoding="utf-8")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Spork test file")
    parser.add_argument("file", type=Path)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--result", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    summary = run_test_file(args.file.resolve(), legacy=args.legacy)
    if args.result is not None:
        _write_result(args.result, summary)
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
