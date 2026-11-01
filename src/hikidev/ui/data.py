"""home/ 파일 → 화면이 쓰는 값. 전부 읽기 전용.

시각은 hikidev.yaml 의 timezone 으로 맞춘다 (state.json 은 컨테이너가 UTC 로 적고, 호스트 로그는 +09:00 으로 적는다).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import markdown as _markdown

from hikidev.config import Config
from hikidev.home import Approval, HikidevHome, State

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


# ── 시각 ─────────────────────────────────────────────────────
def tz_of(cfg: Config) -> ZoneInfo:
    try:
        return ZoneInfo(cfg.timezone or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


def parse_iso(s: str | None, tz: ZoneInfo) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return t.astimezone(tz)


def hm(t: datetime | None) -> str:
    return t.strftime("%H:%M") if t else "—"


def hms(t: datetime | None) -> str:
    return t.strftime("%H:%M:%S") if t else "—"


def date_label(d: datetime) -> str:
    return f"{d:%Y-%m-%d} ({WEEKDAYS[d.weekday()]})"


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def fmt_k(n: int | float | None) -> str:
    if not n:
        return "0"
    if n >= 1000:
        return f"{int(n) // 1000}k" if int(n) % 1000 == 0 else f"{n / 1000:.1f}k"
    return str(int(n))


# ── 마크다운 ─────────────────────────────────────────────────
def render_md(text: str) -> str:
    return _markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html")


def strip_h1(text: str) -> str:
    lines = text.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).lstrip("\n")
    return text


# ── 일기 ─────────────────────────────────────────────────────
@dataclass(slots=True)
class Journal:
    day: str
    path: Path
    text: str

    @property
    def html(self) -> str:
        return render_md(strip_h1(self.text))

    @property
    def title(self) -> str:
        try:
            return date_label(datetime.strptime(self.day, "%Y-%m-%d"))
        except ValueError:
            return self.day


def journals(home: HikidevHome) -> list[Journal]:
    """최신이 먼저."""
    out = []
    if home.journal_dir.exists():
        for p in sorted(home.journal_dir.glob("*.md"), reverse=True):
            out.append(Journal(day=p.stem, path=p, text=p.read_text(encoding="utf-8", errors="replace")))
    return out


def journal_for(home: HikidevHome, day: str) -> Journal | None:
    p = home.journal_path(day)
    if not p.exists():
        return None
    return Journal(day=day, path=p, text=p.read_text(encoding="utf-8", errors="replace"))


# ── 프로젝트 ─────────────────────────────────────────────────
@dataclass(slots=True)
class Project:
    name: str
    status: str
    text: str
    summary: str
    next_steps: list[str]
    days: int

    @property
    def html(self) -> str:
        return render_md(strip_h1(self.text))


def _project_summary(text: str) -> str:
    """status 줄 다음에 오는 첫 산문 문단."""
    body = strip_h1(text)
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith(("#", "status", "```", "|", "-", "*")):
            # status 줄만 있는 문단이면 그 뒤 줄을 본다
            rest = [ln for ln in para.splitlines() if not re.match(r"\s*status\s*:", ln, re.I)]
            rest = [ln for ln in rest if ln.strip() and not ln.startswith(("#", "```", "|"))]
            if rest:
                return _plain(" ".join(ln.strip() for ln in rest))
            continue
        return _plain(para.replace("\n", " "))
    return ""


def _plain(s: str, n: int = 200) -> str:
    """요약용: 마크다운 강조·코드 표시를 벗긴다."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _next_steps(text: str, limit: int = 2) -> list[str]:
    out = []
    for m in re.finditer(r"^\s*[-*]\s*\[ \]\s*(.+)$", text, re.M):
        item = _plain(m.group(1), 48)
        # "길이표 RLE (0 반복, 직전값 반복) — 설명" → 설명은 뗀다
        out.append(re.split(r"\s[—-]\s", item)[0].strip())
        if len(out) >= limit:
            break
    return out


