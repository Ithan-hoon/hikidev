from __future__ import annotations

from pathlib import Path

from hikidev.config import load_config
from hikidev.home import HikidevHome
from hikidev.prompt import HeartbeatContext, Signals, emergency_handoff, heartbeat_prompt, system_prompt


def test_load_config_defaults_and_override(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "hikidev.yaml"
    p.write_text("name: me\nschedule:\n  heartbeat_minutes: 5\ndiscord:\n  channel_id: 42\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.name == "me"
    assert cfg.schedule.heartbeat_minutes == 5
    assert cfg.schedule.max_active_hours_per_day == 8  # 기본값 유지
    assert cfg.discord.channel_id == "42"  # 숫자도 문자열로
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "99")
    assert load_config(p).discord.channel_id == "99"
    assert load_config(tmp_path / "none.yaml").name == "hikidev"


def _signals() -> Signals:
    return Signals(
        now="2026-11-01 20:00",
        weekday="일",
        heartbeats_today=2,
        active_hours_today=1.5,
        max_active_hours=8,
        consecutive_failures=0,
        context_used_ratio=0.4,
    )


def test_system_prompt_is_not_imperative(home: HikidevHome) -> None:
    s = system_prompt("ithan's hikidev", home.root, "9", "ko")
    assert "ithan's hikidev" in s and str(home.root) in s
    for tool in ("notify", "request_approval", "read_inbox", "new_chat", "sleep_until"):
        assert tool in s
    assert "active | paused | done | abandoned" in s
    assert "반드시" not in s and "해야 한다" not in s


def test_heartbeat_prompt_new_session_includes_memory(home: HikidevHome) -> None:
    home.journal_dir.joinpath("2026-10-31.md").write_text("# 어제\n좀 했다", encoding="utf-8")
    (home.projects_dir / "p1").mkdir()
    (home.projects_dir / "p1" / "NOTES.md").write_text("status: active\n뭔가", encoding="utf-8")
    p = home.write_inbox(author="ithan", content="hi")
    ctx = HeartbeatContext(signals=_signals(), new_session=True, inbox_files=[p], handoff="지난 메모")
    text = heartbeat_prompt(home, ctx)
    assert "### self.md" in text and "# test hikidev" in text
    assert "journal/2026-10-31.md" in text and "좀 했다" in text
    assert "**p1** — status: active" in text
    assert "새 inbox 1건" in text and p.name in text
    assert "지난 메모" in text
    assert "컨텍스트 사용: 약 40%" in text


def test_heartbeat_prompt_resumed_is_light(home: HikidevHome) -> None:
    ctx = HeartbeatContext(signals=_signals(), new_session=False, forced_reason=None)
    text = heartbeat_prompt(home, ctx)
    assert "### self.md" not in text
    assert "[심장박동]" in text and "## 신호" in text


def test_emergency_handoff(home: HikidevHome) -> None:
    home.journal_dir.joinpath("2026-11-01.md").write_text("오늘 일기", encoding="utf-8")
    (home.projects_dir / "p1").mkdir()
    (home.projects_dir / "p1" / "NOTES.md").write_text("status: active\n진행중", encoding="utf-8")
    (home.projects_dir / "p2").mkdir()
    (home.projects_dir / "p2" / "NOTES.md").write_text("status: done", encoding="utf-8")
    h = emergency_handoff(home)
    assert "오늘 일기" in h and "projects/p1/NOTES.md" in h and "p2" not in h
