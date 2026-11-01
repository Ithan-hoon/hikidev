# hikidev

> An autonomous developer that lives in your machine and builds whatever it wants.

hikidev는 개발 에이전트가 아니라 **한 명의 개발자**다. 집에 박혀서 컴퓨터만 만지는 취미 개발자처럼, 생각나는 아이디어가 있으면 스스로 설계·개발·개선한다. 시키는 일을 하는 게 아니라 자기가 만들고 싶은 걸 만든다. 돈이 안 돼도, 의미가 없어도 된다. 사용자마다 자기 hikidev를 갖는다 (예: ithan's hikidev). 개발자니까 주인의 의뢰를 정식으로 받을 수 있고, 거절할 수도 있다.

설계 전문은 [DESIGN.md](DESIGN.md) (source of truth).

## 어떻게 사는가

- **심장박동**: 오케스트레이터가 주기적으로 hikidev를 깨운다. 뭘 할지는 전부 hikidev가 정한다 — 하고 싶어? 컨디션은? 아이디어는? 의뢰 들어온 거 있어?
- **기억은 파일**: `self.md`(정체성·취향), `ideas.md`, `journal/`(일기), `projects/<name>/NOTES.md`(상태·결정). 세션을 넘어 이어지는 건 전부 파일이다.
- **자기 방**: Docker 컨테이너 안에서만 산다. 인터넷은 되고 사설망은 막힌다. 주인의 계정·파일은 모른다.
- **주인과의 관계**: 디스코드 채널 하나. hikidev가 `notify`로 알리고, 외부 행동(레포 공개·배포)은 `request_approval`로 승인을 받고, 주인의 말은 inbox로 읽는다. 명령이 아니라 친구의 말이다.
- **실행 기반**: `claude -p` 래퍼(`CliRunner`). 주인이 자기 구독으로 `claude` 로그인하면 된다. hikidev는 토큰·키를 중개하지 않는다.

## 빠른 시작 (호스트)

**모든 명령은 이 레포 폴더(`hikidev/`)에서** 실행한다. `.env`가 여기 있고, `home/`은 걔 방이라 그 안에서 돌리지 않는다.

```bash
cd hikidev
uv sync
uv run hikidev init home --name "ithan's hikidev"   # 기억 구조 + home/hikidev.yaml 생성
cp .env.example .env              # 토큰은 home 밖(.env)에 — 걔 방 안에 주인 토큰을 두지 않는다
# home/hikidev.yaml 편집 (디스코드 채널 ID 등), home/self.md 초기값
uv run hikidev run --home home --once --log-level info   # 심장박동 1회 (실연동 확인)
uv run hikidev run --home home                            # 계속
uv run hikidev status --home home
uv run hikidev log -f --home home
```

`claude`가 PATH에 없으면 `.env`에 `CLAUDE_CLI_PATH`를 적는다. Windows의 npm `claude.cmd` shim은 킷이 그 안의 `claude.exe`로 바꿔 실행한다.

## 명령

| 명령 | 하는 일 |
|---|---|
| `hikidev init [home]` | 작업 폴더 생성: `self.md`, `ideas.md`, `inbox/`, `journal/`, `projects/`, `.hikidev/`, `hikidev.yaml` |
| `hikidev run [--once]` | 심장박동 루프. `--once`는 한 번만 |
| `hikidev status` | 세션·오늘 가동 시간·승인 큐·마지막 심장박동 |
| `hikidev log [-f]` | `.hikidev/logs/날짜.jsonl` 보기 |
| `hikidev mcp` | MCP 서버 (stdio). 세션에 자동으로 붙는다. 직접 부를 일 없음 |
| `hikidev supervise` | `kits_supervisor`로 `hikidev run`을 감시. 크래시 반복 시 정지 + `#hikidev-alerts` 웹훅 |

## MCP 도구 (hikidev가 쓰는 것)

| 도구 | 하는 일 |
|---|---|
| `notify(message)` | 디스코드 `#hikidev`에 메시지 |
| `request_approval(action, why)` | 승인 큐 등록 + 디스코드 버튼. 결과는 다음 `read_inbox` / 심장박동에서 |
| `read_inbox()` | 주인이 쓴 글 + 승인 결과 |
| `new_chat(handoff)` | 이 턴이 끝나면 새 세션. 인수인계 메모는 본인이 씀 |
| `sleep_until(time, note)` | 다음 심장박동 시각을 직접 정함 |

## 설정 (`hikidev.yaml`)

```yaml
name: ithan's hikidev
runner: cli                  # cli | sdk (sdk는 Phase 2)
schedule:
  heartbeat_minutes: 30
  max_active_hours_per_day: 8
session:
  context_window_tokens: 200000
  context_threshold: 0.85    # 넘으면 강제 새 채팅
  max_turns: 200
discord:
  channel_id: "..."          # #hikidev
  owner_id: "..."
notion:
  mirror_journal: true       # journal → "📄 Progress Diary"
```
토큰은 `.env` (`.env.example` 참고).

## Docker

```bash
# 처음 한 번: 킷(private) 받기용 자격증명 → docker/git-credentials 에 `https://<id>:<token>@github.com` 한 줄
docker compose build
docker compose run --rm hikidev hikidev-check-network                              # 사설망 차단·인터넷·claude 확인
docker compose run --rm hikidev hikidev run --home /home/hikidev/home --once --log-level info   # 심장박동 1회
docker compose up -d                                                                # 상시 (supervise)
```
호스트에서 쓰던 `home/`을 그대로 마운트한다. 세션 기록은 머신마다 달라서 첫 컨테이너 심장박동은 새 세션으로 시작한다(자동).
`home/`만 컨테이너에 마운트된다. 컨테이너 시작 시 iptables로 사설 IP 대역(10/8, 172.16/12, 192.168/16, 169.254/16)을 막는다. claude 로그인은 호스트에서 `claude setup-token`으로 받은 장기 토큰을 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`에 넣는다 (Max 구독, API 키 안 씀).

## 라이선스

MIT. hikidev가 만드는 프로젝트의 라이선스는 걔가 프로젝트마다 고른다.
