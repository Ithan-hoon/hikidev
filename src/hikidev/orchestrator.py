"""심장박동 루프. 깨우고, 신호를 주고, 세션을 돌리고, 기록한다. 뭘 할지는 hikidev 가 정한다.

비상 개입만 한다: 컨텍스트 임계치 초과 / 프로세스 사망 / 연속 실패 → 강제 새 채팅 (인수인계 = 마지막 journal + NOTES).
rate limit 이면 리셋까지 잔다. 하루 가동 시간 상한을 넘으면 자정까지 잔다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from kits_runner import Error, RateLimit, Raw, RunOptions, RunSummary, SessionId, collect

from .config import Config
from .home import HikidevHome, State, now_iso
from .notion_mirror import mirror_journal
from .prompt import HeartbeatContext, Signals, emergency_handoff, heartbeat_prompt, system_prompt
from .relay import Relay

log = logging.getLogger("hikidev")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
SESSION_ENV_BLANK = {"DISCORD_BOT_TOKEN": "", "DISCORD_WEBHOOK_URL": "", "NOTION_TOKEN": ""}
"""세션(hikidev)에게는 주인 쪽 토큰을 보여주지 않는다. GITHUB_TOKEN 은 걔 것이라 그대로."""
FAILURE_STATUSES = ("process_died", "error", "orchestrator_error")
"""연속 실패로 세는 상태. orchestrator_error 는 heartbeat() 자체의 예외 (예: 출력 한 줄이 너무 길어 파싱 실패)."""


def local_now() -> datetime:
    return datetime.now().astimezone()


def context_tokens_from_raw(obj: Any) -> int | None:
    """assistant 메시지의 usage 에서 이 턴의 컨텍스트 크기를 추정한다."""
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    usage = (obj.get("message") or {}).get("usage")
    if not isinstance(usage, dict):
        return None
    total = 0
    for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = usage.get(k)
        if isinstance(v, int | float):
            total += int(v)
    return total or None


class Orchestrator:
    def __init__(self, home: HikidevHome, cfg: Config, *, runner: Any = None, relay: Relay | None = None):
        self.home = home
        self.cfg = cfg
        self.runner = runner or self._default_runner()
        self.relay = relay or Relay(home, cfg.discord, os.environ.get("DISCORD_BOT_TOKEN"), owner_name=cfg.owner)
        self._stop = asyncio.Event()

    def _default_runner(self) -> Any:
        if self.cfg.runner == "sdk":
            from kits_runner import SdkRunner

            return SdkRunner(daily_budget_usd=self.cfg.budget.daily_usd)
        from kits_runner import CliRunner

        return CliRunner()

    # ── 루프 ─────────────────────────────────────────────────
    async def run(self, *, once: bool = False) -> None:
        await self.relay.start()
        try:
            while not self._stop.is_set():
                if not once:
                    await self._wait_for_wake()
                    if self._stop.is_set():
                        break
                try:
                    await self.heartbeat()
                except Exception as e:
                    log.exception("심장박동 실패")
                    self._record_orchestrator_error(e)
                if once:
                    break
        finally:
            await self.relay.stop()

    def _record_orchestrator_error(self, exc: BaseException) -> None:
        """heartbeat() 자체가 터졌을 때. 곧바로 같은 세션을 다시 돌리면 같은 줄에서 또 터져 초 단위 루프가 되므로
        last_heartbeat 를 찍어 기본 심장박동 주기만큼은 쉬게 하고, 연속 실패로 센다 (max 넘으면 새 채팅)."""
        now = local_now()
        st = self.home.load_state()
        self._roll_date(st, now.strftime("%Y-%m-%d"))
        st.consecutive_failures += 1
        st.last_status = "orchestrator_error"
        st.last_heartbeat = now_iso()
        st.sleep_until = None
        self.home.save_state(st)
        self.home.append_log(
            now.strftime("%Y-%m-%d"),
            {
                "type": "hikidev",
                "event": "orchestrator_error",
                "at": now_iso(),
                "error": f"{type(exc).__name__}: {exc}",
                "consecutive_failures": st.consecutive_failures,
            },
        )

    def stop(self) -> None:
        self._stop.set()

    def next_wake(self, state: State, now: datetime | None = None) -> datetime:
        now = now or local_now()
        if state.sleep_until:
            try:
                t = datetime.fromisoformat(state.sleep_until)
                if t > now:
                    return t
            except ValueError:
                pass
        if state.last_heartbeat:
            try:
                last = datetime.fromisoformat(state.last_heartbeat)
                return max(now, last + timedelta(minutes=self.cfg.schedule.heartbeat_minutes))
            except ValueError:
                pass
        return now

    async def _wait_for_wake(self) -> None:
        wake = self.next_wake(self.home.load_state())
        delay = (wake - local_now()).total_seconds()
        if delay > 0:
            log.info("다음 심장박동 %s (%.0f분 후)", wake.strftime("%m-%d %H:%M"), delay / 60)
            # 자는 동안에도 디스코드 inbox 는 받고 승인 큐는 중계한다
            await self.relay.start_polling(5.0)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            finally:
                await self.relay.stop_polling()

    # ── 심장박동 한 번 ───────────────────────────────────────
    def _roll_date(self, state: State, today: str) -> None:
        if state.date != today:
            state.date = today
            state.active_seconds = 0
            state.heartbeats = 0

    def _signals(self, state: State, now: datetime, rate_note: str | None = None) -> Signals:
        ratio = None
        if state.last_context_tokens and self.home.current_session():
            ratio = state.last_context_tokens / self.cfg.session.context_window_tokens
        return Signals(
            now=now.strftime("%Y-%m-%d %H:%M"),
            weekday=WEEKDAYS[now.weekday()],
            heartbeats_today=state.heartbeats + 1,
            active_hours_today=state.active_seconds / 3600,
            max_active_hours=self.cfg.schedule.max_active_hours_per_day,
            consecutive_failures=state.consecutive_failures,
            rate_limit_note=rate_note,
            context_used_ratio=ratio,
            context_soft=self.cfg.session.context_soft,
            context_hard=self.cfg.session.context_threshold,
            last_sleep_note=state.sleep_note,
        )

    def _decide_session(self, state: State, control: dict[str, Any]) -> tuple[bool, str | None, str | None]:
        """(새 세션인가, 인수인계, 강제 사유)"""
        current = self.home.current_session()
        if current is None:
            return True, control.get("handoff"), None
        if control.get("action") == "new_chat":
            self.home.set_session(None, reason="new_chat")
            return True, control.get("handoff"), None
        s = self.cfg.session
        reason = None
        ratio = state.last_context_tokens / s.context_window_tokens if state.last_context_tokens else 0
        if ratio >= s.context_threshold:
            reason = (
                f"지난 세션 컨텍스트가 {ratio * 100:.0f}% 라 오케스트레이터가 새 채팅으로 넘겼다 "
                f"(임계 {s.context_threshold * 100:.0f}%)."
            )
        elif state.last_status in FAILURE_STATUSES and state.consecutive_failures >= s.max_consecutive_failures:
            reason = f"지난 세션이 {state.consecutive_failures}회 연속 비정상 종료라 새 채팅으로 넘겼다."
        elif state.last_status == "process_died":
            reason = "지난 세션 프로세스가 죽어서 새 채팅으로 넘겼다."
        if reason:
            self.home.set_session(None, reason="forced")
            return True, emergency_handoff(self.home), reason
        return False, None, None

    def write_mcp_config(self) -> str:
        cfg = {
            "mcpServers": {
                "hikidev": {
                    "command": sys.executable,
                    "args": ["-m", "hikidev", "mcp", "--home", str(self.home.root)],
                }
            }
        }
        self.home.mcp_json.parent.mkdir(parents=True, exist_ok=True)
        self.home.mcp_json.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return str(self.home.mcp_json)

    async def heartbeat(self) -> RunSummary | None:
        now = local_now()
        today = now.strftime("%Y-%m-%d")
        state = self.home.load_state()
        self._roll_date(state, today)
        state.sleep_until = None

        cap_s = self.cfg.schedule.max_active_hours_per_day * 3600
        if state.active_seconds >= cap_s:
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            state.sleep_until = midnight.isoformat(timespec="seconds")
            self.home.save_state(state)
            log.info("오늘 가동 상한 도달 (%.1fh) — 자정까지 잔다", state.active_seconds / 3600)
            self.home.append_log(today, {"type": "hikidev", "event": "daily_cap", "at": now_iso()})
            return None

        control = self.home.read_control(clear=True)
        new_session, handoff, forced = self._decide_session(state, control)
        resume = None if new_session else self.home.current_session()
        ctx = HeartbeatContext(
            signals=self._signals(state, now),
            new_session=new_session,
            inbox_files=self.home.unread_inbox(),
            decisions=self.home.unseen_decisions(mark=False),
            handoff=handoff,
            forced_reason=forced,
        )
        prompt = heartbeat_prompt(self.home, ctx)
        s = self.cfg.session
        # 시스템 프롬프트는 파일로 (인자 길이·줄바꿈 안전), MCP 는 우리 mcp.json 만 (주인 claude.ai 커넥터 차단)
        sp_file = self.home.dot / "system-prompt.md"
        sp_file.write_text(
            system_prompt(self.cfg.name, self.home.root, self.cfg.owner, self.cfg.language), encoding="utf-8"
        )
        opts = RunOptions(
            prompt=prompt,
            resume=resume,
            cwd=str(self.home.root),
            model=s.model,
            max_turns=s.max_turns,
            append_system_prompt_file=str(sp_file),
            permission_mode=s.permission_mode,
            mcp_config=self.write_mcp_config(),
            strict_mcp_config=True,
            env=dict(SESSION_ENV_BLANK),
            timeout_s=s.timeout_minutes * 60,
        )
        self.home.append_log(
            today,
            {
                "type": "hikidev",
                "event": "heartbeat_start",
                "at": now_iso(),
                "new_session": new_session,
                "resume": resume,
                "forced": forced,
                "signals": ctx.signals.render(),
            },
        )
        log.info("심장박동 #%d %s", state.heartbeats + 1, "새 세션" if new_session else f"이어서 {resume}")

        last_ctx: dict[str, int] = {}

        def on_event(e: Any) -> None:
            if isinstance(e, Raw):
                self.home.append_log(today, e.json)
                if (n := context_tokens_from_raw(e.json)) is not None:
                    last_ctx["tokens"] = n
            elif isinstance(e, SessionId):
                if self.home.current_session() != e.session_id:
                    self.home.set_session(e.session_id, reason="new")
            elif isinstance(e, Error | RateLimit):
                self.home.append_log(today, {"type": "hikidev", "event": e.type, "message": e.message})

        await self.relay.start_polling()
        t0 = time.monotonic()
        try:
            summary = await collect(self.runner.run(opts), on_event)
        finally:
            elapsed = time.monotonic() - t0
            await self.relay.stop_polling()

        lost = summary.error is not None and summary.error.code == "api_error" and not summary.num_turns
        if resume and summary.status == "error" and lost:
            # 다른 머신(호스트↔컨테이너)으로 옮기면 세션 기록이 없어 resume 이 즉시 실패한다 → 새 세션으로 한 번 더
            log.warning("세션 %s 을(를) 이어갈 수 없다 — 새 세션으로 다시 시작", resume)
            self.home.set_session(None, reason="session_lost")
            self.home.append_log(today, {"type": "hikidev", "event": "session_lost", "at": now_iso(), "resume": resume})
            return await self.heartbeat()

        # ── 사후 처리 ──
        state = self.home.load_state()  # relay 가 건드렸을 수도
        self._roll_date(state, today)
        state.heartbeats += 1
        state.active_seconds += elapsed
        state.last_heartbeat = now_iso()
        state.last_context_tokens = last_ctx.get("tokens", state.last_context_tokens if not new_session else 0)
        state.sleep_note = None
        if summary.session_id:
            self.home.set_session(summary.session_id, reason="result")

        if summary.status == "ok":
            state.consecutive_failures = 0
            state.last_status = "ok"
        elif summary.status == "rate_limited":
            state.last_status = "rate_limited"
            rl = summary.rate_limit
            until = rl.resets_at.astimezone() if rl and rl.resets_at else None
            if until is None or until <= now:
                until = local_now() + timedelta(minutes=self.cfg.schedule.rate_limit_fallback_minutes)
            state.sleep_until = until.isoformat(timespec="seconds")
            log.warning("rate limit — %s 까지 잔다", until.strftime("%m-%d %H:%M"))
        else:
            state.consecutive_failures += 1
            code = summary.error.code if summary.error else "unknown"
            state.last_status = "process_died" if code in ("exit_nonzero", "timeout", "spawn_failed") else "error"
            log.warning("세션 오류 (%s): %s", code, summary.error.message if summary.error else "")
            if code == "not_logged_in":
                log.error("claude 로그인이 안 되어 있다. 호스트에서 `claude login` 이 필요하다.")

        post = self.home.read_control(clear=False)
        if post.get("sleep_until") and summary.status == "ok":
            state.sleep_until = post["sleep_until"]
            state.sleep_note = post.get("sleep_note") or None
        if post.get("action") == "new_chat":
            self.home.write_control({"action": "new_chat", "handoff": post.get("handoff", "")})
        else:
            self.home.read_control(clear=True)
        self.home.save_state(state)

        url = await asyncio.to_thread(mirror_journal, self.home, self.cfg.notion, today)
        self.home.append_log(
            today,
            {
                "type": "hikidev",
                "event": "heartbeat_end",
                "at": now_iso(),
                "status": summary.status,
                "session": summary.session_id,
                "turns": summary.num_turns,
                "cost_usd": summary.total_cost_usd,
                "elapsed_s": round(elapsed),
                "context_tokens": state.last_context_tokens,
                "sleep_until": state.sleep_until,
                "notion": url,
            },
        )
        log.info(
            "심장박동 끝: %s, %s턴, %.0f초, 컨텍스트 %s 토큰",
            summary.status,
            summary.num_turns,
            elapsed,
            state.last_context_tokens,
        )
        return summary
