"""
Generate benchmark report for documentation.

This script runs the benchmark suite at multiple N values and combines
the results with host information into a markdown format suitable for
the BENCHMARKS.md file.

Usage:
    python3 generate_benchmark_report.py 25000 50000 100000
    python3 generate_benchmark_report.py --sizes 25000 50000 100000
    python3 generate_benchmark_report.py  # uses default sizes
"""

import argparse
import subprocess
import sys
from pathlib import Path


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()


def run_host_info() -> str:
    """Run host_info.py and return the output."""
    script = get_script_dir() / "host_info.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error running host_info.py: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def run_benchmark(size: int, iterations: int = 50) -> str:
    """Run benchmark_pds.py with the given size and return the output."""
    script = get_script_dir() / "benchmark_pds.py"
    result = subprocess.run(
        [sys.executable, str(script), "--size", str(size), "--iter", str(iterations)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error running benchmark (N={size}): {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def format_size(size: int) -> str:
    """Format size with comma separators."""
    return f"{size:,}"


def generate_report(sizes: list[int], iterations: int = 50) -> str:
    """Generate the full benchmark report."""
    lines = []

    host_info = run_host_info()

    cpu_name = "Unknown CPU"
    for line in host_info.split("\n"):
        if line.startswith("- **CPU**:"):
            cpu_name = line.split(":", 1)[1].strip()
            break

    lines.append(f"### {cpu_name}")
    lines.append("")

    for line in host_info.split("\n"):
        if not line.startswith("## "):
            lines.append(line)

    for size in sizes:
        lines.append("")
        lines.append(f"#### N={format_size(size)}")
        lines.append("")
        lines.append("<details>")
        lines.append(
            f"<summary>Click to expand benchmark results (N={format_size(size)})</summary>"
        )
        lines.append("")
        lines.append("```sh")
        lines.append(f"$ .venv/bin/python tools/benchmark_pds.py --size {size}")

        print(f"Running benchmark with N={format_size(size)}...", file=sys.stderr)
        benchmark_output = run_benchmark(size, iterations)
        lines.append(benchmark_output.rstrip())

        lines.append("```")
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate benchmark report for documentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s 25000 50000 100000
    %(prog)s --sizes 25000 50000 100000
    %(prog)s --iter 100 25000 50000
        """,
    )
    parser.add_argument(
        "sizes",
        nargs="*",
        type=int,
        default=[25000, 50000, 100000],
        help="N values to benchmark (default: 25000 50000 100000)",
    )
    parser.add_argument(
        "--sizes",
        dest="sizes_flag",
        nargs="+",
        type=int,
        help="Alternative way to specify N values",
    )
    parser.add_argument(
        "--iter",
        type=int,
        default=50,
        help="Number of iterations per benchmark (default: 50)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output file (default: stdout)",
    )

    args = parser.parse_args()

    sizes = args.sizes_flag if args.sizes_flag else args.sizes

    if not sizes:
        sizes = [25000, 50000, 100000]

    sizes = sorted(sizes)

    print(
        f"Generating benchmark report for N={', '.join(map(str, sizes))}...",
        file=sys.stderr,
    )

    report = generate_report(sizes, args.iter)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
            f.write("\n")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
