"""
spork.cli - Spork Command Line Interface

This module provides the main CLI entry point for Spork with subcommand support:

- spork repl          Start the interactive REPL
- spork new <name>    Create a new Spork project
- spork add <package> Add project dependencies
- spork remove <pkg>  Remove project dependencies
- spork sync          Sync project dependencies
- spork run           Run the project's main entry point
- spork test          Run project Spork tests
- spork check         Check all project sources without executing them
- spork build         Build project to .spork-out/ with Python + source maps
- spork <provider>    Run a project-local or active extension command
- spork <file>        Execute an explicit Spork file path

Legacy flags are still supported for backwards compatibility:
- spork -c <code>     Execute code directly
- spork -e <file>     Export Spork file to Python
- spork --nrepl       Start nREPL server
"""

import argparse
import os
import platform
import subprocess
import sys
import traceback
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Mapping, Optional

from spork.command_discovery import (
    CommandCatalog,
    CommandProviderLoadError,
    DiscoveredCommand,
    discover_extension_commands,
)
from spork.commands import (
    CommandContext,
    CommandProvider,
    CommandResultError,
    CommandSpec,
    ProjectRequiredError,
    create_command_context,
    invoke_command,
)

if TYPE_CHECKING:
    from spork.project.config import ProjectConfig


def cmd_version(args: argparse.Namespace) -> int:
    """Print Spork version and Python host information."""
    import spork

    print(f"Spork {spork.__version__}")
    print()
    print("Python Host:")
    print(f"  Version:        {platform.python_version()}")
    print(f"  Implementation: {platform.python_implementation()}")
    print(f"  Compiler:       {platform.python_compiler()}")
    print(f"  Executable:     {sys.executable}")
    print()
    print("System:")
    print(f"  OS:             {platform.system()} {platform.release()}")
    print(f"  Architecture:   {platform.machine()}")
    print(f"  Platform:       {platform.platform()}")
    return 0


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
        print(f"[ok] Created new Spork project: {project_path}")
        print()
        print("Next steps:")
        print(f"  cd {os.path.basename(project_path)}")
        print("  spork run       # Run the project entrypoint")
        print("  spork repl      # Start the REPL in the project context")
        return 0
    except Exception as e:
        print(f"Error creating project: {e}", file=sys.stderr)
        return 1


