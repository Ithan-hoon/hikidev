from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kits_runner import RunnerEvent, RunOptions, events_from_json

from hikidev.config import Config
from hikidev.home import HikidevHome
from hikidev.orchestrator import Orchestrator, context_tokens_from_raw


def _assistant(text: str, ctx_tokens: int = 1000) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": ctx_tokens - 100, "output_tokens": 10},
        },
    }


def _result(session_id: str, text: str = "done") -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "session_id": session_id,
        "result": text,
        "is_error": False,
        "total_cost_usd": 0.01,
        "duration_ms": 1500,
        "num_turns": 2,
    }


class FakeRunner:
    """stream-json 줄을 순서대로 뱉는 가짜. 호출마다 받은 RunOptions 를 기억한다."""

    def __init__(self, *scripts: list[dict]):
        self.scripts = list(scripts)
        self.calls: list[RunOptions] = []
        self.on_run = None

    async def run(self, opts: RunOptions) -> AsyncIterator[RunnerEvent]:
        self.calls.append(opts)
        script = self.scripts.pop(0) if self.scripts else [_result("s-default")]
        if self.on_run:
            self.on_run(opts)
        for obj in script:
            for e in events_from_json(obj):
                yield e


def test_context_tokens_from_raw() -> None:
    assert context_tokens_from_raw(_assistant("x", 5000)) == 5000
    assert context_tokens_from_raw({"type": "result"}) is None


