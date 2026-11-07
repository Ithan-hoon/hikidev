"""작업 폴더(HikidevHome). 경로, init, 그리고 `.hikidev/` 아래 상태 파일 전부.

파일 레이아웃은 DESIGN.md 8절. MCP 서버와 오케스트레이터는 다른 프로세스라 여기 파일로만 대화한다.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

TEMPLATES = resources.files("hikidev") / "templates"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass(slots=True)
class State:
    """오케스트레이터 상태 (.hikidev/state.json). 날짜가 바뀌면 active_seconds 가 0으로."""

    date: str = ""
    active_seconds: float = 0
    consecutive_failures: int = 0
    heartbeats: int = 0
    last_heartbeat: str | None = None
    last_status: str | None = None
    last_context_tokens: int = 0
    sleep_until: str | None = None
    sleep_note: str | None = None
    session_turns: int = 0


@dataclass(slots=True)
class Approval:
    id: str
    action: str
    why: str
    status: str = "pending"
    """pending | approved | rejected | timeout"""
    requested_at: str = field(default_factory=now_iso)
    decided_at: str | None = None
    by: str | None = None
    seen: bool = False
    """hikidev 가 결과를 읽었는지"""


class HikidevHome:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.self_md = self.root / "self.md"
        self.ideas_md = self.root / "ideas.md"
        self.inbox_dir = self.root / "inbox"
        self.inbox_read_dir = self.inbox_dir / "read"
        self.journal_dir = self.root / "journal"
        self.projects_dir = self.root / "projects"
        self.dot = self.root / ".hikidev"
        self.sessions_json = self.dot / "sessions.json"
        self.approvals_json = self.dot / "approvals.json"
        self.logs_dir = self.dot / "logs"
        self.state_json = self.dot / "state.json"
        self.outbox_jsonl = self.dot / "outbox.jsonl"
        self.control_json = self.dot / "control.json"
        self.inbox_jsonl = self.dot / "inbox.jsonl"
        self.mcp_json = self.dot / "mcp.json"
        self.notion_state_json = self.dot / "notion-mirror.json"
        self.notion_map_json = self.dot / "notion-map.json"
        """journal 상대 경로 → Progress Diary 페이지 ID (호스트/컨테이너 공통)"""
        self.config_yaml = self.root / "hikidev.yaml"

    # ── init ─────────────────────────────────────────────────
    def init(self, *, name: str = "hikidev", values: dict[str, str] | None = None, force: bool = False) -> list[str]:
        """폴더와 초기 파일을 만든다. 이미 있는 파일은 force 가 아니면 건드리지 않는다. 만든 경로 목록 반환."""
        made: list[str] = []
        for d in (self.inbox_dir, self.inbox_read_dir, self.journal_dir, self.projects_dir, self.dot, self.logs_dir):
            if not d.exists():
                d.mkdir(parents=True)
                made.append(str(d.relative_to(self.root)) + "/")
        subs = {
            "name": name,
            "interests": "(아직 모름 — 해보면서 알아갈 것)",
            "stack": "Python",
            "traits": "(아직 모름)",
            "license": "MIT",
            "language": "한국어",
            "channel_id": "",
            "owner_id": "",
            "owner": "친구",
        }
        subs.update(values or {})

        def render(template: str) -> str:
            text = (TEMPLATES / template).read_text(encoding="utf-8")
            for k, v in subs.items():
                text = text.replace("{" + k + "}", v)
            return text

        files = {
            self.self_md: render("self.md"),
            self.ideas_md: render("ideas.md"),
            self.config_yaml: render("hikidev.yaml"),
            self.sessions_json: "{}\n",
            self.approvals_json: "[]\n",
            self.state_json: json.dumps(asdict(State()), ensure_ascii=False, indent=2) + "\n",
            self.dot / ".gitignore": "*\n",
        }
        for path, content in files.items():
            if path.exists() and not force:
                continue
            path.write_text(content, encoding="utf-8")
            made.append(str(path.relative_to(self.root)))
        return made

    def is_initialized(self) -> bool:
        return self.self_md.exists() and self.dot.exists()

    # ── state ────────────────────────────────────────────────
    def load_state(self) -> State:
        data = _read_json(self.state_json, {})
        known = {k: v for k, v in data.items() if k in State.__dataclass_fields__}
        return State(**known)

    def save_state(self, state: State) -> None:
        _write_json(self.state_json, asdict(state))

    # ── approvals ────────────────────────────────────────────
    def load_approvals(self) -> list[Approval]:
        out = []
        for d in _read_json(self.approvals_json, []):
            if isinstance(d, dict) and "id" in d:
                out.append(Approval(**{k: v for k, v in d.items() if k in Approval.__dataclass_fields__}))
        return out

    def save_approvals(self, items: list[Approval]) -> None:
        _write_json(self.approvals_json, [asdict(a) for a in items])

    def add_approval(self, action: str, why: str) -> Approval:
        items = self.load_approvals()
        a = Approval(id=uuid.uuid4().hex[:8], action=action, why=why)
        items.append(a)
        self.save_approvals(items)
        return a

    def update_approval(self, approval_id: str, **changes: Any) -> Approval | None:
        items = self.load_approvals()
        for a in items:
            if a.id == approval_id:
                for k, v in changes.items():
                    setattr(a, k, v)
                self.save_approvals(items)
                return a
        return None

    def unseen_decisions(self, *, mark: bool = True) -> list[Approval]:
        """결정됐는데 hikidev 가 아직 못 본 승인들."""
        items = self.load_approvals()
        out = [a for a in items if a.status != "pending" and not a.seen]
        if mark and out:
            for a in out:
                a.seen = True
            self.save_approvals(items)
        return out

    # ── outbox (MCP → 오케스트레이터 → 디스코드) ─────────────
    def push_outbox(self, message: str) -> None:
        self.dot.mkdir(parents=True, exist_ok=True)
        with self.outbox_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_iso(), "message": message}, ensure_ascii=False) + "\n")

    def drain_outbox(self) -> list[str]:
        if not self.outbox_jsonl.exists():
            return []
        lines = self.outbox_jsonl.read_text(encoding="utf-8").splitlines()
        self.outbox_jsonl.write_text("", encoding="utf-8")
        out = []
        for line in lines:
            try:
                out.append(json.loads(line)["message"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return out

    # ── control (new_chat / sleep_until) ─────────────────────
    def write_control(self, data: dict[str, Any]) -> None:
        current = _read_json(self.control_json, {})
        current.update(data)
        current["at"] = now_iso()
        _write_json(self.control_json, current)

    def read_control(self, *, clear: bool = False) -> dict[str, Any]:
        data = _read_json(self.control_json, {})
        if clear and self.control_json.exists():
            self.control_json.unlink()
        return data if isinstance(data, dict) else {}

    # ── sessions ─────────────────────────────────────────────
    def current_session(self) -> str | None:
        return _read_json(self.sessions_json, {}).get("current")

    def set_session(self, session_id: str | None, *, reason: str = "") -> None:
        data = _read_json(self.sessions_json, {})
        history = data.get("history", [])
        if data.get("current") and data.get("current") != session_id:
            history.append({"id": data["current"], "ended_at": now_iso(), "reason": reason})
        data["current"] = session_id
        data["history"] = history[-50:]
        _write_json(self.sessions_json, data)

    # ── inbox (디스코드 → 파일) ───────────────────────────────
    def write_inbox(
        self,
        *,
        author: str,
        content: str,
        at: str | None = None,
        msg_id: str | None = None,
        attachments: list[str] | None = None,
    ) -> Path:
        """디스코드 메시지 한 건을 inbox/*.md 로. 첨부(사진 등)는 URL 만 `첨부:` 섹션에 적는다 — 받을지는 걔 판단."""
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        at = at or now_iso()
        stamp = re.sub(r"[^0-9T]", "", at)[:15]
        mid = msg_id or uuid.uuid4().hex[:6]
        path = self.inbox_dir / f"{stamp}-{mid}.md"
        body = f"---\nfrom: {author}\nat: {at}\n---\n{content}\n"
        if attachments:
            body += "\n첨부:\n" + "".join(f"- {u}\n" for u in attachments)
        path.write_text(body, encoding="utf-8")
        return path

    def unread_inbox(self) -> list[Path]:
        if not self.inbox_dir.exists():
            return []
        return sorted(p for p in self.inbox_dir.glob("*.md") if p.is_file())

    def mark_inbox_read(self, paths: list[Path]) -> None:
        self.inbox_read_dir.mkdir(parents=True, exist_ok=True)
        for p in paths:
            os.replace(p, self.inbox_read_dir / p.name)

    # ── journal / projects (읽기 전용) ───────────────────────
    def journal_path(self, day: str) -> Path:
        return self.journal_dir / f"{day}.md"

    def recent_journals(self, n: int = 3) -> list[Path]:
        if not self.journal_dir.exists():
            return []
        return sorted(self.journal_dir.glob("*.md"))[-n:]

    def projects(self) -> list[dict[str, str]]:
        """projects/*/NOTES.md 의 status 와 첫 줄들."""
        out = []
        if not self.projects_dir.exists():
            return out
        for d in sorted(p for p in self.projects_dir.iterdir() if p.is_dir()):
            notes = d / "NOTES.md"
            status, head = "unknown", ""
            if notes.exists():
                text = notes.read_text(encoding="utf-8", errors="replace")
                if m := re.search(r"status\s*:\s*(active|paused|done|abandoned)", text, re.I):
                    status = m.group(1).lower()
                head = text.strip()[:600]
            out.append({"name": d.name, "status": status, "notes": head})
        return out

    def log_path(self, day: str) -> Path:
        return self.logs_dir / f"{day}.jsonl"

    def append_log(self, day: str, obj: Any) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path(day).open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
