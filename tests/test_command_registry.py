"""Tests for the uniform static command model and top-level dispatcher."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import spork
import spork.cli as cli
from spork.commands import (
    COMMAND_API_VERSION,
    CommandContext,
    CommandProvider,
    CommandSpec,
    create_command_context,
    invoke_command,
)


EXPECTED_CORE_COMMANDS = (
    "repl",
    "new",
    "add",
    "remove",
    "sync",
    "run",
    "test",
    "check",
    "build",
    "dist",
    "clean",
    "lsp",
    "version",
)


def core_provider() -> CommandProvider:
    return CommandProvider(name="spork-lang", scope="core", version=spork.__version__)


def test_every_existing_core_command_is_statically_registered():
    assert tuple(cli.CORE_COMMANDS) == EXPECTED_CORE_COMMANDS
    assert cli.SUBCOMMANDS == frozenset(EXPECTED_CORE_COMMANDS)

    providers = {spec.provider for spec in cli.CORE_COMMANDS.values()}
    assert len(providers) == 1
    provider = providers.pop()
    assert provider.name == "spork-lang"
    assert provider.version == spork.__version__
    assert provider.scope == "core"
    assert provider.location == Path(cli.__file__).resolve()

    for name, spec in cli.CORE_COMMANDS.items():
        assert spec.name == name
        assert spec.summary
        assert callable(spec.handler)


def test_core_registry_and_descriptors_are_immutable():
    with pytest.raises(TypeError):
        cli.CORE_COMMANDS["other"] = cli.CORE_COMMANDS["version"]  # type: ignore[index]

    with pytest.raises(FrozenInstanceError):
        cli.CORE_COMMANDS["version"].name = "other"  # type: ignore[misc]


def test_command_context_is_immutable_and_records_provenance(tmp_path: Path):
    provider = core_provider()
    spec = CommandSpec("sample", "Sample command", lambda context, argv: 0, provider)

    context = create_command_context(spec, cwd=tmp_path)

    assert context.api_version == COMMAND_API_VERSION
    assert context.command == "sample"
    assert context.scope == "core"
    assert context.cwd == tmp_path.resolve()
    assert context.provider == provider
    assert context.project is None
    assert context.project_root is None

    with pytest.raises(FrozenInstanceError):
        context.command = "other"  # type: ignore[misc]


def test_command_context_rejects_mismatched_provider_scope(tmp_path: Path):
    provider = CommandProvider(name="provider", scope="global")

    with pytest.raises(ValueError, match="scope must match"):
        CommandContext(
            command="sample",
            scope="core",
            cwd=tmp_path,
            provider=provider,
        )


def test_common_invocation_passes_context_and_raw_argument_copy(tmp_path: Path):
    provider = core_provider()
    seen = {}

    def handler(context: CommandContext, argv: list[str]):
        seen["context"] = context
        seen["argv"] = list(argv)
        argv.append("changed")
        return None

    spec = CommandSpec("sample", "Sample command", handler, provider)
    context = create_command_context(spec, cwd=tmp_path)
    arguments = ["one", "--two", "three"]

    assert invoke_command(spec, arguments, context=context) == 0
    assert seen == {"context": context, "argv": arguments}
    assert arguments == ["one", "--two", "three"]


def test_common_invocation_preserves_integer_status_and_rejects_other_results():
    provider = core_provider()
    success = CommandSpec("success", "Success", lambda context, argv: 7, provider)
    invalid = CommandSpec("invalid", "Invalid", lambda context, argv: True, provider)

    assert invoke_command(success, []) == 7
    with pytest.raises(TypeError, match="expected int or None"):
        invoke_command(invalid, [])


def test_common_invocation_rejects_wrong_context(tmp_path: Path):
    provider = core_provider()
    first = CommandSpec("first", "First", lambda context, argv: 0, provider)
    second = CommandSpec("second", "Second", lambda context, argv: 0, provider)
    context = create_command_context(first, cwd=tmp_path)

    with pytest.raises(ValueError, match="context is for"):
        second.invoke(context, [])


def test_each_core_command_has_an_isolated_parser():
    assert cli.create_command_parser("repl").parse_args([]) is not None
    assert cli.create_command_parser("test").parse_args([]) is not None
    assert cli.create_command_parser("version").parse_args([]) is not None

    new = cli.create_command_parser("new").parse_args(["demo", "--path", "parent"])
    assert (new.name, new.path) == ("demo", "parent")

    add = cli.create_command_parser("add").parse_args(["httpx", "rich>=13"])
    assert add.packages == ["httpx", "rich>=13"]

    remove = cli.create_command_parser("remove").parse_args(["httpx"])
    assert remove.packages == ["httpx"]

    sync = cli.create_command_parser("sync").parse_args(["--quiet", "--dev"])
    assert sync.quiet and sync.dev

    run = cli.create_command_parser("run").parse_args(
        ["--main", "sample.core:start", "first", "second"]
    )
    assert run.main == "sample.core:start"
    assert run.args == ["first", "second"]

    check = cli.create_command_parser("check").parse_args(
        ["--json", "--no-tests", "--warnings-as-errors"]
    )
    assert check.format == "json"
    assert check.no_tests and check.warnings_as_errors

    build = cli.create_command_parser("build").parse_args(["-o", "generated", "-c"])
    assert build.out_dir == "generated"
    assert build.clean

    dist = cli.create_command_parser("dist").parse_args(
        ["-d", "packages", "-o", "generated", "--clean", "--wheel-only"]
    )
    assert dist.dist_dir == "packages"
    assert dist.out_dir == "generated"
    assert dist.clean and dist.wheel_only and not dist.sdist_only

    clean = cli.create_command_parser("clean").parse_args(["--all"])
    assert clean.all

    lsp = cli.create_command_parser("lsp").parse_args(["--log", "lsp.log"])
    assert lsp.log == "lsp.log"

    with pytest.raises(ValueError, match="unknown core command"):
        cli.create_command_parser("missing")


def test_top_level_help_lists_static_commands_deterministically(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)

    with pytest.raises(SystemExit) as exited:
        cli._main(["--help"])

    assert exited.value.code == 0
    output = capsys.readouterr().out
    assert "core commands:" in output
    positions = [output.index(f"  {name}") for name in EXPECTED_CORE_COMMANDS]
    assert positions == sorted(positions)


def test_command_help_uses_its_own_parser(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)

    with pytest.raises(SystemExit) as exited:
        cli._main(["check", "--help"])

    assert exited.value.code == 0
    output = capsys.readouterr().out
    assert output.startswith("usage: spork check")
    assert "--warnings-as-errors" in output
    assert "--nrepl" not in output


def test_top_level_dispatch_passes_raw_arguments_to_selected_command(
    tmp_path: Path, monkeypatch
):
    provider = core_provider()
    seen = {}

    def handler(context: CommandContext, argv: list[str]):
        seen["context"] = context
        seen["argv"] = argv
        return 9

    spec = CommandSpec("probe", "Probe command", handler, provider)
    monkeypatch.setattr(cli, "CORE_COMMANDS", {"probe": spec, "repl": spec})
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.chdir(tmp_path)

    assert cli._main(["probe", "one", "--two=three"]) == 9
    assert seen["argv"] == ["one", "--two=three"]
    assert seen["context"].command == "probe"
    assert seen["context"].cwd == tmp_path.resolve()


def test_direct_file_and_legacy_code_remain_outside_command_parsing(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.setattr(
        cli,
        "cmd_exec_file",
        lambda path, interactive=False: calls.append(("file", path, interactive)) or 4,
    )
    monkeypatch.setattr(
        cli,
        "cmd_exec_code",
        lambda code, interactive=False: calls.append(("code", code, interactive)) or 5,
    )

    assert cli._main(["sample.spork", "--interactive"]) == 4
    assert cli._main(["--command", "(+ 1 2)", "--interactive"]) == 5
    assert calls == [
        ("file", "sample.spork", True),
        ("code", "(+ 1 2)", True),
    ]


def test_no_arguments_invoke_repl_through_common_command_contract(
    tmp_path: Path, monkeypatch
):
    provider = core_provider()
    seen = []

    def handler(context: CommandContext, argv: list[str]):
        seen.append((context, argv))
        return 6

    repl = CommandSpec("repl", "REPL", handler, provider)
    monkeypatch.setattr(cli, "CORE_COMMANDS", {"repl": repl})
    monkeypatch.setattr(cli, "_delegate_to_project_toolchain", lambda argv: None)
    monkeypatch.chdir(tmp_path)

    assert cli._main([]) == 6
    assert len(seen) == 1
    context, arguments = seen[0]
    assert context.command == "repl"
    assert context.cwd == tmp_path.resolve()
    assert arguments == []
