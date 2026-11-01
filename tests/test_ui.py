"""웹 UI: 라우트는 TestClient + 임시 home. 실제 home/ 은 건드리지 않는다."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import yaml
from fastapi.testclient import TestClient

from hikidev.home import HikidevHome
from hikidev.ui import data, settings
from hikidev.ui.app import create_app

TZ = ZoneInfo("Asia/Seoul")


@pytest.fixture
def filled(home: HikidevHome) -> HikidevHome:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    home.journal_path(today).write_text(
        f"# {today} (일)\n\n첫날. 방이 텅 비어 있었다.\n\n## 오후\n허프만 들어감.\n", encoding="utf-8"
    )
    proj = home.projects_dir / "squish"
    proj.mkdir()
    (proj / "NOTES.md").write_text(
        "# squish\n\nstatus: active\n압축 알고리즘을 바닥부터.\n\n## 다음 할 일\n- [ ] 길이표 RLE\n- [x] corpus\n- [ ] lazy matching\n",
        encoding="utf-8",
    )
    home.ideas_md.write_text(
        "# ideas\n\n- **tinyvm** — VM\n- **dedupe** — 중복\n\n시작함:\n- ~~**squish** — 압축~~ → projects/squish\n",
        encoding="utf-8",
    )
    home.write_inbox(author="ithan", content="잘 지내?")
    home.add_approval("레포 public 전환", "공개하고 싶어서")
    st = home.load_state()
    st.date = today
    st.active_seconds = 7800
    st.heartbeats = 2
    st.last_context_tokens = 77_328
    st.last_heartbeat = datetime.now(TZ).isoformat(timespec="seconds")
    home.save_state(st)
    records = [
        {"type": "hikidev", "event": "heartbeat_start", "at": f"{today}T20:28:18+09:00", "new_session": True},
        {
            "type": "system",
            "subtype": "init",
            "session_id": "12ad309b-x",
            "tools": ["Bash"],
            "mcp_servers": [{"name": "hikidev"}],
        },
        {
            "type": "assistant",
            "timestamp": f"{today}T11:28:25.802Z",
            "message": {"content": [{"type": "text", "text": "첫 심장박동이다."}]},
        },
        {
            "type": "assistant",
            "timestamp": f"{today}T11:28:27.000Z",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "uv run pytest -q"}},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "mcp__hikidev__notify",
                        "input": {"message": "허프만 붙임"},
                    },
                ]
            },
        },
        {
            "type": "system",
            "subtype": "permission_denied",
            "tool_name": "Write",
            "tool_use_id": "t3",
            "message": "needs approval",
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "t3", "is_error": True, "content": "needs approval"}]
            },
        },
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.06}}},
        },
        {"type": "result", "subtype": "success", "num_turns": 17, "total_cost_usd": 2.9},
        {
            "type": "hikidev",
            "event": "heartbeat_end",
            "at": f"{today}T20:31:44+09:00",
            "status": "ok",
            "turns": 17,
            "elapsed_s": 206,
            "context_tokens": 77328,
            "notion": "https://x",
        },
    ]
    for r in records:
        home.append_log(today, r)
    return home


@pytest.fixture
def client(filled: HikidevHome) -> TestClient:
    return TestClient(create_app(filled))


# ── 데이터 ───────────────────────────────────────────────────
def test_stream_lines_and_stats(filled: HikidevHome) -> None:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    records = data.read_log(filled, today)
    lines = data.stream_lines(records, TZ)
    kinds = [(ln.kind, ln.label) for ln in lines]
    assert ("system", "system") in kinds and ("assistant", "assistant") in kinds
    assert ("tool", "Bash") in kinds and ("hikidev", "hikidev") in kinds
    assert ("denied", "denied") in kinds
    # 거부된 도구의 tool_result 오류는 중복으로 안 나온다
    assert sum(1 for k, _ in kinds if k == "error") == 0
    assert lines[0].at == "20:28:18"
    assert any("heartbeat end · ok · 17 turns · 206s · ctx 77,328" in ln.text for ln in lines)
    assert any(ln.label == "notion" for ln in lines)

    st = data.day_stats(records, TZ)
    assert len(st.beats) == 1 and st.beats[0].status == "ok" and "17턴" in st.beats[0].text
    assert st.turns == 17 and st.elapsed_s == 206 and st.denied == 1 and st.denied_last == "Write"
    assert st.rate_5h == 0.06 and st.notifies == 1 and not st.running


def test_retry_starts_merge_into_one_beat() -> None:
    recs = [
        {"type": "hikidev", "event": "heartbeat_start", "at": "2026-11-01T20:28:00+09:00", "new_session": True},
        {"type": "hikidev", "event": "heartbeat_start", "at": "2026-11-01T20:29:00+09:00", "resume": "abc"},
        {
            "type": "hikidev",
            "event": "heartbeat_end",
            "at": "2026-11-01T20:42:00+09:00",
            "status": "ok",
            "turns": 3,
            "elapsed_s": 10,
        },
        {"type": "hikidev", "event": "heartbeat_start", "at": "2026-11-01T22:13:00+09:00", "resume": "abc"},
    ]
    st = data.day_stats(recs, TZ)
    assert len(st.beats) == 2
    assert st.beats[0].at == "20:28" and st.beats[0].text.startswith("새 세션") and "재시도 1" in st.beats[0].text
    assert st.running
    # 오래 열려 있으면 죽은 것으로 본다
    st2 = data.day_stats(recs, TZ, now=datetime(2026, 11, 2, 1, 0, tzinfo=TZ), stale_minutes=30)
    assert not st2.running and st2.beats[1].status == "error"


def test_projects_ideas_letters(filled: HikidevHome) -> None:
    ps = data.projects(filled, datetime.now(TZ))
    assert ps[0].name == "squish" and ps[0].status == "active"
    assert ps[0].summary.startswith("압축 알고리즘")
    assert ps[0].next_steps == ["길이표 RLE", "lazy matching"]
    ideas = data.ideas(filled)
    assert [i.name for i in ideas] == ["tinyvm", "dedupe", "squish"]
    assert [i.started for i in ideas] == [False, False, True]
    ls = data.letters(filled)
    assert len(ls) == 1 and ls[0].author == "ithan" and ls[0].body == "잘 지내?" and not ls[0].read


def test_overview(filled: HikidevHome, cfg) -> None:
    o = data.overview(filled, cfg)
    assert o.journal_is_today and o.project and o.project.name == "squish"
    assert o.ideas_count == 2 and o.unread == 1 and o.pending == 1
    assert o.mood in ("idle", "sleeping") and o.next_wake is not None
    assert 0 < o.active_ratio < 1 and 0 < o.context_ratio < 1


# ── 라우트 ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/journal",
        "/projects",
        "/ideas",
        "/inbox",
        "/heartbeat",
        "/settings",
        "/partial/room-aside",
        "/partial/stream",
    ],
)
def test_pages_render(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200, r.text[:300]


def test_room_shows_real_data(client: TestClient) -> None:
    html = client.get("/").text
    assert "test hikidev" in html
    assert "첫날. 방이 텅 비어 있었다." in html
    assert "squish" in html and "길이표 RLE" in html
    assert "2h 10m" in html and "77.3k" in html and "200k" in html
    assert "아이디어 2" in html and "받은 편지 1" in html and "승인 대기 1" in html


def test_heartbeat_stream(client: TestClient) -> None:
    html = client.get("/heartbeat").text
    assert 'data-theme="paper"' in html and 'class="stream-wrap"' in html
    assert "heartbeat start · new session" in html
    assert "notify → 허프만 붙임" in html
    assert "RATE LIMIT 5H" in html and "6%" in html


def test_settings_yaml_save_preserves_comments(client: TestClient, filled: HikidevHome) -> None:
    before = filled.config_yaml.read_text(encoding="utf-8")
    assert "#" in before  # 템플릿에 주석이 있다
    values = settings.current_values(filled.config_yaml)
    form = {k: str(v) for k, v in values.items()}
    form["schedule.heartbeat_minutes"] = "45"
    form["session.permission_mode"] = "acceptEdits"
    r = client.post("/settings/yaml", data=form, follow_redirects=False)
    assert r.status_code == 303 and "schedule.heartbeat_minutes" in r.headers["location"]
    after = filled.config_yaml.read_text(encoding="utf-8")
    parsed = yaml.safe_load(after)
    assert parsed["schedule"]["heartbeat_minutes"] == 45
    assert parsed["session"]["permission_mode"] == "acceptEdits"
    # 주석 줄 수는 그대로
    assert sum(1 for ln in before.splitlines() if "#" in ln) == sum(1 for ln in after.splitlines() if "#" in ln)
    # 다른 값은 안 바뀜
    assert parsed["discord"]["channel_id"] == "123"
    log = (filled.dot / "ui-changes.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["file"] == "hikidev.yaml"


def test_settings_yaml_rejects_bad_value(client: TestClient, filled: HikidevHome) -> None:
    before = filled.config_yaml.read_text(encoding="utf-8")
    form = {k: str(v) for k, v in settings.current_values(filled.config_yaml).items()}
    form["schedule.heartbeat_minutes"] = "abc"
    r = client.post("/settings/yaml", data=form)
    assert r.status_code == 200 and "심장박동 주기" in r.text
    assert filled.config_yaml.read_text(encoding="utf-8") == before


def test_replace_values_adds_missing_key() -> None:
    text = "name: x\n\nschedule:\n  heartbeat_minutes: 30   # 주기\n\nsession:\n  max_turns: 60\n"
    out = settings.replace_values(
        text, {("schedule", "heartbeat_minutes"): 15, ("schedule", "rate_limit_fallback_minutes"): 90}
    )
    assert "  heartbeat_minutes: 15   # 주기" in out
    assert "  rate_limit_fallback_minutes: 90" in out
    parsed = yaml.safe_load(out)
    assert parsed["schedule"] == {"heartbeat_minutes": 15, "rate_limit_fallback_minutes": 90}
    assert parsed["session"]["max_turns"] == 60


def test_settings_self_save_logs_change(client: TestClient, filled: HikidevHome) -> None:
    r = client.post("/settings/self", data={"text": "# me\n\n새 취향\n"}, follow_redirects=False)
    assert r.status_code == 303
    assert filled.self_md.read_text(encoding="utf-8") == "# me\n\n새 취향\n"
    log = (filled.dot / "ui-changes.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["file"] == "self.md"
    # journal 에는 아무것도 안 쓴다
    assert not any("self.md" in p.read_text(encoding="utf-8") for p in filled.journal_dir.glob("*.md"))


def test_login_required_when_password_set(filled: HikidevHome) -> None:
    c = TestClient(create_app(filled, password="비밀"), follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    r = c.get("/partial/room-aside", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == "/login"
    r = c.post("/login", data={"password": "틀림", "next": "/"})
    assert "error=1" in r.headers["location"]
    r = c.post("/login", data={"password": "비밀", "next": "/heartbeat"})
    assert r.status_code == 303 and r.headers["location"] == "/heartbeat"
    assert c.get("/").status_code == 200
    c.post("/logout")
    assert c.get("/").status_code == 303


def test_cli_has_ui_subcommand() -> None:
    from hikidev.cli import build_parser

    args = build_parser().parse_args(["ui", "--home", "h", "--port", "9000"])
    assert args.host == "0.0.0.0" and args.port == 9000
