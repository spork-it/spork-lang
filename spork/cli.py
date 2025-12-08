"""
spork.cli - Spork Command Line Interface

This module provides the main CLI entry point for Spork with subcommand support:

- spork repl          Start the interactive REPL
- spork new <name>    Create a new Spork project
- spork sync          Sync project dependencies
- spork run           Run the project's main entry point
- spork build         Build project to .spork-out/ with Python + source maps
- spork <file>        Execute a Spork file directly

Legacy flags are still supported for backwards compatibility:
- spork -c <code>     Execute code directly
- spork -e <file>     Export Spork file to Python
- spork --nrepl       Start nREPL server
"""

import argparse
import os
import sys
import traceback
from typing import Optional


def cmd_repl(args: argparse.Namespace) -> int:
    """Start the interactive REPL."""
    from spork.repl import create_repl
    from spork.runtime.ns import init_source_roots

    # Check if we're in a project and initialize project context
    try:
        from spork.project import ProjectConfig, ProjectManager

        config = ProjectConfig.load()
        manager = ProjectManager(config)

        print(f"Starting REPL for project: {config.name}")

        # Ensure venv exists and has dependencies
        if not manager.has_venv():
            print("Project venv not found, initializing...")
            success = manager.install_dependencies(quiet=False)
            if not success:
                print(
                    "Error: Failed to initialize project environment", file=sys.stderr
                )
                return 1
            print()

        # Inject venv site-packages into sys.path
        manager.inject_venv_paths()

        # Add source paths to namespace resolution
        for source_path in config.get_absolute_source_paths():
            if os.path.isdir(source_path):
                init_source_roots(extra_paths=[source_path])
    except FileNotFoundError:
        # Not in a project, that's fine
        pass

    init_source_roots(include_cwd=True)

    repl_instance = create_repl(mode="terminal")
    repl_instance.run()
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    """Create a new Spork project."""
    from spork.project.scaffold import create_project

    name = args.name
    path = args.path or os.getcwd()

    try:
        project_path = create_project(name, path)
        print(f"✓ Created new Spork project: {project_path}")
        print()
        print("Next steps:")
        print(f"  cd {os.path.basename(project_path)}")
        print("  spork run       # Run the project entrypoint")
        print("  spork repl      # Start the REPL in the project context")
        return 0
    except Exception as e:
        print(f"Error creating project: {e}", file=sys.stderr)
        return 1


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync project dependencies."""
    from spork.project import ProjectConfig, ProjectManager

    try:
        config = ProjectConfig.load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Are you in a Spork project directory?", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error in spork.it: {e}", file=sys.stderr)
        return 1

    print(f"Syncing project: {config.name} v{config.version}")
    print(f"Project root: {config.project_root}")
    print()

    manager = ProjectManager(config)

    try:
        success = manager.install_dependencies(quiet=args.quiet)
        return 0 if success else 1
    except Exception as e:
        print(f"Error syncing dependencies: {e}", file=sys.stderr)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run the project's main entry point."""
    from spork.compiler import exec_file
    from spork.project import ProjectConfig, ProjectManager
    from spork.runtime.ns import (
        NamespaceProxy,
        add_source_root,
        find_spork_file_for_ns,
        get_namespace,
        init_source_roots,
        register_namespace,
    )
    from spork.runtime.types import normalize_name

    try:
        config = ProjectConfig.load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error in spork.it: {e}", file=sys.stderr)
        return 1

    # Determine what to run
    main_entry = args.main or config.main

    if not main_entry:
        print(
            "Error: No main entry point specified. Use --main or set :main in spork.it",
            file=sys.stderr,
        )
        return 1

    # Parse main entry (format: namespace/function)
    if "/" in main_entry:
        ns_name, fn_name = main_entry.rsplit("/", 1)
    else:
        # Assume it's just a namespace, call main function
        ns_name = main_entry
        fn_name = "main"

    # Normalize function name (hyphens to underscores for Python)
    fn_name_py = normalize_name(fn_name)

    # Setup environment - ensure venv exists and has dependencies
    manager = ProjectManager(config)
    if not manager.has_venv():
        print("Project venv not found, initializing...")
        try:
            success = manager.install_dependencies(quiet=False)
            if not success:
                print(
                    "Error: Failed to initialize project environment", file=sys.stderr
                )
                return 1
            print()  # Blank line after setup output
        except Exception as e:
            print(f"Error initializing project environment: {e}", file=sys.stderr)
            return 1

    # Inject venv paths for imports
    manager.inject_venv_paths()

    init_source_roots(include_cwd=True)

    # Add project source paths
    for source_path in config.get_absolute_source_paths():
        if os.path.isdir(source_path):
            add_source_root(source_path, prepend=True)

    # Load the namespace and run the function
    try:
        # Find and load the namespace file
        spork_file = find_spork_file_for_ns(ns_name)
        if spork_file is None:
            print(f"Error: Namespace '{ns_name}' not found", file=sys.stderr)
            print(f"Searched in: {config.get_absolute_source_paths()}", file=sys.stderr)
            return 1

        # Execute the file to load the namespace
        env = exec_file(spork_file)

        # Get the namespace info
        ns_info = get_namespace(ns_name)
        if ns_info is None:
            # Register it ourselves if the file didn't declare the namespace
            register_namespace(
                name=ns_name,
                file=os.path.abspath(spork_file),
                env=env,
                macros=env.get("__spork_macros__", {}),
            )
            ns_info = get_namespace(ns_name)

        if ns_info is None:
            print(f"Error: Failed to load namespace '{ns_name}'", file=sys.stderr)
            return 1

        ns_proxy = NamespaceProxy(ns_info.env, ns_name)

        # Get the function
        try:
            fn = getattr(ns_proxy, fn_name_py)
        except AttributeError:
            try:
                fn = getattr(ns_proxy, fn_name)
            except AttributeError:
                print(
                    f"Error: Function '{fn_name}' not found in namespace '{ns_name}'",
                    file=sys.stderr,
                )
                return 1

        # Call the function with any additional arguments
        result = fn(*args.args)

        # If result is an integer, use as exit code
        if isinstance(result, int):
            return result
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    """Build the project to .spork-out/ with Python source and source maps."""
    from pathlib import Path

    from spork.project.build import build_project

    out_dir = Path(args.out_dir) if args.out_dir else None
    clean = getattr(args, "clean", False)

    try:
        result = build_project(
            out_dir=out_dir,
            clean=clean,
            verbose=True,
        )

        if result.success:
            print()
            print(f"Output written to: {result.out_dir}")
            return 0
        else:
            return 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_dist(args: argparse.Namespace) -> int:
    """Create distribution packages (wheel and sdist) from compiled Spork project."""
    from pathlib import Path

    from spork.project.dist import create_dist

    dist_dir = Path(args.dist_dir) if args.dist_dir else None
    out_dir = Path(args.out_dir) if args.out_dir else None
    clean = getattr(args, "clean", False)
    no_build = getattr(args, "no_build", False)
    wheel_only = getattr(args, "wheel_only", False)
    sdist_only = getattr(args, "sdist_only", False)

    # Determine what to build
    build_wheel = not sdist_only
    build_sdist = not wheel_only

    try:
        result = create_dist(
            out_dir=out_dir,
            dist_dir=dist_dir,
            build_first=not no_build,
            clean=clean,
            wheel=build_wheel,
            sdist=build_sdist,
            verbose=True,
        )

        if result.success:
            print()
            print("Distribution packages created:")
            if result.wheel_path:
                print(f"  wheel: {result.wheel_path}")
            if result.sdist_path:
                print(f"  sdist: {result.sdist_path}")
            print()
            return 0
        else:
            if result.error:
                print(f"Error: {result.error}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_clean(args: argparse.Namespace) -> int:
    """Clean project artifacts."""
    from spork.project import ProjectConfig, ProjectManager

    try:
        config = ProjectConfig.load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    manager = ProjectManager(config)
    success = manager.clean(venv_only=not args.all)
    return 0 if success else 1


def cmd_exec_file(filepath: str, interactive: bool = False) -> int:
    """Execute a Spork file."""
    from spork.compiler import exec_file
    from spork.repl import create_repl

    try:
        exec_file(filepath)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    if interactive:
        repl_instance = create_repl(mode="terminal")
        repl_instance.run()

    return 0


def cmd_exec_code(code: str, interactive: bool = False) -> int:
    """Execute Spork code directly."""
    from spork.compiler import compile_forms_to_code
    from spork.repl import create_repl
    from spork.runtime import setup_runtime_env
    from spork.runtime.ns import init_source_roots

    init_source_roots(include_cwd=True)

    env = {
        "__name__": "__main__",
        "__file__": "<command>",
    }
    setup_runtime_env(env)

    try:
        compiled, _ = compile_forms_to_code(code, "<command>")
        exec(compiled, env, env)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    if interactive:
        repl_instance = create_repl(mode="terminal")
        repl_instance.run()

    return 0


def cmd_export_file(filepath: str) -> int:
    """Export a Spork file to Python code."""
    from spork.compiler import export_file

    try:
        export_file(filepath)
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_lsp(args: argparse.Namespace) -> int:
    """Start the Language Server Protocol server."""
    from spork.lsp.server import start_server

    log_path = getattr(args, "log", None)

    try:
        start_server(log_path=log_path)
        return 0
    except Exception as e:
        print(f"Error starting LSP server: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_nrepl_server(host: str, port: int) -> int:
    """Start the nREPL server."""
    from spork.repl.nrepl import NReplServer
    from spork.runtime.ns import init_source_roots

    # Check if we're in a project and initialize project context
    try:
        from spork.project import ProjectConfig, ProjectManager

        config = ProjectConfig.load()
        manager = ProjectManager(config)

        print(f"Starting nREPL server for project: {config.name}")

        # Ensure venv exists and has dependencies
        if not manager.has_venv():
            print("Project venv not found, initializing...")
            success = manager.install_dependencies(quiet=False)
            if not success:
                print(
                    "Error: Failed to initialize project environment", file=sys.stderr
                )
                return 1
            print()

        # Inject venv site-packages into sys.path
        manager.inject_venv_paths()

        # Add source paths to namespace resolution
        for source_path in config.get_absolute_source_paths():
            if os.path.isdir(source_path):
                init_source_roots(extra_paths=[source_path])

    except FileNotFoundError:
        # Not in a project, that's fine - run in standalone mode
        print("Starting nREPL server (no project context)")

    init_source_roots(include_cwd=True)

    server = NReplServer(host, port)
    server.start()
    return 0


def cmd_nrepl_client(host: str, port: int) -> int:
    """Connect to an nREPL server as a test client."""
    from spork.repl.nrepl import SimpleNReplClient

    client = SimpleNReplClient(host, port)
    try:
        client.connect()
        print("\nSimple nREPL Client")
        print("Type code to evaluate, or :quit to exit\n")

        while True:
            try:
                code = input("client> ")
                if code.strip() == ":quit":
                    break
                if not code.strip():
                    continue

                response = client.eval(code)

                if "value" in response:
                    print(f"=> {response['value']}")
                elif "error" in response:
                    print(f"Error: {response['error']}")

            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                continue
            except Exception as e:
                print(f"Error: {e}")
    finally:
        client.close()
    return 0


# Known subcommands - used to differentiate from file arguments
SUBCOMMANDS = {"repl", "new", "sync", "run", "build", "dist", "clean", "lsp"}


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="spork",
        description="Spork - A Lisp to Python transpiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  spork                         Start interactive REPL
  spork repl                    Start interactive REPL (explicit)
  spork new my-project          Create a new project
  spork sync                    Install project dependencies
  spork run                     Run project's main function
  spork script.spork            Execute a Spork file
  spork -c "(+ 1 2 3)"          Evaluate Spork code directly
  spork -e script.spork         Export Spork file to Python code
  spork --nrepl                 Start nREPL server on default port
        """,
    )

    # Legacy/shortcut flags (these work without subcommands)
    parser.add_argument(
        "-c",
        "--command",
        metavar="CODE",
        help="Execute Spork code directly (like python -c)",
    )

    parser.add_argument(
        "-e",
        "--export",
        metavar="FILE",
        help="Export Spork file to Python code and print to stdout",
    )

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Start REPL after executing file or command",
    )

    parser.add_argument(
        "--nrepl",
        action="store_true",
        help="Start nREPL server for editor integration",
    )

    parser.add_argument(
        "--nrepl-client",
        action="store_true",
        help="Connect to nREPL server as a test client",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for nREPL server (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=7888,
        help="Port for nREPL server (default: 7888)",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # repl subcommand
    subparsers.add_parser("repl", help="Start the interactive REPL")

    # new subcommand
    new_parser = subparsers.add_parser("new", help="Create a new Spork project")
    new_parser.add_argument("name", help="Name of the new project")
    new_parser.add_argument(
        "--path",
        "-p",
        help="Parent directory for the project (default: current directory)",
    )

    # sync subcommand
    sync_parser = subparsers.add_parser(
        "sync", help="Sync project dependencies (create venv, install deps)"
    )
    sync_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress pip output"
    )

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run the project's main function")
    run_parser.add_argument(
        "--main",
        "-m",
        help="Main entry point (namespace/function), overrides spork.it",
    )
    run_parser.add_argument(
        "args",
        nargs="*",
        help="Arguments to pass to the main function",
    )

    # build subcommand
    build_parser = subparsers.add_parser(
        "build", help="Build project to .spork-out/ with Python + source maps"
    )
    build_parser.add_argument(
        "--out-dir",
        "-o",
        default=".spork-out",
        help="Output directory (default: .spork-out)",
    )
    build_parser.add_argument(
        "--clean",
        "-c",
        action="store_true",
        help="Remove existing output directory before building",
    )

    # dist subcommand
    dist_parser = subparsers.add_parser(
        "dist", help="Create wheel and sdist from compiled Spork project"
    )
    dist_parser.add_argument(
        "--dist-dir",
        "-d",
        default="dist",
        help="Output directory for distributions (default: dist)",
    )
    dist_parser.add_argument(
        "--out-dir",
        "-o",
        default=".spork-out",
        help="Compiled output directory (default: .spork-out)",
    )
    dist_parser.add_argument(
        "--clean",
        "-c",
        action="store_true",
        help="Remove existing dist directory before building",
    )
    dist_parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip running `spork build` first (use existing .spork-out)",
    )
    dist_parser.add_argument(
        "--wheel-only",
        action="store_true",
        help="Only build wheel, skip sdist",
    )
    dist_parser.add_argument(
        "--sdist-only",
        action="store_true",
        help="Only build sdist, skip wheel",
    )

    # clean subcommand
    clean_parser = subparsers.add_parser("clean", help="Clean project artifacts")
    clean_parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Remove all artifacts, not just .venv",
    )

    # lsp subcommand
    lsp_parser = subparsers.add_parser(
        "lsp", help="Start the Language Server Protocol server"
    )
    lsp_parser.add_argument(
        "--log",
        metavar="FILE",
        help="Log file for debugging LSP communication",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the Spork CLI. Calls sys.exit with return code."""
    sys.exit(_main(argv))


def _main(argv: Optional[list[str]] = None) -> int:
    """Internal main that returns exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Pre-parse to detect if first arg is a file (not a subcommand or flag)
    # This allows `spork myfile.spork` to work without a subcommand
    file_to_run = None
    if argv and not argv[0].startswith("-") and argv[0] not in SUBCOMMANDS:
        # First arg looks like a file, not a subcommand
        file_to_run = argv[0]
        argv = argv[1:]  # Remove it from argv for argparse

    parser = create_parser()
    args = parser.parse_args(argv)

    # Handle subcommands first
    if args.subcommand == "repl":
        return cmd_repl(args)
    elif args.subcommand == "new":
        return cmd_new(args)
    elif args.subcommand == "sync":
        return cmd_sync(args)
    elif args.subcommand == "run":
        return cmd_run(args)
    elif args.subcommand == "build":
        return cmd_build(args)
    elif args.subcommand == "dist":
        return cmd_dist(args)
    elif args.subcommand == "clean":
        return cmd_clean(args)
    elif args.subcommand == "lsp":
        return cmd_lsp(args)

    # Handle legacy flags
    if args.nrepl:
        return cmd_nrepl_server(args.host, args.port)

    if args.nrepl_client:
        return cmd_nrepl_client(args.host, args.port)

    if args.command:
        return cmd_exec_code(args.command, args.interactive)

    if args.export:
        return cmd_export_file(args.export)

    # Handle file execution (detected in pre-parse)
    if file_to_run:
        return cmd_exec_file(file_to_run, args.interactive)

    # No arguments - start REPL
    return cmd_repl(args)


if __name__ == "__main__":
    main()
