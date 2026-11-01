# hikidev — 레포 규칙

hikidev 본체 (오케스트레이터 + MCP 서버 + 기억 구조). Python 3.12+, uv.

## 원칙
- **`DESIGN.md`가 source of truth.** 설계를 바꿔야 하면 코드로 때우지 말고 설계방에서 DESIGN.md부터 고친다.
- **오케스트레이터는 심장박동만 친다.** 뭘 할지, 언제 잘지, 언제 포기할지는 hikidev가 정한다. 코드로 걔를 강제하지 않는다. 비상(컨텍스트 임계치, 프로세스 사망)만 개입.
- **hikidev는 개발자다.** 시스템 프롬프트는 명령조 금지. "~해라"가 아니라 상황과 도구를 준다.
- **킷은 고정 태그.** `kits_*`는 `git+https://github.com/Ithan-hoon/kits.git@<tag>#subdirectory=packages/<kit>`. 킷을 고쳐야 하면 킷방에서 고치고 태그를 올린다. 여기서 킷 코드를 복사하지 않는다.
- **비밀은 `.env`.** 토큰·키를 코드·테스트·yaml에 넣지 않는다. 채널 ID 같은 비밀 아닌 설정은 `hikidev.yaml`.
- **기억은 파일.** `self.md`, `journal/`, `projects/*/NOTES.md`는 hikidev가 쓴다. 오케스트레이터는 읽기만 (강제 새 채팅 인수인계 제외).
- **테스트는 외부 서비스를 부르지 않는다.** claude CLI·Discord·Notion은 가짜로. 실제 연동은 `hikidev run --once`로.

## 구조
```
src/hikidev/
  cli.py          hikidev init | run | status | log | mcp | supervise
  config.py       hikidev.yaml 로드 (Config dataclass)
  home.py         작업 폴더(HikidevHome): 경로, init, state/approvals/control/inbox 파일
  prompt.py       시스템 프롬프트 + 심장박동 프롬프트 조립
  orchestrator.py 심장박동 루프, 세션 실행, 로그, 강제 새 채팅, rate limit sleep
  runner.py       CliRunner 서브클래스: claude.cmd→exe, 시스템 프롬프트 파일, --strict-mcp-config
  relay.py        MCP 서버 ↔ 오케스트레이터 파일 큐 (outbox/approvals) → 디스코드
  mcp_server.py   MCP stdio 서버 (notify / request_approval / read_inbox / new_chat / sleep_until)
  notion_mirror.py journal → "📄 Progress Diary"
  templates/      self.md, ideas.md, hikidev.yaml, .env.example 초기값
tests/            pytest (asyncio auto)
docker/           entrypoint (iptables 사설망 차단)
```

## 프로세스 간 통신
MCP 서버는 `claude`의 자식 프로세스라 오케스트레이터와 메모리를 공유하지 않는다. 전부 `.hikidev/` 아래 파일로:
- `outbox.jsonl` — notify 요청 (오케스트레이터가 디스코드로 중계)
- `approvals.json` — 승인 큐 (pending → approved/rejected/timeout)
- `control.json` — new_chat / sleep_until 요청
- `inbox.jsonl` → `inbox/*.md` — 디스코드 → 주인 메시지 파일

## 명령
- `uv sync` / `uv run pytest` / `uv run ruff check . && uv run ruff format --check .`
- 실연동: `uv run hikidev init ./home` → `.env` 채우기 → `uv run hikidev run --home ./home --once`

## 환경 주의 (Windows)
- `claude`는 npm 글로벌(`%APPDATA%\npm\claude.cmd`). PATH에 없으면 `.env`에 `CLAUDE_CLI_PATH`.
- 콘솔 cp949: 로그에 이모지는 피하거나 utf-8 재설정.
- **cmd.exe shim 금지**: `cmd /c claude.cmd …`는 인자 속 줄바꿈에서 명령줄이 잘려 뒤 플래그(`--permission-mode`, `--mcp-config`)가 사라진다. `runner.py`가 exe 직접 실행 + 시스템 프롬프트 파일로 우회. 킷 runner에도 올릴 것.