def projects(home: HikidevHome, now: datetime) -> list[Project]:
    out = []
    if not home.projects_dir.exists():
        return out
    for d in sorted(p for p in home.projects_dir.iterdir() if p.is_dir()):
        notes = d / "NOTES.md"
        text, status = "", "unknown"
        if notes.exists():
            text = notes.read_text(encoding="utf-8", errors="replace")
            if m := re.search(r"status\s*:\s*(active|paused|done|abandoned)", text, re.I):
                status = m.group(1).lower()
        try:
            started = datetime.fromtimestamp(d.stat().st_ctime, tz=now.tzinfo)
            days = max(1, (now.date() - started.date()).days + 1)
        except OSError:
            days = 1
        out.append(
            Project(
                name=d.name,
                status=status,
                text=text,
                summary=_project_summary(text),
                next_steps=_next_steps(text),
                days=days,
            )
        )
    order = {"active": 0, "paused": 1, "unknown": 2, "done": 3, "abandoned": 4}
    out.sort(key=lambda p: order.get(p.status, 9))
    return out


# ── 아이디어 ─────────────────────────────────────────────────
@dataclass(slots=True)
class Idea:
    name: str
    text: str
    started: bool


def ideas(home: HikidevHome) -> list[Idea]:
    if not home.ideas_md.exists():
        return []
    out = []
    for line in home.ideas_md.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if not m:
            continue
        body = m.group(1).strip()
        started = body.startswith("~~")
        clean = body.replace("~~", "")
        nm = re.search(r"\*\*(.+?)\*\*", clean)
        if not nm:
            continue  # 이름 없는 줄은 메모지 아이디어가 아니다
        out.append(Idea(name=nm.group(1), text=clean, started=started))
    return out


def ideas_html(home: HikidevHome) -> str:
    if not home.ideas_md.exists():
        return ""
    return render_md(strip_h1(home.ideas_md.read_text(encoding="utf-8", errors="replace")))


# ── 받은 편지 ────────────────────────────────────────────────
@dataclass(slots=True)
class Letter:
    name: str
    author: str
    at: str
    body: str
    read: bool


def _parse_letter(p: Path, read: bool) -> Letter:
    text = p.read_text(encoding="utf-8", errors="replace")
    author, at, body = "", "", text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        for ln in m.group(1).splitlines():
            if ln.startswith("from:"):
                author = ln[5:].strip()
            elif ln.startswith("at:"):
                at = ln[3:].strip()
        body = m.group(2)
    return Letter(name=p.name, author=author, at=at, body=body.strip(), read=read)


def letters(home: HikidevHome) -> list[Letter]:
    """미읽음 먼저, 각각 최신순."""
    out = []
    if home.inbox_dir.exists():
        out += [_parse_letter(p, False) for p in sorted(home.inbox_dir.glob("*.md"), reverse=True)]
    if home.inbox_read_dir.exists():
        out += [_parse_letter(p, True) for p in sorted(home.inbox_read_dir.glob("*.md"), reverse=True)]
    return out


# ── 로그 (stream-json → 한 줄) ───────────────────────────────
@dataclass(slots=True)
class Line:
    at: str
    kind: str
    """system | hikidev | assistant | tool | denied | error | result | rate | dim"""
    label: str
    text: str


