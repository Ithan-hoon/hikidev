from __future__ import annotations

import json

from hikidev.home import HikidevHome, State


def test_init_creates_layout(home: HikidevHome) -> None:
    for p in (
        "self.md",
        "ideas.md",
        "inbox",
        "journal",
        "projects",
        ".hikidev/sessions.json",
        ".hikidev/approvals.json",
    ):
        assert (home.root / p).exists(), p
    text = home.self_md.read_text(encoding="utf-8")
    assert "# test hikidev" in text and "테스트" in text
    assert 'channel_id: "123"' in home.config_yaml.read_text(encoding="utf-8")


def test_init_does_not_overwrite(home: HikidevHome) -> None:
    home.self_md.write_text("내가 고친 self", encoding="utf-8")
    made = home.init(name="x")
    assert home.self_md.read_text(encoding="utf-8") == "내가 고친 self"
    assert "self.md" not in made


def test_state_roundtrip(home: HikidevHome) -> None:
    st = home.load_state()
    assert isinstance(st, State) and st.heartbeats == 0
    st.heartbeats = 3
    st.active_seconds = 12.5
    home.save_state(st)
    assert home.load_state().heartbeats == 3
    # 모르는 키는 무시
    home.state_json.write_text(json.dumps({"heartbeats": 1, "future_field": 1}), encoding="utf-8")
    assert home.load_state().heartbeats == 1


def test_approvals(home: HikidevHome) -> None:
    a = home.add_approval("레포 공개", "다 만들었음")
    assert [x.id for x in home.load_approvals()] == [a.id]
    assert home.unseen_decisions() == []
    home.update_approval(a.id, status="approved", by="9")
    seen = home.unseen_decisions(mark=True)
    assert len(seen) == 1 and seen[0].status == "approved"
    assert home.unseen_decisions() == []


def test_outbox(home: HikidevHome) -> None:
    home.push_outbox("hi")
    home.push_outbox("there")
    assert home.drain_outbox() == ["hi", "there"]
    assert home.drain_outbox() == []


def test_control(home: HikidevHome) -> None:
    assert home.read_control() == {}
    home.write_control({"action": "new_chat", "handoff": "메모"})
    home.write_control({"sleep_until": "2026-11-02T09:00:00+09:00"})
    c = home.read_control(clear=True)
    assert c["action"] == "new_chat" and c["sleep_until"].startswith("2026-11-02")
    assert home.read_control() == {}


def test_sessions(home: HikidevHome) -> None:
    assert home.current_session() is None
    home.set_session("s1")
    home.set_session("s2", reason="new_chat")
    assert home.current_session() == "s2"
    data = json.loads(home.sessions_json.read_text(encoding="utf-8"))
    assert data["history"][0]["id"] == "s1" and data["history"][0]["reason"] == "new_chat"


def test_inbox_files(home: HikidevHome) -> None:
    p = home.write_inbox(author="ithan", content="안녕?", at="2026-11-01T10:00:00+09:00", msg_id="abc")
    assert p.name == "20261101T100000-abc.md"
    assert home.unread_inbox() == [p]
    assert "from: ithan" in p.read_text(encoding="utf-8")
    home.mark_inbox_read([p])
    assert home.unread_inbox() == []
    assert (home.inbox_read_dir / p.name).exists()


def test_projects_status(home: HikidevHome) -> None:
    d = home.projects_dir / "toy"
    d.mkdir()
    (d / "NOTES.md").write_text("# toy\nstatus: Paused\n다음: 테스트", encoding="utf-8")
    (home.projects_dir / "nonotes").mkdir()
    ps = home.projects()
    assert [(p["name"], p["status"]) for p in ps] == [("nonotes", "unknown"), ("toy", "paused")]


def test_append_log(home: HikidevHome) -> None:
    home.append_log("2026-11-01", {"type": "x", "n": 1})
    assert home.log_path("2026-11-01").read_text(encoding="utf-8").strip() == '{"type": "x", "n": 1}'