def _edit_dependencies(args: argparse.Namespace, *, remove: bool) -> int:
    """Add or remove dependencies in the nearest project manifest."""
    from pathlib import Path

    from spork.project import ProjectConfig, add_dependencies, remove_dependencies

    try:
        config = ProjectConfig.load()
        manifest_path = Path(config.project_root, "spork.it").resolve()
        if remove:
            changes = remove_dependencies(manifest_path, args.packages)
        else:
            changes = add_dependencies(manifest_path, args.packages)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Are you in a Spork project directory?", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error in spork.it: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error updating spork.it: {e}", file=sys.stderr)
        return 1

    for change in changes:
        if change.action == "added":
            print(f"Adding {change.dependency} to {manifest_path}")
        elif change.action == "updated":
            print(
                f"Updating {change.previous} to {change.dependency} "
                f"in {manifest_path}"
            )
        elif change.action == "removed":
            print(f"Removing {change.dependency} from {manifest_path}")
        elif change.action == "unchanged":
            print(f"{change.dependency} is already in {manifest_path}")
        else:
            print(f"{change.dependency} is not in {manifest_path}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Add dependencies to the nearest project manifest."""
    return _edit_dependencies(args, remove=False)


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove dependencies from the nearest project manifest."""
    return _edit_dependencies(args, remove=True)


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
        success = manager.install_dependencies(
            dev=getattr(args, "dev", False), quiet=args.quiet
        )
        return 0 if success else 1
    except Exception as e:
        print(f"Error syncing dependencies: {e}", file=sys.stderr)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run the project's main entry point through the reusable runtime."""
    from spork.project import ProjectConfig, ProjectRuntime, ProjectRuntimeError

    try:
        config = ProjectConfig.load()
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Error in spork.it: {error}", file=sys.stderr)
        return 1

    main_entry = args.main or config.main
    if not main_entry:
        print(
            "Error: No main entry point specified. Use --main or set :main in spork.it",
            file=sys.stderr,
        )
        return 1

    runtime = ProjectRuntime(config)
    environment_missing = runtime.environment_missing
    if environment_missing:
        print("Project venv not found, initializing...")

    try:
        runtime.prepare()
        if environment_missing:
            print()
        return runtime.invoke_entry(main_entry, args.args)
    except ProjectRuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """Discover and run project Spork tests with the native test runner."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    from spork.project import ProjectConfig, ProjectManager, build_project
    from spork.testing.discovery import TestDiscoveryError, discover_test_files

    try:
        config = ProjectConfig.load()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    manager = ProjectManager(config)
    if not manager.has_venv():
        print("Project venv not found, syncing development dependencies...")
        if not manager.install_dependencies(dev=True):
            return 1
    manager.inject_venv_paths()

    source_roots = [Path(path) for path in config.get_absolute_source_paths()]
    test_roots = [Path(path) for path in config.get_absolute_test_paths()]
    try:
        test_files = discover_test_files(source_roots, test_roots)
    except TestDiscoveryError as exc:
        print(f"Test discovery failed: {exc}", file=sys.stderr)
        return 1

    if not test_files:
        print("No matching Spork tests found.", file=sys.stderr)
        return 1

    build_result = None
    needs_spork_api = config.api is not None and config.api.spork is not None
    if needs_spork_api:
        build_result = build_project(
            project_root=Path(config.project_root), clean=True, verbose=False
        )
        if not build_result.success:
            print("Project build failed before tests.", file=sys.stderr)
            return 1

    env = os.environ.copy()
    spork_paths = [
        *config.get_absolute_source_paths(),
        *config.get_absolute_test_paths(),
    ]
    if build_result is not None:
        spork_paths.append(str(build_result.out_dir))
    existing_spork_path = env.get("SPORK_PATH")
    if existing_spork_path:
        spork_paths.append(existing_spork_path)
    env["SPORK_PATH"] = os.pathsep.join(spork_paths)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    passed = 0
    failed = 0
    with tempfile.TemporaryDirectory(prefix="spork-tests-") as result_dir:
        for index, discovered in enumerate(test_files):
            try:
                relative = discovered.path.relative_to(config.project_root)
            except ValueError:
                relative = discovered.path
            print(f"\n=== {relative} ===", flush=True)

            result_path = Path(result_dir) / f"{index}.json"
            command = [
                config.venv_python,
                "-m",
                "spork.testing.runner",
                str(discovered.path),
                "--result",
                str(result_path),
            ]
            completed = subprocess.run(
                command,
                cwd=config.project_root,
                env=env,
                check=False,
            )

            result = None
            if result_path.is_file():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    passed += int(result["passed"])
                    failed += int(result["failed"])
                except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    failed += 1
            else:
                failed += 1

            if completed.returncode and result is not None:
                # A normal test failure is already represented by the result.
                # Reserve this branch for a runner/result disagreement.
                try:
                    represented_failure = int(result.get("failed", 0)) > 0
                except (AttributeError, TypeError, ValueError):
                    represented_failure = False
                if not represented_failure:
                    failed += 1

    print("\n=== Spork Test Summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Files:  {len(test_files)}")
    if failed:
        return 1
    print("All Spork tests passed")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Check project namespaces, imports, exports, and compilation."""
    import json
    from pathlib import Path

    from spork.project import (
        ProjectConfig,
        check_project,
        find_project_root,
        format_human_result,
    )

    output_format = getattr(args, "format", "human")
    try:
        config = ProjectConfig.load()
        result = check_project(
            config,
            include_tests=not getattr(args, "no_tests", False),
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        if output_format == "json":
            detected_root = find_project_root() or str(Path.cwd())
            print(
                json.dumps(
                    {
                        "version": 1,
                        "project": None,
                        "projectRoot": str(Path(detected_root).resolve()),
                        "filesChecked": 0,
                        "namespacesChecked": 0,
                        "errors": 1,
                        "warnings": 0,
                        "success": False,
                        "diagnostics": [
                            {
                                "path": "spork.it",
                                "line": 1,
                                "column": 1,
                                "endLine": 1,
                                "endColumn": 2,
                                "severity": "error",
                                "code": "SPK001",
                                "message": str(exc),
                            }
                        ],
                    },
                    indent=2,
                )
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if output_format == "json":
        print(result.to_json())
    else:
        print(format_human_result(result))

    warnings_fail = getattr(args, "warnings_as_errors", False) and result.warning_count
    return 0 if result.success and not warnings_fail else 1


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


# These commands must remain available when the project environment is absent,
# stale, or being removed. Other commands require a compatible toolchain.
_TOOLCHAIN_OPTIONAL_COMMANDS = {"add", "remove", "sync", "version"}
_NEVER_DELEGATE_COMMANDS = {"new", "clean", "plugin"}


def _is_explicit_file_token(token: str) -> bool:
    """Return whether a top-level token explicitly selects a file path."""
    separators = {os.sep}
    if os.altsep:
        separators.add(os.altsep)
    return (
        token.endswith(".spork")
        or Path(token).is_absolute()
        or token in {".", ".."}
        or any(separator in token for separator in separators)
    )


def _project_command(argv: list[str]) -> Optional[str]:
    """Return a core or extension candidate relevant to project delegation."""
    if not argv:
        return None
    candidate = argv[0]
    if candidate in CORE_COMMANDS or candidate == "plugin":
        return candidate
    if not candidate.startswith("-") and not _is_explicit_file_token(candidate):
        return candidate
    return None


def _delegate_to_project_toolchain(argv: list[str]) -> Optional[int]:
    """Run the CLI with the synchronized project toolchain when available.

    ``spork sync`` remains a bootstrap operation when the environment is
    missing or incompatible. Once a compatible ``spork-lang`` is installed in
    ``.venv``, project-aware invocations are delegated to that interpreter.
    """
    command = _project_command(argv)
    if command in _NEVER_DELEGATE_COMMANDS:
        return None

    from spork.project import ProjectConfig, ProjectManager

    try:
        config = ProjectConfig.load()
    except FileNotFoundError:
        return None
    except ValueError as error:
        if command in _TOOLCHAIN_OPTIONAL_COMMANDS:
            return None
        print(f"Error in spork.it: {error}", file=sys.stderr)
        return 1

    manager = ProjectManager(config)
    active_version = manager.active_spork_version()

    if manager.is_running_in_project_venv():
        if manager.spork_version_satisfies_project(active_version):
            return None
        if command in _TOOLCHAIN_OPTIONAL_COMMANDS:
            return None
        print(
            f"Error: project requires spork-lang{config.spork_version}, but its "
            f"environment is running spork-lang=={active_version}.",
            file=sys.stderr,
        )
        print("Run `spork sync` to update the project toolchain.", file=sys.stderr)
        return 1

    installed_version = manager.get_project_spork_version()
    if installed_version is not None and manager.spork_version_satisfies_project(
        installed_version
    ):
        try:
            result = subprocess.run(
                [config.venv_python, "-m", "spork", *argv],
                cwd=os.getcwd(),
                check=False,
            )
        except OSError as error:
            print(
                f"Error: could not run the project Spork toolchain: {error}",
                file=sys.stderr,
            )
            return 1
        return result.returncode

    help_requested = any(argument in {"-h", "--help"} for argument in argv)
    if command in _TOOLCHAIN_OPTIONAL_COMMANDS or (
        help_requested and (command is None or command in CORE_COMMANDS)
    ):
        return None

    if not manager.has_venv() and manager.active_spork_satisfies_project():
        return None

    requirement = config.spork_version
    if installed_version is not None:
        print(
            f"Error: project environment has spork-lang=={installed_version}, "
            f"but spork.it requires spork-lang{requirement}.",
            file=sys.stderr,
        )
    elif manager.has_venv():
        print(
            "Error: project environment does not contain a usable spork-lang "
            "toolchain.",
            file=sys.stderr,
        )
    else:
        print(
            f"Error: project requires spork-lang{requirement}, but the active "
            f"CLI is spork-lang=={active_version}.",
            file=sys.stderr,
        )
    print("Run `spork sync` to synchronize the project toolchain.", file=sys.stderr)
    return 1


ParsedCommandHandler = Callable[[argparse.Namespace], int]
ParserConfigurer = Callable[[argparse.ArgumentParser], None]


def _no_arguments(parser: argparse.ArgumentParser) -> None:
    """Configure a command that accepts only the standard help flag."""


def _configure_new(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="Name of the new project")
    parser.add_argument(
        "--path",
        "-p",
        help="Parent directory for the project (default: current directory)",
    )


def _configure_add(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "packages", nargs="+", metavar="PACKAGE", help="Package requirement(s) to add"
    )


def _configure_remove(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "packages", nargs="+", metavar="PACKAGE", help="Package name(s) to remove"
    )


def _configure_sync(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress pip output"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install :dev-dependencies from spork.it",
    )


def _configure_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--main",
        "-m",
        help="Main entry point (namespace:function), overrides spork.it",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Arguments to pass to the main function",
    )


def _configure_check(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="Diagnostic output format (default: human)",
    )
    parser.add_argument(
        "--json",
        dest="format",
        action="store_const",
        const="json",
        help="Shortcut for --format json",
    )
    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Check only :source-paths, excluding :test-paths",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Return a failure status when warnings are reported",
    )


def _configure_build(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--out-dir",
        "-o",
        default=".spork-out",
        help="Output directory (default: .spork-out)",
    )
    parser.add_argument(
        "--clean",
        "-c",
        action="store_true",
        help="Remove existing output directory before building",
    )


def _configure_dist(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dist-dir",
        "-d",
        default="dist",
        help="Output directory for distributions (default: dist)",
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        default=".spork-out",
        help="Compiled output directory (default: .spork-out)",
    )
    parser.add_argument(
        "--clean",
        "-c",
        action="store_true",
        help="Remove existing dist directory before building",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip running `spork build` first (use existing .spork-out)",
    )
    parser.add_argument(
        "--wheel-only",
        action="store_true",
        help="Only build wheel, skip sdist",
    )
    parser.add_argument(
        "--sdist-only",
        action="store_true",
        help="Only build sdist, skip wheel",
    )


def _configure_clean(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Remove all artifacts, not just .venv",
    )


def _configure_lsp(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log",
        metavar="FILE",
        help="Log file for debugging LSP communication",
    )


@dataclass(frozen=True)
class _CoreCommandDefinition:
    name: str
    summary: str
    action: ParsedCommandHandler
    configure_parser: ParserConfigurer = _no_arguments


_CORE_COMMAND_DEFINITIONS = (
    _CoreCommandDefinition("repl", "Start the interactive REPL", cmd_repl),
    _CoreCommandDefinition(
        "new", "Create a new Spork project", cmd_new, _configure_new
    ),
    _CoreCommandDefinition(
        "add",
        "Add packages to :dependencies in spork.it",
        cmd_add,
        _configure_add,
    ),
    _CoreCommandDefinition(
        "remove",
        "Remove packages from :dependencies in spork.it",
        cmd_remove,
        _configure_remove,
    ),
    _CoreCommandDefinition(
        "sync",
        "Sync project dependencies (create venv, install deps)",
        cmd_sync,
        _configure_sync,
    ),
    _CoreCommandDefinition(
        "run", "Run the project's main function", cmd_run, _configure_run
    ),
    _CoreCommandDefinition("test", "Discover and run project Spork tests", cmd_test),
    _CoreCommandDefinition(
        "check",
        "Check project sources without producing build artifacts",
        cmd_check,
        _configure_check,
    ),
    _CoreCommandDefinition(
        "build",
        "Build project to .spork-out/ with Python + source maps",
        cmd_build,
        _configure_build,
    ),
    _CoreCommandDefinition(
        "dist",
        "Create wheel and sdist from compiled Spork project",
        cmd_dist,
        _configure_dist,
    ),
    _CoreCommandDefinition(
        "clean", "Clean project artifacts", cmd_clean, _configure_clean
    ),
    _CoreCommandDefinition(
        "lsp", "Start the Language Server Protocol server", cmd_lsp, _configure_lsp
    ),
    _CoreCommandDefinition(
        "version", "Print Spork version and Python host information", cmd_version
    ),
)
_CORE_COMMAND_DEFINITIONS_BY_NAME = {
    definition.name: definition for definition in _CORE_COMMAND_DEFINITIONS
}


def create_command_parser(command: str) -> argparse.ArgumentParser:
    """Create the isolated argument parser for one static core command."""
    try:
        definition = _CORE_COMMAND_DEFINITIONS_BY_NAME[command]
    except KeyError as error:
        raise ValueError(f"unknown core command: {command}") from error

    parser = argparse.ArgumentParser(
        prog=f"spork {definition.name}",
        description=definition.summary,
    )
    definition.configure_parser(parser)
    return parser


def _create_core_command_spec(
    definition: _CoreCommandDefinition,
    provider: CommandProvider,
) -> CommandSpec:
    def handler(context: CommandContext, argv: list[str]) -> int:
        # Context is intentionally accepted even though the existing core
        # actions do not need it yet. Extensions use this exact boundary.
        del context
        args = create_command_parser(definition.name).parse_args(argv)
        return definition.action(args)

    return CommandSpec(
        name=definition.name,
        summary=definition.summary,
        handler=handler,
        provider=provider,
    )


def _create_core_command_registry() -> Mapping[str, CommandSpec]:
    import spork

    provider = CommandProvider(
        name="spork-lang",
        version=spork.__version__,
        scope="core",
        location=Path(__file__).resolve(),
    )
    return MappingProxyType(
        {
            definition.name: _create_core_command_spec(definition, provider)
            for definition in _CORE_COMMAND_DEFINITIONS
        }
    )


CORE_COMMANDS = _create_core_command_registry()
# Backwards-compatible command-name view for code that only needs membership.
SUBCOMMANDS = frozenset(CORE_COMMANDS)


def _core_command_help() -> str:
    width = max(len(name) for name in CORE_COMMANDS)
    return "\n".join(
        f"  {name:<{width}}  {spec.summary}" for name, spec in CORE_COMMANDS.items()
    )


def _extension_command_help(commands: Mapping[str, DiscoveredCommand]) -> str:
    if not commands:
        return ""
    width = max(len(name) for name in commands)
    entries = "\n".join(
        f"  {name:<{width}}  {command.summary}"
        for name, command in sorted(commands.items())
    )
    return f"\nextension commands:\n{entries}\n"


@dataclass(frozen=True)
class _ExtensionCommandState:
    catalog: CommandCatalog
    project: Optional["ProjectConfig"] = None
    project_error: Optional[str] = None


def _discover_extension_state() -> _ExtensionCommandState:
    """Load optional project metadata and discover providers without imports."""
    from spork.project.config import ProjectConfig

    project = None
    project_error = None
    try:
        project = ProjectConfig.load()
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as error:
        project_error = str(error)
    return _ExtensionCommandState(
        catalog=discover_extension_commands(project),
        project=project,
        project_error=project_error,
    )


def _print_discovery_diagnostic(message: str, *, warning: bool = False) -> None:
    prefix = "Warning" if warning else "Error"
    print(f"{prefix}: {message}", file=sys.stderr)


def _invoke_extension_command(
    command: DiscoveredCommand,
    argv: list[str],
    project: Optional["ProjectConfig"],
) -> int:
    """Invoke one lazily loaded extension through the shared command contract."""
    from spork.project.runtime import ProjectRuntimeError

    spec = command.create_spec()
    context = create_command_context(spec, project=project)
    provider = command.provider
    version = f"=={provider.version}" if provider.version else ""
    provenance = (
        f"command {command.name!r} from {provider.name}{version} "
        f"({provider.scope})"
    )
    try:
        return invoke_command(spec, argv, context=context)
    except (
        CommandProviderLoadError,
        CommandResultError,
        ProjectRequiredError,
        ProjectRuntimeError,
    ) as error:
        _print_discovery_diagnostic(f"{provenance}: {error}")
        return 1
    except Exception as error:
        _print_discovery_diagnostic(
            f"{provenance} raised {type(error).__name__}: {error}"
        )
        raise


def _unknown_command(command: str, catalog: CommandCatalog) -> int:
    _print_discovery_diagnostic(f"unknown command {command!r}")
    choices = [*CORE_COMMANDS, *catalog.commands]
    matches = get_close_matches(command, choices, n=3, cutoff=0.6)
    if matches:
        print(
            "Did you mean " + " or ".join(repr(match) for match in matches) + "?",
            file=sys.stderr,
        )
    return 2


def create_parser(
    extension_commands: Optional[Mapping[str, DiscoveredCommand]] = None,
) -> argparse.ArgumentParser:
    """Create the top-level parser for legacy flags and general help."""
    extension_help = _extension_command_help(extension_commands or {})
    parser = argparse.ArgumentParser(
        prog="spork",
        description="Spork - A Lisp to Python transpiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
core commands:
{_core_command_help()}
{extension_help}
examples:
  spork                         Start interactive REPL
  spork repl                    Start interactive REPL (explicit)
  spork new my-project          Create a new project
  spork add httpx rich          Add project dependencies
  spork remove httpx            Remove a project dependency
  spork sync                    Install project dependencies
  spork run                     Run project's main function
  spork check                   Check project sources and namespaces
  spork script.spork            Execute a Spork file
  spork -c "(+ 1 2 3)"          Evaluate Spork code directly
  spork -e script.spork         Export Spork file to Python code
  spork --nrepl                 Start nREPL server on default port
        """,
    )

    # Legacy/shortcut flags are intentionally separate from command parsers.
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
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the Spork CLI. Calls sys.exit with return code."""
    sys.exit(_main(argv))


def _main(argv: Optional[list[str]] = None) -> int:
    """Dispatch one CLI invocation and return its exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    delegated_result = _delegate_to_project_toolchain(arguments)
    if delegated_result is not None:
        return delegated_result

    # Core commands remain reliable bootstrap operations and never require
    # dynamic metadata discovery.
    if arguments and arguments[0] in CORE_COMMANDS:
        command = CORE_COMMANDS[arguments[0]]
        return invoke_command(command, arguments[1:])

    extension_state: Optional[_ExtensionCommandState] = None
    command_candidate = None
    if (
        arguments
        and not arguments[0].startswith("-")
        and not _is_explicit_file_token(arguments[0])
    ):
        command_candidate = arguments[0]
        extension_state = _discover_extension_state()
        if extension_state.project_error is not None:
            _print_discovery_diagnostic(
                f"could not load project configuration: "
                f"{extension_state.project_error}"
            )
            return 1

        diagnostics = extension_state.catalog.diagnostics_for(command_candidate)
        if diagnostics:
            for diagnostic in diagnostics:
                _print_discovery_diagnostic(diagnostic.message)
            return 1

        extension = extension_state.catalog.commands.get(command_candidate)
        if extension is not None:
            return _invoke_extension_command(
                extension,
                arguments[1:],
                extension_state.project,
            )
        return _unknown_command(command_candidate, extension_state.catalog)

    # Preserve explicit file execution and legacy flags outside command parsing.
    file_to_run = None
    legacy_arguments = arguments
    if arguments and _is_explicit_file_token(arguments[0]):
        file_to_run = arguments[0]
        legacy_arguments = arguments[1:]

    show_help = any(argument in {"-h", "--help"} for argument in legacy_arguments)
    if show_help and extension_state is None:
        extension_state = _discover_extension_state()
        if extension_state.project_error is not None:
            _print_discovery_diagnostic(
                f"could not load project configuration: "
                f"{extension_state.project_error}",
                warning=True,
            )
        for diagnostic in extension_state.catalog.diagnostics:
            _print_discovery_diagnostic(diagnostic.message, warning=True)

    extension_commands = (
        extension_state.catalog.commands if extension_state is not None else None
    )
    args = create_parser(extension_commands).parse_args(legacy_arguments)

    if args.nrepl:
        return cmd_nrepl_server(args.host, args.port)

    if args.nrepl_client:
        return cmd_nrepl_client(args.host, args.port)

    if args.command:
        return cmd_exec_code(args.command, args.interactive)

    if args.export:
        return cmd_export_file(args.export)

    if file_to_run:
        return cmd_exec_file(file_to_run, args.interactive)

    # No arguments retain the historical implicit REPL command while still
    # passing through the common command context and handler contract.
    return invoke_command(CORE_COMMANDS["repl"], [])


if __name__ == "__main__":
    main()