def _short(s: Any, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _tool_summary(name: str, inp: dict[str, Any]) -> str:
    if not isinstance(inp, dict):
        return _short(inp)
    for key in ("command", "file_path", "path", "pattern", "query", "url", "message", "action", "handoff", "time"):
        if key in inp:
            extra = ""
            if key == "action" and inp.get("why"):
                extra = f" — {inp['why']}"
            if key == "time" and inp.get("note"):
                extra = f" — {inp['note']}"
            if name in ("Edit", "Write") and key == "file_path":
                return _short(inp[key], 100)
            return _short(str(inp[key]) + extra)
    return _short(json.dumps(inp, ensure_ascii=False))


def summarize(
    obj: dict[str, Any], tz: ZoneInfo, last_at: str, denied: set[str] | None = None
) -> tuple[list[Line], str]:
    """레코드 하나 → 0..n 줄. 시각이 없는 레코드는 직전 시각을 쓴다.
    denied 는 권한 거부된 tool_use id (오류 결과가 거부 줄과 중복되지 않게)."""
    at = last_at
    denied = set() if denied is None else denied
    for k in ("at", "timestamp"):
        if t := parse_iso(obj.get(k), tz):
            at = hms(t)
            break
    t = obj.get("type")
    out: list[Line] = []

    if t == "hikidev":
        ev = obj.get("event")
        if ev == "heartbeat_start":
            how = "forced new chat" if obj.get("forced") else ("new session" if obj.get("new_session") else "resume")
            sid = (obj.get("resume") or "")[:8]
            out.append(Line(at, "system", "system", f"heartbeat start · {how}" + (f" {sid}" if sid else "")))
        elif ev == "heartbeat_end":
            ctx = obj.get("context_tokens")
            parts = [
                "heartbeat end",
                str(obj.get("status") or ""),
                f"{obj.get('turns') or 0} turns",
                f"{obj.get('elapsed_s') or 0}s",
            ]
            if ctx:
                parts.append(f"ctx {ctx:,}")
            if obj.get("sleep_until"):
                su = parse_iso(obj["sleep_until"], tz)
                parts.append(f"sleep until {hm(su)}")
            out.append(Line(at, "system", "system", " · ".join(parts)))
            if obj.get("notion"):
                out.append(Line(at, "dim", "notion", "mirror journal → Progress Diary"))
        elif ev == "session_lost":
            out.append(Line(at, "system", "system", f"세션 {(obj.get('resume') or '')[:8]} 이어갈 수 없음 → 새 세션"))
        elif ev == "error":
            out.append(Line(at, "error", "error", _short(obj.get("message") or "오케스트레이터 오류")))
        else:
            rest = {k: v for k, v in obj.items() if k not in ("type", "event", "at", "signals") and v is not None}
            out.append(Line(at, "system", "system", f"{ev} {_short(json.dumps(rest, ensure_ascii=False))}"))
        return out, at

    if t == "system":
        sub = obj.get("subtype")
        if sub == "init":
            sid = (obj.get("session_id") or "")[:8]
            mcp = ",".join(s.get("name", "") for s in obj.get("mcp_servers") or [] if isinstance(s, dict))
            text = f"session {sid} init · {len(obj.get('tools') or [])} tools" + (
                f" · mcp:{_short(mcp, 40)}" if mcp else ""
            )
            out.append(Line(at, "system", "system", text))
        elif sub == "permission_denied":
            if obj.get("tool_use_id"):
                denied.add(str(obj["tool_use_id"]))
            out.append(Line(at, "denied", "denied", f"{obj.get('tool_name')} · {_short(obj.get('message'), 110)}"))
        elif sub in ("thinking_tokens", "compact_boundary", "status", "hook_started", "hook_response"):
            pass
        else:
            out.append(Line(at, "dim", "system", f"{sub} {_short(obj.get('message') or '')}"))
        return out, at

    if t == "assistant":
        for b in (obj.get("message") or {}).get("content") or []:
            bt = b.get("type")
            if bt == "text" and b.get("text", "").strip():
                out.append(Line(at, "assistant", "assistant", _short(b["text"], 160)))
            elif bt == "tool_use":
                name = b.get("name") or "tool"
                if name.startswith("mcp__hikidev__") or name.startswith("mcp__"):
                    short = name.split("__")[-1]
                    out.append(
                        Line(at, "hikidev", "hikidev", f"{short} → {_tool_summary(short, b.get('input') or {})}")
                    )
                else:
                    out.append(Line(at, "tool", name, _tool_summary(name, b.get("input") or {})))
        return out, at

    if t == "user":
        for b in (obj.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                if str(b.get("tool_use_id") or "") in denied:
                    continue  # 거부 줄이 이미 있다
                c = b.get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                out.append(Line(at, "error", "error", _short(c, 140)))
        return out, at

    if t == "result":
        sub = obj.get("subtype") or ""
        cost = obj.get("total_cost_usd") or 0
        kind = "result" if sub == "success" else "error"
        text = f"result {sub} · {obj.get('num_turns') or 0} turns · ${cost:.2f}"
        if obj.get("errors"):
            text += " · " + _short(" ".join(map(str, obj["errors"])), 100)
        out.append(Line(at, kind, "result", text))
        return out, at

    if t == "rate_limit_event":
        info = obj.get("rate_limit_info") or {}
        win = (info.get("unifiedWindows") or {}).get("five_hour") or {}
        util = win.get("utilization")
        if util is not None:
            out.append(Line(at, "dim", "rate", f"5h window {util * 100:.0f}% · {info.get('status', '')}"))
        return out, at

    return out, at


def read_log(home: HikidevHome, day: str) -> list[dict[str, Any]]:
    p = home.log_path(day)
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def stream_lines(records: list[dict[str, Any]], tz: ZoneInfo, limit: int = 400) -> list[Line]:
    lines: list[Line] = []
    last = "—"
    denied: set[str] = set()
    for obj in records:
        new, last = summarize(obj, tz, last, denied)
        lines.extend(new)
    return lines[-limit:]


def log_days(home: HikidevHome) -> list[str]:
    if not home.logs_dir.exists():
        return []
    return sorted((p.stem for p in home.logs_dir.glob("????-??-??.jsonl")), reverse=True)


# ── 오늘의 박동 / 컨디션 ──────────────────────────────────────
@dataclass(slots=True)
class Beat:
    at: str
    text: str
    status: str
    """ok | error | running | planned"""
    started: datetime | None = None
    attempts: int = 1


@dataclass(slots=True)
class DayStats:
    beats: list[Beat] = field(default_factory=list)
    turns: int = 0
    elapsed_s: int = 0
    denied: int = 0
    denied_last: str = ""
    rate_5h: float | None = None
    rate_7d: float | None = None
    running: bool = False
    session_restarts: int = 0
    notifies: int = 0


def day_stats(
    records: list[dict[str, Any]], tz: ZoneInfo, *, now: datetime | None = None, stale_minutes: int = 0
) -> DayStats:
    """하루 로그 → 박동 목록과 합계. 끝 기록 없이 다시 start 가 오면 같은 박동의 재시도로 합친다.
    stale_minutes 가 있으면 그보다 오래 열려 있는 박동은 '끝 기록 없음' 으로 닫는다 (프로세스가 죽은 경우)."""
    st = DayStats()
    open_beat: Beat | None = None
    for obj in records:
        t = obj.get("type")
        if t == "hikidev":
            ev = obj.get("event")
            if ev == "heartbeat_start":
                how = "강제 새 채팅" if obj.get("forced") else ("새 세션" if obj.get("new_session") else "이어가기")
                started = parse_iso(obj.get("at"), tz)
                if open_beat is not None:
                    open_beat.attempts += 1
                else:
                    open_beat = Beat(hm(started), how, "running", started=started)
                    st.beats.append(open_beat)
            elif ev == "heartbeat_end":
                if open_beat is None:
                    open_beat = Beat(hm(parse_iso(obj.get("at"), tz)), "", "running")
                    st.beats.append(open_beat)
                turns = int(obj.get("turns") or 0)
                st.turns += turns
                st.elapsed_s += int(obj.get("elapsed_s") or 0)
                status = str(obj.get("status") or "")
                parts = [open_beat.text, f"{turns}턴", f"{int(obj.get('elapsed_s') or 0)}초"]
                if open_beat.attempts > 1:
                    parts.append(f"재시도 {open_beat.attempts - 1}")
                if status != "ok":
                    parts.append(status)
                if obj.get("sleep_until"):
                    parts.append(f"{hm(parse_iso(obj['sleep_until'], tz))}까지 잠")
                open_beat.text = " · ".join(p for p in parts if p)
                open_beat.status = "ok" if status == "ok" else "error"
                open_beat = None
            elif ev == "session_lost":
                st.session_restarts += 1
                if open_beat:
                    open_beat.text += "(이어가기 실패)"
        elif t == "system" and obj.get("subtype") == "permission_denied":
            st.denied += 1
            st.denied_last = f"{obj.get('tool_name')}"
        elif t == "rate_limit_event":
            wins = ((obj.get("rate_limit_info") or {}).get("unifiedWindows")) or {}
            if (fh := wins.get("five_hour")) and fh.get("utilization") is not None:
                st.rate_5h = float(fh["utilization"])
            if (sd := wins.get("seven_day")) and sd.get("utilization") is not None:
                st.rate_7d = float(sd["utilization"])
        elif t == "assistant":
            for b in (obj.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use" and str(b.get("name", "")).endswith("notify"):
                    st.notifies += 1
    if open_beat is not None and stale_minutes and now and open_beat.started:
        if now - open_beat.started > timedelta(minutes=stale_minutes):
            open_beat.status = "error"
            open_beat.text += " · 끝 기록 없음"
            open_beat = None
    st.running = open_beat is not None
    return st


def next_wake(state: State, cfg: Config, now: datetime) -> datetime | None:
    """orchestrator.next_wake 와 같은 규칙 (UI 는 본체를 import 하지 않고 계산만 따라간다)."""
    tz = now.tzinfo
    if su := parse_iso(state.sleep_until, tz):  # type: ignore[arg-type]
        if su > now:
            return su
    if lh := parse_iso(state.last_heartbeat, tz):  # type: ignore[arg-type]
        return max(now, lh + timedelta(minutes=cfg.schedule.heartbeat_minutes))
    return None


@dataclass(slots=True)
class Overview:
    name: str
    now: datetime
    today: str
    date_label: str
    state: State
    stats: DayStats
    mood: str
    """awake | sleeping | idle"""
    mood_text: str
    next_wake: datetime | None
    journal: Journal | None
    journal_is_today: bool
    project: Project | None
    projects: list[Project]
    ideas_count: int
    unread: int
    pending: int
    approvals: list[Approval]
    active_ratio: float
    context_ratio: float
    rate_5h: float | None
    session_id: str | None
    active_cap: float
    context_window: int


def overview(home: HikidevHome, cfg: Config) -> Overview:
    tz = tz_of(cfg)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    state = home.load_state()
    records = read_log(home, today)
    stats = day_stats(records, tz, now=now, stale_minutes=cfg.session.timeout_minutes + 10)
    wake = next_wake(state, cfg, now)

    projs = projects(home, now)
    active = next((p for p in projs if p.status == "active"), projs[0] if projs else None)

    if stats.running:
        mood, text = "awake", "깨어 있음" + (f" · {active.name} 작업 중" if active else "")
    elif state.sleep_until and (su := parse_iso(state.sleep_until, tz)) and su > now:
        mood, text = "sleeping", "자는 중"
        if state.sleep_note:
            text += f" · {_short(state.sleep_note, 36)}"
    else:
        mood, text = "idle", "쉬는 중"
    if wake and not stats.running:
        text += f" · 다음 박동 {hm(wake)}"

    j = journal_for(home, today)
    is_today = j is not None
    if j is None:
        js = journals(home)
        j = js[0] if js else None

    approvals = home.load_approvals()
    pending = sum(1 for a in approvals if a.status == "pending")
    cap_s = cfg.schedule.max_active_hours_per_day * 3600
    active_seconds = state.active_seconds if state.date == today else 0
    return Overview(
        name=cfg.name,
        now=now,
        today=today,
        date_label=date_label(now),
        state=state,
        stats=stats,
        mood=mood,
        mood_text=text,
        next_wake=wake,
        journal=j,
        journal_is_today=is_today,
        project=active,
        projects=projs,
        ideas_count=sum(1 for i in ideas(home) if not i.started),
        unread=len(home.unread_inbox()),
        pending=pending,
        approvals=approvals,
        active_ratio=min(1.0, active_seconds / cap_s) if cap_s else 0,
        context_ratio=min(1.0, state.last_context_tokens / cfg.session.context_window_tokens)
        if cfg.session.context_window_tokens
        else 0,
        rate_5h=stats.rate_5h,
        session_id=home.current_session(),
        active_cap=cfg.schedule.max_active_hours_per_day,
        context_window=cfg.session.context_window_tokens,
    )
