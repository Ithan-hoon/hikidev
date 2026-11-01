from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hikidev.home import HikidevHome
from hikidev.mcp_server import build_server, parse_sleep_time

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 1, 20, 0, tzinfo=KST)


def test_parse_sleep_time() -> None:
    assert parse_sleep_time("+2h", NOW) == NOW + timedelta(hours=2)
    assert parse_sleep_time("30m", NOW) == NOW + timedelta(minutes=30)
    assert parse_sleep_time("90", NOW) == NOW + timedelta(minutes=90)
    assert parse_sleep_time("09:00", NOW) == datetime(2026, 11, 2, 9, 0, tzinfo=KST)
    assert parse_sleep_time("21:30", NOW) == datetime(2026, 11, 1, 21, 30, tzinfo=KST)
    assert parse_sleep_time("2026-11-03T08:00", NOW) == datetime(2026, 11, 3, 8, 0, tzinfo=KST)
    assert parse_sleep_time("내일", NOW) is None


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def test_tools_write_files(home: HikidevHome) -> None:
    server = build_server(home)
    names = {t.name for t in await server.list_tools()}
    assert names == {"notify", "request_approval", "read_inbox", "new_chat", "sleep_until"}

    await server.call_tool("notify", {"message": "안녕 주인"})
    assert home.drain_outbox() == ["안녕 주인"]

    r = await server.call_tool("request_approval", {"action": "레포 공개", "why": "완성"})
    approvals = home.load_approvals()
    assert len(approvals) == 1 and approvals[0].status == "pending" and approvals[0].id in _text(r)

    assert _text(await server.call_tool("read_inbox", {})) == "새 메시지 없음."
    p = home.write_inbox(author="ithan", content="잘 지내?")
    home.update_approval(approvals[0].id, status="rejected", by="9")
    out = _text(await server.call_tool("read_inbox", {}))
    assert "잘 지내?" in out and "[rejected]" in out and "레포 공개" in out
    assert home.unread_inbox() == [] and (home.inbox_read_dir / p.name).exists()
    assert _text(await server.call_tool("read_inbox", {})) == "새 메시지 없음."

    await server.call_tool("new_chat", {"handoff": "p1 계속"})
    c = home.read_control()
    assert c["action"] == "new_chat" and c["handoff"] == "p1 계속"

    r = await server.call_tool("sleep_until", {"time": "+1h", "note": "눈 좀 붙임"})
    assert "까지 잔다" in _text(r)
    c = home.read_control()
    assert c["sleep_note"] == "눈 좀 붙임" and "T" in c["sleep_until"]

    r = await server.call_tool("sleep_until", {"time": "모레"})
    assert "못 읽었다" in _text(r)
