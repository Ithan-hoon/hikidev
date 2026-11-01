"""MCP 서버 (stdio). claude 세션에 `--mcp-config` 로 붙는다.

claude 의 자식 프로세스라 오케스트레이터와 메모리를 공유하지 않는다. 전부 HikidevHome 의 파일을 통해 전달하고,
디스코드 전송은 오케스트레이터가 중계한다 (relay.py). stdout 은 MCP 전용이라 print 금지.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .home import HikidevHome


def parse_sleep_time(text: str, now: datetime | None = None) -> datetime | None:
    """'2026-11-02T09:00', '09:00', '+2h', '+30m', '90' (분) 을 받는다. 못 읽으면 None."""
    now = now or datetime.now().astimezone()
    s = text.strip()
    if m := re.fullmatch(r"\+?(\d+(?:\.\d+)?)\s*([hm])", s, re.I):
        n = float(m.group(1))
        return now + (timedelta(hours=n) if m.group(2).lower() == "h" else timedelta(minutes=n))
    if re.fullmatch(r"\d+", s):
        return now + timedelta(minutes=int(s))
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})", s):
        cand = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return cand if cand > now else cand + timedelta(days=1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def build_server(home: HikidevHome):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("hikidev", instructions="hikidev 의 방과 주인을 잇는 도구")

    @server.tool(description="디스코드 #hikidev 채널에 메시지를 보낸다. 뭘 알릴지는 네 마음.")
    def notify(message: str) -> str:
        home.push_outbox(message)
        return "보냈다 (오케스트레이터가 디스코드로 전달)."

    @server.tool(
        description="바깥 행동(레포 public 전환, 배포, 계정 필요 등)의 승인을 주인에게 요청한다. "
        "바로 결과가 오지 않으니 기다리지 말고 다른 일을 하면 된다. 결과는 read_inbox 나 다음 심장박동에서."
    )
    def request_approval(action: str, why: str) -> str:
        a = home.add_approval(action, why)
        return f"승인 요청 등록 (id={a.id}). 결과는 read_inbox 또는 다음 심장박동에 온다."

    @server.tool(description="주인이 디스코드에 쓴 새 메시지와 승인 결과를 읽는다. 읽으면 읽음 처리된다.")
    def read_inbox() -> str:
        files = home.unread_inbox()
        decisions = home.unseen_decisions(mark=True)
        if not files and not decisions:
            return "새 메시지 없음."
        parts: list[str] = []
        for p in files:
            parts.append(f"--- {p.name}\n{p.read_text(encoding='utf-8', errors='replace').strip()}")
        home.mark_inbox_read(files)
        for a in decisions:
            who = f" by {a.by}" if a.by else ""
            parts.append(f"--- 승인 결과 [{a.status}]{who}: {a.action} (id={a.id})")
        return "\n\n".join(parts)

    @server.tool(
        description="인수인계 메모를 남기고 새 세션으로 넘어간다. 이 턴을 끝내면 다음 심장박동이 새 채팅으로 시작된다. "
        "journal 과 NOTES 를 먼저 갱신해 두는 편이 좋다."
    )
    def new_chat(handoff: str) -> str:
        home.write_control({"action": "new_chat", "handoff": handoff})
        return "접수. 이 턴이 끝나면 새 채팅으로 넘어간다. 인수인계 메모는 다음 세션 첫 프롬프트에 들어간다."

    @server.tool(
        description="다음에 깰 시각을 정한다. time: ISO('2026-11-02T09:00'), 'HH:MM', '+2h', '+30m'. "
        "note 는 깰 때 네게 다시 보여준다."
    )
    def sleep_until(time: str, note: str = "") -> str:
        dt = parse_sleep_time(time)
        if dt is None:
            return f"시각을 못 읽었다: {time!r}. ISO / HH:MM / +2h / +30m 형식으로."
        home.write_control({"sleep_until": dt.isoformat(timespec="seconds"), "sleep_note": note})
        return f"알겠다. {dt.strftime('%Y-%m-%d %H:%M')} 까지 잔다. 턴을 끝내면 된다."

    return server


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="hikidev mcp")
    ap.add_argument("--home", required=True)
    args = ap.parse_args(argv)
    home = HikidevHome(Path(args.home))
    if not home.is_initialized():
        print(f"hikidev home 이 아님: {home.root}", file=sys.stderr)
        sys.exit(2)
    build_server(home).run("stdio")


if __name__ == "__main__":
    main()