async def test_first_heartbeat_new_session(home: HikidevHome, cfg: Config) -> None:
    runner = FakeRunner(
        [{"type": "system", "subtype": "init", "session_id": "s1"}, _assistant("안녕", 3000), _result("s1")]
    )
    orch = Orchestrator(home, cfg, runner=runner)
    s = await orch.heartbeat()
    assert s is not None and s.status == "ok"
    o = runner.calls[0]
    assert o.resume is None and o.cwd == str(home.root) and o.mcp_config == str(home.mcp_json)
    assert "### self.md" in o.prompt
    assert o.append_system_prompt is None
    assert "test hikidev" in Path(o.append_system_prompt_file).read_text(encoding="utf-8")
    assert o.permission_mode == "bypassPermissions" and o.strict_mcp_config is True
    assert o.env["DISCORD_BOT_TOKEN"] == ""
    assert home.current_session() == "s1"
    st = home.load_state()
    assert st.heartbeats == 1 and st.last_status == "ok" and st.last_context_tokens == 3000 and st.active_seconds >= 0
    mcp = json.loads(home.mcp_json.read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["hikidev"]["args"][-1] == str(home.root)
    day = datetime.now().strftime("%Y-%m-%d")
    lines = [json.loads(x) for x in home.log_path(day).read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "heartbeat_start" and lines[-1]["event"] == "heartbeat_end"
    assert any(x.get("type") == "assistant" for x in lines)


async def test_second_heartbeat_resumes(home: HikidevHome, cfg: Config) -> None:
    runner = FakeRunner([_result("s1")], [_result("s1")])
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    await orch.heartbeat()
    assert runner.calls[1].resume == "s1"
    assert "### self.md" not in runner.calls[1].prompt


async def test_new_chat_control_starts_fresh_with_handoff(home: HikidevHome, cfg: Config) -> None:
    runner = FakeRunner([_result("s1")], [_result("s2")])

    def during(opts: RunOptions) -> None:
        if not opts.resume:
            home.write_control({"action": "new_chat", "handoff": "p1 다음은 테스트"})

    runner.on_run = during
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    runner.on_run = None
    await orch.heartbeat()
    assert runner.calls[1].resume is None
    assert "p1 다음은 테스트" in runner.calls[1].prompt
    assert home.current_session() == "s2" and home.read_control() == {}


async def test_sleep_until_control(home: HikidevHome, cfg: Config) -> None:
    until = (datetime.now().astimezone() + timedelta(hours=3)).isoformat(timespec="seconds")
    runner = FakeRunner([_result("s1")])
    runner.on_run = lambda o: home.write_control({"sleep_until": until, "sleep_note": "쉼"})
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    st = home.load_state()
    assert st.sleep_until == until and st.sleep_note == "쉼"
    assert orch.next_wake(st).isoformat(timespec="seconds") == until
    # 다음 심장박동 프롬프트에 메모가 보이고, 그 뒤엔 지워진다
    runner.on_run = None
    await orch.heartbeat()
    assert "잠들기 전 메모: 쉼" in runner.calls[1].prompt
    assert home.load_state().sleep_note is None


async def test_context_threshold_forces_new_chat(home: HikidevHome, cfg: Config) -> None:
    cfg.session.context_window_tokens = 10_000
    runner = FakeRunner([_assistant("x", 9000), _result("s1")], [_result("s2")])
    orch = Orchestrator(home, cfg, runner=runner)
    home.journal_dir.joinpath("2026-11-01.md").write_text("마지막 일기", encoding="utf-8")
    await orch.heartbeat()
    await orch.heartbeat()
    o = runner.calls[1]
    assert o.resume is None and "90%" in o.prompt and "마지막 일기" in o.prompt
    assert home.current_session() == "s2"


async def test_rate_limit_sleeps_until_reset(home: HikidevHome, cfg: Config) -> None:
    resets = int((datetime.now(UTC) + timedelta(hours=2)).timestamp())
    runner = FakeRunner(
        [
            {
                "type": "rate_limit_event",
                "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour", "resetsAt": resets},
            }
        ]
    )
    orch = Orchestrator(home, cfg, runner=runner)
    s = await orch.heartbeat()
    assert s is not None and s.status == "rate_limited"
    st = home.load_state()
    assert st.last_status == "rate_limited"
    assert abs(datetime.fromisoformat(st.sleep_until).timestamp() - resets) < 2


async def test_process_death_counts_failure_and_forces_new(home: HikidevHome, cfg: Config) -> None:
    runner = FakeRunner([_result("s1")], [], [_result("s3")])  # 두 번째는 result 없음 → 종료 코드 에러 흉내
    orig = runner.run

    async def run(opts):
        async for e in orig(opts):
            yield e
        if len(runner.calls) == 2:
            from kits_runner import Error

            yield Error(message="claude 종료 코드 1", code="exit_nonzero")

    runner.run = run  # type: ignore[method-assign]
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    await orch.heartbeat()
    st = home.load_state()
    assert st.consecutive_failures == 1 and st.last_status == "process_died"
    await orch.heartbeat()
    assert runner.calls[2].resume is None and "프로세스가 죽어서" in runner.calls[2].prompt
    assert home.load_state().consecutive_failures == 0


async def test_daily_cap_sleeps_until_midnight(home: HikidevHome, cfg: Config) -> None:
    cfg.schedule.max_active_hours_per_day = 1
    st = home.load_state()
    st.date = datetime.now().strftime("%Y-%m-%d")
    st.active_seconds = 3600
    home.save_state(st)
    runner = FakeRunner()
    orch = Orchestrator(home, cfg, runner=runner)
    assert await orch.heartbeat() is None
    assert runner.calls == []
    wake = datetime.fromisoformat(home.load_state().sleep_until)
    assert wake.hour == 0 and wake.date() == (datetime.now() + timedelta(days=1)).date()


async def test_run_once_handles_relay_without_discord(home: HikidevHome, cfg: Config) -> None:
    runner = FakeRunner([_result("s1")])
    runner.on_run = lambda o: (home.push_outbox("알림!"), home.add_approval("공개", "이유"))
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.run(once=True)
    assert home.drain_outbox() == []  # relay 가 비웠다 (로그로)
    assert home.load_state().heartbeats == 1


async def test_lost_session_restarts_fresh(home: HikidevHome, cfg: Config) -> None:
    lost = {**_result("s1"), "subtype": "error_during_execution", "is_error": True, "result": "", "num_turns": 0}
    runner = FakeRunner([_result("s1")], [lost], [_result("s2")])
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    s = await orch.heartbeat()
    assert s is not None and s.status == "ok"
    assert runner.calls[1].resume == "s1" and runner.calls[2].resume is None
    assert home.current_session() == "s2"
    st = home.load_state()
    assert st.heartbeats == 2 and st.consecutive_failures == 0


def test_relay_inbox_uses_owner_name(home: HikidevHome) -> None:
    from types import SimpleNamespace

    from hikidev.config import DiscordConfig
    from hikidev.relay import Relay

    r = Relay(home, DiscordConfig(channel_id="1", owner_id="9"), None, owner_name="ithan")
    msg = SimpleNamespace(
        author_name="ithan_alarm", author_id="9", content="hi", created_at="2026-11-03T00:00:00+09:00", id="m1"
    )
    p = r._on_inbox(msg) or home.unread_inbox()[-1]
    assert "from: ithan\n" in p.read_text(encoding="utf-8")
    other = SimpleNamespace(
        author_name="guest", author_id="8", content="yo", created_at="2026-11-03T00:00:01+09:00", id="m2"
    )
    r._on_inbox(other)
    assert any("from: guest\n" in q.read_text(encoding="utf-8") for q in home.unread_inbox())


async def test_orchestrator_error_backs_off_and_forces_new_after_max(home: HikidevHome, cfg: Config) -> None:
    """heartbeat() 자체가 터지면(출력 파싱 실패 등) 곧바로 재시도하지 않고, 연속 실패가 쌓이면 새 채팅."""
    runner = FakeRunner([_result("s1")], [_result("s9")])
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()

    async def boom(*a, **k):
        raise ValueError("Separator is not found, and chunk exceed the limit")

    orig = orch.heartbeat
    orch.heartbeat = boom  # type: ignore[method-assign]
    for _ in range(cfg.session.max_consecutive_failures):
        await orch.run(once=True)
    st = home.load_state()
    assert st.consecutive_failures == cfg.session.max_consecutive_failures
    assert st.last_status == "orchestrator_error"
    assert st.last_heartbeat is not None
    wake = orch.next_wake(st)
    assert (wake - datetime.now().astimezone()).total_seconds() > cfg.schedule.heartbeat_minutes * 60 - 5
    assert home.current_session() == "s1"

    orch.heartbeat = orig  # type: ignore[method-assign]
    await orch.heartbeat()
    assert runner.calls[1].resume is None and "연속 비정상 종료" in runner.calls[1].prompt
    assert home.current_session() == "s9" and home.load_state().consecutive_failures == 0


async def test_output_too_long_forces_new_chat_immediately(home: HikidevHome, cfg: Config) -> None:
    """kits v0.1.2: 출력 한 줄이 한도를 넘으면 Error(output_too_long). 같은 세션은 또 터지니 바로 새 채팅."""
    runner = FakeRunner([_result("s1")], [], [_result("s3")])
    orig = runner.run

    async def run(opts):
        async for e in orig(opts):
            yield e
        if len(runner.calls) == 2:
            from kits_runner import Error

            yield Error(message="출력 한 줄이 64MiB 를 넘었다", code="output_too_long")

    runner.run = run  # type: ignore[method-assign]
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    await orch.heartbeat()
    st = home.load_state()
    assert st.consecutive_failures == 1 and st.last_status == "output_too_long"
    await orch.heartbeat()
    assert runner.calls[2].resume is None and "출력 한 줄이 너무 커서" in runner.calls[2].prompt
    assert home.current_session() == "s3" and home.load_state().consecutive_failures == 0


def test_relay_inbox_passes_attachments(home: HikidevHome) -> None:
    from types import SimpleNamespace

    from hikidev.config import DiscordConfig
    from hikidev.relay import Relay

    r = Relay(home, DiscordConfig(channel_id="1", owner_id="9"), None, owner_name="ithan")
    url = "https://cdn.discordapp.com/attachments/1/2/sketch.jpg"
    r._on_inbox(
        SimpleNamespace(
            author_name="ithan",
            author_id="9",
            content="이거",
            created_at="2026-11-07T00:00:00+09:00",
            id="m1",
            attachments=[url],
        )
    )
    assert f"첨부:\n- {url}\n" in home.unread_inbox()[-1].read_text(encoding="utf-8")
    # attachments 필드가 없는 옛 킷 메시지도 그대로 동작
    r._on_inbox(
        SimpleNamespace(
            author_name="ithan", author_id="9", content="글", created_at="2026-11-07T00:00:01+09:00", id="m2"
        )
    )
    assert "첨부:" not in home.unread_inbox()[-1].read_text(encoding="utf-8")


async def test_multiple_results_sum_turns(home: HikidevHome, cfg: Config) -> None:
    """Monitor 같은 백그라운드 깨움은 한 박동에 result 를 여러 개 낸다. turns 는 합, 비용은 마지막(누적)."""
    r1 = {**_result("s1"), "num_turns": 34, "total_cost_usd": 2.27}
    r2 = {**_result("s1"), "num_turns": 1, "total_cost_usd": 2.29}
    r3 = {**_result("s1"), "num_turns": 4, "total_cost_usd": 2.59}
    runner = FakeRunner([_assistant("a"), r1, _assistant("b"), r2, _assistant("c"), r3])
    orch = Orchestrator(home, cfg, runner=runner)
    s = await orch.heartbeat()
    assert s is not None and s.num_turns == 39 and s.total_cost_usd == 2.59
    end = [
        json.loads(line)
        for line in home.log_path(datetime.now().strftime("%Y-%m-%d")).read_text(encoding="utf-8").splitlines()
    ]
    end = [e for e in end if e.get("event") == "heartbeat_end"][-1]
    assert end["turns"] == 39


async def test_lost_session_needs_no_assistant_reply(home: HikidevHome, cfg: Config) -> None:
    """api_error 로 끝났어도 assistant 응답이 있었으면 '세션 잃음' 이 아니다 — 같은 세션을 유지한다."""
    err = {**_result("s1"), "subtype": "error_during_execution", "is_error": True, "result": "", "num_turns": 0}
    runner = FakeRunner([_result("s1")], [_assistant("일하다가"), err], [_result("s1")])
    orch = Orchestrator(home, cfg, runner=runner)
    await orch.heartbeat()
    s = await orch.heartbeat()
    assert s is not None and s.status == "error"
    assert home.current_session() == "s1" and home.load_state().consecutive_failures == 1
    assert len(runner.calls) == 2  # 새 세션으로 재시도하지 않았다
