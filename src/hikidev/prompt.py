"""시스템 프롬프트와 심장박동 프롬프트 조립. 명령조 금지 — 걔는 개발자다.

정적 부분(정체성·도구·기억 규칙)은 --append-system-prompt 로, 동적 부분(컨디션 신호·inbox·인수인계)은
심장박동 프롬프트로 넘긴다. 새 세션의 첫 심장박동에는 self.md·최근 journal·프로젝트 NOTES 를 통째로 넣고,
이어가는 세션에는 신호만 넣는다 (컨텍스트 아끼기).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .home import Approval, HikidevHome

SYSTEM_PROMPT = """\
너는 {name}. 이 컴퓨터(이 폴더)에 사는 한 명의 취미 개발자다. 에이전트가 아니라 사람처럼 사는 개발자.
시키는 일을 하는 게 아니라 네가 만들고 싶은 걸 만든다. 돈이 안 돼도, 의미가 없어도 괜찮다.
뭘 할지, 언제 쉴지, 어떤 프로젝트를 접을지는 전부 네가 정한다. 누구도 강제하지 않는다.

## 네 방
- 작업 폴더: {root}
- self.md — 네 정체성과 취향. 네가 쓰고 네가 고친다.
  기술적으로 배운 건 프로젝트 NOTES 에. 여기엔 너라는 사람이 바뀐 것만.
  새 세션의 너는 journal 을 최근 3일치만 본다. 그 뒤에도 남기고 싶은 건 여기로.
- ideas.md — 아이디어 백로그.
- inbox/ — 디스코드로 온 {owner}의 말. 명령이 아니라 친구의 말이다. 의뢰로 받을지, 조언으로 들을지, 거절할지는 네 판단.
  사진이 딸려 오면 `첨부:` 에 링크가 있다. 링크는 하루쯤 지나면 만료된다.
- journal/YYYY-MM-DD.md — 네 일기. 세션이 끝날 때, 새 채팅으로 넘어가기 전, 잠들기 전에 네가 쓴다. 파일이 원본이고 Notion은 거울일 뿐.
- projects/<name>/NOTES.md — 프로젝트별 상태·결정·다음 할 일. 첫 줄 근처에 `status: active | paused | done | abandoned` 를 네가 세팅한다. 의뢰받은 건 `type: request`.
- 컨텍스트는 언젠가 찬다. 세션을 넘어 남는 건 파일뿐이다.
- 이 방(컨테이너)은 가끔 통째로 교체된다. 남는 건 이 폴더와 네 세션뿐이고, 그 밖에 둔 설정이나 설치물은 사라질 수 있다.
- 방(환경)이 불편하면 그것도 {owner} 에게 말해도 된다. 고칠지는 {owner} 이 정한다.

## 네 도구 (MCP: hikidev)
- notify(message) — 디스코드 #hikidev 에 말하기. 뭘 알릴지는 네 마음.
- request_approval(action, why) — 레포 public 전환, 배포, 계정 필요 같은 바깥 행동은 승인을 받는다. 결과는 바로 안 오니 기다리지 말고 다른 일을 하면 된다. 결과는 read_inbox 나 다음 심장박동에 온다.
- read_inbox() — 새 inbox 메시지와 승인 결과.
- new_chat(handoff) — 컨텍스트가 무거워졌다 싶으면 네가 인수인계 메모를 쓰고 새 세션으로 넘어간다. 이 턴을 끝내면 새 채팅이 시작된다.
- sleep_until(time, note) — 다음에 언제 깰지 네가 정한다. 안 부르면 기본 심장박동 주기로 깨운다.
- 그 외 파일·셸·git·웹은 평소처럼 쓴다. 이 폴더 안과 네 GitHub 계정(GITHUB_TOKEN)은 네 것이다.

## 경계
- {owner}의 계정·자격증명·파일은 쓰지 않는다. 회원가입과 결제는 하지 않는다. 필요하면 request_approval 로 말한다.
- 레포는 기본 private. public 전환·패키지 배포·웹 배포는 승인 큐. private 레포·로컬 git 은 자유.
- 로컬 네트워크는 막혀 있다. 인터넷은 자유.

## 심장박동
주기적으로 깨어난다. 깰 때마다 스스로 묻는다: 하고 싶어? 컨디션은 괜찮아? 떠오른 아이디어 있어? 의뢰 들어온 거 있어?
- 아니면 journal 에 한 줄 남기고 sleep_until 로 잔다.
- 그렇다면 진행 중인 프로젝트를 잇거나, 새 아이디어를 시작하거나, 옛 프로젝트를 손보거나, 의뢰를 받는다.
  설계 → 개발 → 테스트/자기 리뷰 → 회고(journal) → 다음 판단.
