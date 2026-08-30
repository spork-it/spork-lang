#!/usr/bin/env python3
"""Run the repository's declared Spork tests in isolated processes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from spork.testing.discovery import discover_test_files

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = (
        [path.resolve() for path in args.files]
        if args.files
        else [
            discovered.path
            for discovered in discover_test_files([], [PROJECT_ROOT / "tests"])
        ]
    )
    if not files:
        print("No Spork test files found.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    passed = 0
    failed = 0

    with tempfile.TemporaryDirectory(prefix="spork-lang-tests-") as result_dir:
        for index, path in enumerate(files):
            try:
                display_path = path.relative_to(PROJECT_ROOT)
            except ValueError:
                display_path = path
            print(f"\n=== Running {display_path} ===", flush=True)

            result_path = Path(result_dir) / f"{index}.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "spork.testing.runner",
                    str(path),
                    "--result",
                    str(result_path),
                ],
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
            )

            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                file_passed = int(result["passed"])
                file_failed = int(result["failed"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                print(
                    f"FAILED: runner did not produce a valid result for {display_path}"
                )
                failed += 1
                continue

            passed += file_passed
            failed += file_failed
            if completed.returncode and file_failed == 0:
                print(f"FAILED: runner exited unexpectedly for {display_path}")
                failed += 1

    print("\n=== Spork Test Summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Files:  {len(files)}")
    if failed:
        return 1
    print("All Spork tests passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
