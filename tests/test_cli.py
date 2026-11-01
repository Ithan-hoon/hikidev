from __future__ import annotations

from pathlib import Path

from hikidev.cli import _summarize_line, main


def test_init_and_status(tmp_path: Path, capsys) -> None:
    root = tmp_path / "h"
    main(["init", str(root), "--name", "ithan's hikidev", "--channel-id", "1", "--owner-id", "2"])
    out = capsys.readouterr().out
    assert "self.md" in out
    assert "ithan's hikidev" in (root / "self.md").read_text(encoding="utf-8")
    main(["status", "--home", str(root)])
    out = capsys.readouterr().out
    assert "ithan's hikidev" in out and "다음은 새 세션" in out


def test_summarize_line() -> None:
    assert (
        _summarize_line('{"type":"hikidev","event":"heartbeat_end","status":"ok"}')
        == "[hikidev] heartbeat_end status=ok"
    )
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"},{"type":"tool_use","name":"notify","input":{"message":"x"}}]}}'
    assert _summarize_line(line) == 'hi\n[tool notify] {"message": "x"}'
    assert _summarize_line("not json") is None
    assert _summarize_line('{"type":"user"}') is None