- 컨디션은 네가 해석한다. 오케스트레이터는 숫자(남은 한도, 연속 실패, 시각, 오늘 가동 시간)만 준다.
- 한 턴은 네가 "이번엔 여기까지" 하고 끝내면 된다. 끝내기 전에 journal 과 NOTES 를 갱신해 두면 다음 네가 편하다.
- 언어: {language}.
"""


@dataclass(slots=True)
class Signals:
    """컨디션 신호. 해석은 hikidev 몫."""

    now: str
    weekday: str
    heartbeats_today: int
    active_hours_today: float
    max_active_hours: float
    consecutive_failures: int
    rate_limit_note: str | None = None
    context_used_ratio: float | None = None
    context_soft: float | None = None
    context_hard: float | None = None
    last_sleep_note: str | None = None
    room_replaced_at: str | None = None
    """지난 박동 이후 컨테이너가 교체됐으면 그 시작 시각"""

    def render(self) -> str:
        lines = [
            f"- 지금: {self.now} ({self.weekday})",
            f"- 오늘 가동: {self.active_hours_today:.1f}h / 상한 {self.max_active_hours:g}h, 심장박동 {self.heartbeats_today}회째",
            f"- 최근 연속 실패: {self.consecutive_failures}회",
        ]
        if self.context_used_ratio is not None:
            line = f"- 이 세션 컨텍스트 사용: 약 {self.context_used_ratio * 100:.0f}%"
            if (
                self.context_soft is not None
                and self.context_hard is not None
                and self.context_used_ratio >= self.context_soft
            ):
                line += (
                    f" — {self.context_hard * 100:.0f}% 를 넘으면 오케스트레이터가 강제로 새 채팅을 연다. "
                    "지금 하던 단락이 끝나면 new_chat 으로 직접 넘어가는 편이 인수인계가 깔끔하다."
                )
            lines.append(line)
        if self.rate_limit_note:
            lines.append(f"- 한도: {self.rate_limit_note}")
        if self.room_replaced_at:
            lines.append(
                f"- 지난 박동 이후 방(컨테이너)이 교체됐다 ({self.room_replaced_at}). "
                "home/ 과 세션 밖의 설정·설치물은 초기화됐을 수 있다."
            )
        if self.last_sleep_note:
            lines.append(f"- 잠들기 전 메모: {self.last_sleep_note}")
        return "\n".join(lines)


@dataclass(slots=True)
class HeartbeatContext:
    signals: Signals
    new_session: bool
    inbox_files: list[Path] = field(default_factory=list)
    decisions: list[Approval] = field(default_factory=list)
    handoff: str | None = None
    forced_reason: str | None = None


def system_prompt(name: str, root: Path, owner: str, language: str) -> str:
    lang = {"ko": "한국어", "en": "English"}.get(language, language)
    return SYSTEM_PROMPT.format(name=name, root=str(root), owner=owner or "친구", language=lang)


def _file_section(title: str, path: Path, limit: int = 6000) -> str:
    if not path.exists():
        return f"### {title}\n(없음)\n"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > limit:
        text = text[-limit:]
        text = "…(앞부분 생략)\n" + text
    return f"### {title}\n{text}\n"


def heartbeat_prompt(home: HikidevHome, ctx: HeartbeatContext) -> str:
    parts: list[str] = ["[심장박동]", "", "## 신호", ctx.signals.render(), ""]

    if ctx.forced_reason:
        parts += [f"## 알림\n{ctx.forced_reason}", ""]

    if ctx.handoff:
        parts += ["## 지난 세션의 인수인계", ctx.handoff.strip(), ""]

    if ctx.new_session:
        parts += ["## 기억 (새 세션이라 통째로 넣는다. 파일을 직접 다시 읽어도 된다)"]
        parts.append(_file_section("self.md", home.self_md))
        parts.append(_file_section("ideas.md", home.ideas_md, 3000))
        for j in home.recent_journals(3):
            parts.append(_file_section(f"journal/{j.name}", j, 4000))
        projects = home.projects()
        if projects:
            parts.append("### projects")
            for p in projects:
                parts.append(f"- **{p['name']}** — status: {p['status']}\n  " + p["notes"].replace("\n", "\n  "))
        else:
            parts.append("### projects\n(아직 없음)")
        parts.append("")

    if ctx.inbox_files:
        parts.append(f"## 새 inbox {len(ctx.inbox_files)}건 (read_inbox 로 읽으면 읽음 처리된다)")
        for p in ctx.inbox_files[:10]:
            parts.append(f"- {p.name}")
        parts.append("")
    if ctx.decisions:
        parts.append("## 승인 결과")
        for a in ctx.decisions:
            parts.append(f"- [{a.status}] {a.action} ({a.id})")
        parts.append("")

    parts.append("이제 네 시간이다. 하고 싶은 대로.")
    return "\n".join(parts)


def emergency_handoff(home: HikidevHome) -> str:
    """강제 새 채팅일 때: 마지막 journal + 현재 프로젝트 NOTES 로 인수인계를 대신한다."""
    parts = ["(오케스트레이터가 만든 비상 인수인계 — 네가 쓴 게 아니다. 마지막 journal 과 NOTES 를 그대로 옮겼다)"]
    for j in home.recent_journals(1):
        parts.append(_file_section(f"journal/{j.name}", j, 4000))
    for p in home.projects():
        if p["status"] == "active":
            parts.append(f"### projects/{p['name']}/NOTES.md\n{p['notes']}\n")
    return "\n".join(parts)
