from __future__ import annotations

from pathlib import Path

from kits_runner import RunOptions

from hikidev.runner import HikidevRunner, resolve_claude_exe


def test_resolve_claude_exe_from_npm_shim(tmp_path: Path) -> None:
    exe = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    shim = tmp_path / "claude.cmd"
    shim.write_text(
        '@ECHO off\r\nSETLOCAL\r\n"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\r\n',
        encoding="utf-8",
    )
    assert resolve_claude_exe(str(shim)) == str(exe)
    # exe 가 없으면 shim 그대로
    exe.unlink()
    assert resolve_claude_exe(str(shim)) == str(shim)
    assert resolve_claude_exe("/usr/bin/claude") == "/usr/bin/claude"


def test_build_args_uses_prompt_file_and_strict_mcp(tmp_path: Path) -> None:
    sp_file = tmp_path / "system-prompt.md"
    r = HikidevRunner("claude-not-found", system_prompt_file=sp_file)
    o = RunOptions(
        prompt="x",
        append_system_prompt="line one\nline two",
        permission_mode="bypassPermissions",
        mcp_config=str(tmp_path / "mcp.json"),
    )
    args = r.build_args(o)
    assert "--append-system-prompt" not in args
    assert args[args.index("--append-system-prompt-file") + 1] == str(sp_file)
    assert sp_file.read_text(encoding="utf-8") == "line one\nline two"
    assert "--allow-dangerously-skip-permissions" in args and "--strict-mcp-config" in args
    assert args[args.index("--permission-mode") + 1] == "bypassPermissions"
    assert not any("\n" in a for a in args)

    plain = r.build_args(RunOptions(prompt="x", permission_mode="acceptEdits"))
    assert "--allow-dangerously-skip-permissions" not in plain and "--strict-mcp-config" not in plain
    assert "--append-system-prompt-file" not in plain
