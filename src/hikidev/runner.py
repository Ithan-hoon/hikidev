"""hikidev 용 CliRunner. 킷을 바꾸지 않고 본체 쪽에서 덮는 것 세 가지:

1. Windows `claude.cmd` 셸 shim 을 피한다. cmd.exe /c 는 인자 안의 줄바꿈에서 명령줄을 잘라 버려서
   `--append-system-prompt` 뒤의 `--permission-mode`, `--mcp-config` 가 통째로 사라진다 (2026-11-01 실연동에서 확인).
   shim 이 가리키는 `node_modules/@anthropic-ai/claude-code/bin/claude.exe` 를 직접 실행한다.
2. 시스템 프롬프트는 인자가 아니라 파일로 (`--append-system-prompt-file`). 길이·따옴표·줄바꿈에 안전.
3. `--strict-mcp-config`: 주인 claude 설정의 MCP(claude.ai 커넥터 등)가 세션에 들어가지 않게. 우리 mcp.json 만.
   `bypassPermissions` 일 때 `--allow-dangerously-skip-permissions` 도 함께 (CLI 가 요구하는 게이트 플래그).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path

from kits_runner import CliRunner, RunOptions

_SHIM_EXE_RE = re.compile(r'"%dp0%\\([^"]+\.exe)"', re.I)


def resolve_claude_exe(path: str) -> str:
    """`claude.cmd` npm shim 이면 그 안의 .exe 경로로. 아니면 그대로."""
    resolved = shutil.which(path) or path
    if not resolved.lower().endswith(".cmd"):
        return resolved
    p = Path(resolved)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return resolved
    if m := _SHIM_EXE_RE.search(text):
        exe = p.parent / m.group(1)
        if exe.exists():
            return str(exe)
    return resolved


class HikidevRunner(CliRunner):
    def __init__(self, claude_path: str | None = None, *, system_prompt_file: Path, **kw):
        super().__init__(claude_path, **kw)
        self.claude_path = resolve_claude_exe(self.claude_path)
        self.system_prompt_file = Path(system_prompt_file).resolve()

    def build_args(self, o: RunOptions) -> list[str]:
        sp = o.append_system_prompt
        args = super().build_args(replace(o, append_system_prompt=None))
        if sp:
            self.system_prompt_file.parent.mkdir(parents=True, exist_ok=True)
            self.system_prompt_file.write_text(sp, encoding="utf-8")
            args += ["--append-system-prompt-file", str(self.system_prompt_file)]
        if o.permission_mode == "bypassPermissions":
            args.append("--allow-dangerously-skip-permissions")
        if o.mcp_config:
            args.append("--strict-mcp-config")
        return args
