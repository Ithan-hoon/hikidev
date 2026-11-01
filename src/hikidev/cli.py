"""hikidev CLI: init | run | status | log | mcp | supervise"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .home import HikidevHome


def _utf8_stdout() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def _home(args: argparse.Namespace) -> HikidevHome:
    return HikidevHome(args.home or os.environ.get("HIKIDEV_HOME") or ".")


def _load(args: argparse.Namespace):
    from kits_config import load_env

    from .config import load_config

    home = _home(args)
    if not home.is_initialized():
        sys.exit(f"hikidev home 이 아닙니다: {home.root}\n먼저 `hikidev init {home.root}`")
    load_env(home.env_file)
    load_env(Path.cwd() / ".env")
    return home, load_config(home.config_yaml)


def _setup_logging(home: HikidevHome, level: str) -> None:
    from kits_logger import get_logger

    get_logger("hikidev", level=level.upper(), file=home.logs_dir / "orchestrator.jsonl")


# ── init ─────────────────────────────────────────────────────
def cmd_init(args: argparse.Namespace) -> None:
    home = HikidevHome(args.home or ".")
    values = {}
    if args.channel_id:
        values["channel_id"] = args.channel_id
    if args.owner_id:
        values["owner_id"] = args.owner_id
    made = home.init(name=args.name, values=values, force=args.force)
    print(f"hikidev home: {home.root}")
    for m in made:
        print(f"  + {m}")
    if not made:
        print("  (이미 다 있음)")
    print("\n다음:")
    print(f"  1. {home.root / 'self.md'} — 관심 분야·스택·성향 초기값")
    print(f"  2. {home.root / 'hikidev.yaml'} — 디스코드 채널 ID, 심장박동 주기")
    print(f"  3. {home.root / '.env'} — .env.example 을 복사해서 토큰")
    print("  4. claude 로그인 확인 (`claude login`)")
    print(f"  5. hikidev run --home {home.root} --once")


# ── run ──────────────────────────────────────────────────────
def cmd_run(args: argparse.Namespace) -> None:
    from .orchestrator import Orchestrator

    home, cfg = _load(args)
    _setup_logging(home, args.log_level)
    orch = Orchestrator(home, cfg)
    try:
        asyncio.run(orch.run(once=args.once))
    except KeyboardInterrupt:
        print("중단")


# ── status ───────────────────────────────────────────────────
def cmd_status(args: argparse.Namespace) -> None:
    home, cfg = _load(args)
    st = home.load_state()
    print(f"{cfg.name} @ {home.root}")
    print(f"  세션:          {home.current_session() or '(없음 — 다음은 새 세션)'}")
    print(f"  마지막 심장박동: {st.last_heartbeat or '-'} ({st.last_status or '-'})")
    cap = cfg.schedule.max_active_hours_per_day
    print(f"  오늘({st.date or '-'}): {st.heartbeats}회, 가동 {st.active_seconds / 3600:.2f}h / {cap}h")
    print(f"  연속 실패:     {st.consecutive_failures}")
    print(f"  컨텍스트:      {st.last_context_tokens} / {cfg.session.context_window_tokens} 토큰")
    print(f"  sleep_until:   {st.sleep_until or '-'}" + (f"  ({st.sleep_note})" if st.sleep_note else ""))
    pending = [a for a in home.load_approvals() if a.status == "pending"]
    print(f"  승인 대기:     {len(pending)}")
    for a in pending:
        print(f"    - {a.id} {a.action}")
    print(f"  inbox 미읽음:  {len(home.unread_inbox())}")
    projects = home.projects()
    print(f"  프로젝트:      {len(projects)}")
    for p in projects:
        print(f"    - {p['name']} [{p['status']}]")


# ── log ──────────────────────────────────────────────────────
def _summarize_line(line: str) -> str | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    t = obj.get("type")
    if t == "hikidev":
        return f"[hikidev] {obj.get('event')} " + " ".join(
            f"{k}={v}" for k, v in obj.items() if k not in ("type", "event", "signals") and v is not None
        )
    if t == "assistant":
        out = []
        for b in (obj.get("message") or {}).get("content") or []:
            if b.get("type") == "text":
                out.append(b["text"])
            elif b.get("type") == "tool_use":
                out.append(f"[tool {b.get('name')}] {json.dumps(b.get('input'), ensure_ascii=False)[:200]}")
        return "\n".join(out) if out else None
    if t == "result":
        return f"[result] {obj.get('subtype')} cost=${obj.get('total_cost_usd', 0):.3f} turns={obj.get('num_turns')}"
    if t == "rate_limit_event":
        return f"[rate_limit] {obj.get('rate_limit_info')}"
    return None


def cmd_log(args: argparse.Namespace) -> None:
    home, _ = _load(args)
    day = args.date or time.strftime("%Y-%m-%d")
    path = home.log_path(day)
    if not path.exists():
        sys.exit(f"로그 없음: {path}")
    with path.open(encoding="utf-8") as f:
        if not args.follow:
            for line in f.readlines()[-args.lines :]:
                s = line if args.raw else _summarize_line(line)
                if s:
                    print(s)
            return
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            s = line if args.raw else _summarize_line(line)
            if s:
                print(s, flush=True)


# ── mcp ──────────────────────────────────────────────────────
def cmd_mcp(args: argparse.Namespace) -> None:
    from .mcp_server import main as mcp_main

    mcp_main(["--home", str(_home(args).root)])


# ── supervise ────────────────────────────────────────────────
def cmd_supervise(args: argparse.Namespace) -> None:
    from kits_discord import send_webhook
    from kits_supervisor import Supervisor

    home, cfg = _load(args)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")

    def notify(msg: str) -> None:
        if webhook:
            send_webhook(webhook, msg, username="hikidev supervisor")
        else:
            print("[alert]", msg)

    sup = Supervisor(
        [sys.executable, "-m", "hikidev", "run", "--home", str(home.root)],
        cwd=str(home.root),
        name=cfg.name,
        max_crashes=args.max_crashes,
        window_s=args.window_min * 60,
        restart_delay_s=2,
        notify=notify,
    )
    final = sup.run()
    print("supervisor 정지:", final.stopped_reason)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hikidev", description="An autonomous developer that lives in your machine.")
    ap.add_argument("--version", action="version", version=f"hikidev {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="작업 폴더 생성")
    p.add_argument("home", nargs="?", default=".")
    p.add_argument("--name", default="hikidev")
    p.add_argument("--channel-id", default="")
    p.add_argument("--owner-id", default="")
    p.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")
    p.set_defaults(fn=cmd_init)

    for name, fn, help_ in (
        ("run", cmd_run, "심장박동 루프"),
        ("status", cmd_status, "상태"),
        ("log", cmd_log, "로그"),
        ("mcp", cmd_mcp, "MCP 서버 (stdio)"),
        ("supervise", cmd_supervise, "supervisor 로 run 감시"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--home", default=None, help="작업 폴더 (기본: $HIKIDEV_HOME 또는 현재 폴더)")
        p.set_defaults(fn=fn)
        if name == "run":
            p.add_argument("--once", action="store_true", help="심장박동 한 번만")
            p.add_argument("--log-level", default="info")
        if name == "log":
            p.add_argument("-f", "--follow", action="store_true")
            p.add_argument("-n", "--lines", type=int, default=50)
            p.add_argument("--date", default=None)
            p.add_argument("--raw", action="store_true")
        if name == "supervise":
            p.add_argument("--max-crashes", type=int, default=3)
            p.add_argument("--window-min", type=int, default=10)
    return ap


def main(argv: list[str] | None = None) -> None:
    _utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
