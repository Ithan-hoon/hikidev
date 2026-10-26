# hikidev 설계 문서

> An autonomous developer that lives in your machine and builds whatever it wants.

- 상태: 초안 v0.1 (2026-10-26)
- 이 문서가 source of truth. 다른 방(킷방·본체방·운영방)에서 설계를 바꿔야 하면 설계방으로 가져와서 여기부터 고친다.
- 진행 기록: Notion "hikidev 진행일지" DB

---

## 1. 컨셉

hikidev는 개발 에이전트가 아니라 **한 명의 개발자**다. 집에 박혀서 컴퓨터만 만지는 취미 개발자처럼, 생각나는 아이디어가 있으면 스스로 설계·개발·개선한다.

- **완전한 자유**: 시키는 일을 하는 게 아니라 자기가 만들고 싶은 걸 만든다.
- **취미 개발자**: 돈이 안 돼도, 의미가 없어도 된다. (돈 되면 더 좋음)
- **각자의 hikidev**: 사용자마다 자기 hikidev를 갖는다. (예: ithan's hikidev)
- **개발자니까**: 주인의 의뢰를 정식으로 받을 수 있고, 거절할 수도 있다.

### 하지 않는 것
- 단순 작업 루프(아이디어 → 개발 → 반복)로 만들지 않는다. 뭘 할지는 hikidev가 정한다.
- 주인의 자격증명·계정·파일을 쓰지 않는다. hikidev는 자기 계정과 자기 폴더만 가진다.

---

## 2. 전체 구조

```
┌─ supervisor (작고 불변, pm2/작업 스케줄러) ─────────────────────┐
│  오케스트레이터 재시작, 연속 크래시 시 정지 + 디스코드 웹훅        │
│                                                                   │
│  ┌─ orchestrator (hikidev 본체, Node/TS) ──────────────────────┐ │
│  │  · 심장박동: 주기적으로 hikidev를 깨움                        │ │
│  │  · Runner: claude -p | Agent SDK  (설정으로 선택)             │ │
│  │  · MCP 서버: notify / request_approval / read_inbox /         │ │
│  │              new_chat / sleep_until                           │ │
│  │  · 세션·로그·승인 큐·inbox 상태 관리                           │ │
│  │                                                               │ │
│  │  ┌─ Docker 컨테이너 (hikidev의 방) ──────────────────────┐   │ │
│  │  │  Claude 세션 실행, 작업 폴더, 킷(읽기 전용 릴리즈)       │   │ │
│  │  │  인터넷 O, 사설망 X                                     │   │ │
│  │  └────────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
          ↕ 디스코드 채널 (notify / inbox / 승인 버튼)
        주인 (ithan)
```

세 층의 역할:

| 층 | 바뀌는 빈도 | 누가 고치나 |
|---|---|---|
| supervisor | 거의 안 바뀜 | 주인만 |
| orchestrator | 가끔 | 주인. (2단계부터 hikidev가 PR → 승인) |
| 컨테이너 안 작업물 | 매일 | hikidev |

---

## 3. 실행 기반 (Runner)

`Runner` 인터페이스 하나에 구현 둘. 둘 다 같은 이벤트 스트림(텍스트·툴 호출·비용·세션 ID)을 뱉는다.

| | `CliRunner` | `SdkRunner` |
|---|---|---|
| 방식 | `claude -p --resume <id> --output-format stream-json` 자식 프로세스 | Claude Agent SDK (TypeScript) |
| 인증 | 사용자가 `claude` 로그인 (Max 구독 가능) | 사용자 본인 API 키 (`ANTHROPIC_API_KEY`) |
| 한도 | 설정 없음. rate limit 에러 → 리셋 시각까지 잠 | 설정에서 일일 예산(USD), 초과 시 sleep/stop |
| 기본값 | ✅ | |

### 근거 (2026-10-26 공식 문서 확인)
- Agent SDK: "Anthropic does not allow third party developers to offer claude.ai login ... including agents built on the Claude Agent SDK. Use the API key authentication methods instead."
- CLI: 수정하지 않은 Claude Code 바이너리에 사용자가 자기 구독으로 로그인하는 것은 허용.
- 단 "Pro/Max 한도는 ordinary, individual usage를 가정"이라는 문구가 있음 → 24시간 상시 가동은 회색지대. 하루 가동 시간 자체 상한을 둔다 (설정 `max_active_hours_per_day`).
- hikidev는 **토큰·키를 중개하지 않는다.** 로그인은 사용자 몫. 로그인 안 돼 있으면 안내만 한다.

### 설정 예시
```yaml
runner: cli            # cli | sdk
budget:                # sdk 일 때만 유효
  daily_usd: 10
  on_exceed: sleep     # sleep | stop
schedule:
  heartbeat_minutes: 30
  max_active_hours_per_day: 8
```

---

## 4. 샌드박스

"내 컴퓨터에 사는 개발자"에서 제일 위험한 부분. 원칙은 **hikidev는 자기 방 밖을 모른다.**

| 항목 | 결정 |
|---|---|
| 격리 | Docker 컨테이너 (Windows: Docker Desktop / WSL2) |
| 파일 | 호스트의 `hikidev/` 작업 폴더만 마운트. 개인 파일·시스템은 보이지 않음 |
| 네트워크 | 인터넷 허용. **사설 IP 대역 차단** (10/8, 172.16/12, 192.168/16, 169.254/16) → 로컬 네트워크의 다른 PC 접근 불가 |
| 계정 | 회원가입 권한 없음. 필요한 서비스 계정은 주인이 **hikidev 전용으로** 만들어 자격증명을 컨테이너 환경변수로 주입 |
| 킷 | 컨테이너 이미지 빌드 시 고정 릴리즈 버전으로 설치 (읽기 전용) |

계정이 더 필요하면 hikidev가 `request_approval("github 계정 필요해, 이유: …")`로 요청 → 주인이 만들어서 주입.

---

## 5. 외부 행동의 경계

| 행동 | 정책 |
|---|---|
| 컨테이너 안 파일 작업, 로컬 git | 자율 |
| 인터넷 참조(검색·문서·패키지 설치) | 자율 |
| 자기 GitHub 계정에 private 레포 생성·push | 자율 |
| 레포 **public 전환** | 승인 큐 |
| npm/PyPI 배포, 웹 배포 | 승인 큐 |
| 킷 레포 main 반영 | 승인 큐 (PR) |
| 돈 쓰기, 결제 | 금지 |
| 회원가입, 주인 계정·자격증명 사용 | 금지 |
| 로컬 네트워크 접근 | 금지 (네트워크 레벨 차단) |

신뢰가 쌓이면 설정으로 완화한다 (예: `publish_repos: auto`).

### Git
- hikidev 전용 GitHub **machine account** (GitHub 약관상 개인당 무료 개인계정 1 + machine account 1 허용).
- 걔 토큰으론 걔 레포만 보이므로 블랙리스트가 필요 없다. 주인 레포는 물리적으로 접근 불가.
- 기본 private. public은 승인 큐 (비밀 커밋 사고 방지 + 초반 신뢰 쌓기).
- push 전 secret-scan 훅을 둔다.

---

## 6. 삶의 사이클

오케스트레이터는 **심장박동**만 친다. 뭘 할지는 전부 hikidev가 정한다.

```
[심장박동]
   │
   ▼
깨어남 ── self.md / journal / 프로젝트 상태 / inbox 읽기
   │
   ▼
자문: 하고 싶어? 컨디션 괜찮아? 떠오른 아이디어 있어? 의뢰 들어온 거 있어?
   │
   ├─ no  → journal 한 줄 + sleep_until(…)
   │
   └─ yes → 진행 중 프로젝트 계속 | 새 아이디어 시작 | 옛 프로젝트 개선 | 의뢰 수락
               │
               ▼
          설계 → 개발 → 테스트/자기 리뷰 → 회고(journal) → 다음 판단
               │
          프로젝트 상태를 본인이 세팅: active | paused | done | abandoned
```

- **컨디션**은 랜덤이 아니라 실제 신호에서 나온다: 남은 한도(rate limit 상태 / 예산 잔량), 최근 연속 실패 횟수, 현재 시각, 오늘 가동 시간. 오케스트레이터가 이 수치를 프롬프트에 넣어주고 해석은 hikidev가 한다.
- 프로젝트를 언제 포기할지, 옛 프로젝트로 언제 돌아갈지도 hikidev 판단. 오케스트레이터는 강제하지 않는다.
- 한도에 걸리면 "오늘은 머리가 안 돌아가네" → 리셋 시각까지 잠.

---

## 7. 정체성과 취향

- `self.md`: 관심 분야, 좋아하는 스택, 성향, 프로젝트 라이선스 취향 등. **초기값만 주인이 주고, 이후엔 hikidev가 직접 고쳐 쓴다.**
- 취향은 경험으로 자란다. 회고 때 self.md를 업데이트할지 본인이 정한다.
- **의뢰**: 주인이 inbox로 정식 요청 가능. hikidev는 수락/거절/보류할 수 있다. 수락한 의뢰는 일반 프로젝트와 같은 흐름으로 가되 `type: request` 태그.
- 주인의 inbox 메시지는 명령이 아니라 "친구의 말"이다. 의뢰로 받을지 조언으로 받을지는 hikidev가 정한다.

---

## 8. 기억

컨텍스트는 언젠가 꽉 찬다. 세션을 넘어 이어지는 건 전부 **파일**이다.

```
hikidev/                      ← 호스트에 마운트되는 작업 폴더
├── self.md                   정체성·취향 (hikidev가 씀)
├── ideas.md                  아이디어 백로그
├── inbox/                    주인 → hikidev 메시지 (디스코드 봇이 적음)
├── journal/
│   └── 2026-10-26.md         날짜별 일기
├── projects/
│   └── <name>/
│       ├── NOTES.md          상태·결정·다음 할 일 (status: active|paused|done|abandoned)
│       └── ...               실제 코드
└── .hikidev/
    ├── sessions.json         세션 ID 기록
    ├── approvals.json        승인 큐
    └── logs/*.jsonl          stream-json 로그
```

- journal은 hikidev 본인이 쓴다. 세션 끝·새 채팅 전·잠들기 전.
- Notion 미러: `notion` 킷이 journal을 Notion **"📄 Progress Diary"** DB(My Atelier > HikiDev)로 복사한다. **파일이 원본, 노션은 거울.** (컨테이너에서 노션이 안 붙어도 일기는 남는다.)

---

## 9. 세션 관리

세션 관리도 hikidev 몫이다. 오케스트레이터는 도구를 주고, 비상시에만 개입한다.

| 도구 | 하는 일 |
|---|---|
| `new_chat(handoff: string)` | 새 세션 시작. 인수인계 메모는 hikidev가 직접 쓴다 |
| `clear()` | 현재 세션 버리고 새로 시작 |
| `resume(session_id)` | 이전 세션 이어가기 |
| `sleep_until(time, note)` | 다음 심장박동까지 잠 |

비상 개입 (오케스트레이터가 강제 새 채팅):
- 컨텍스트 사용량이 임계치(예: 85%)를 넘었는데 hikidev가 new_chat을 안 했을 때
- 세션 프로세스가 죽었을 때
- 이때 인수인계는 마지막 journal + 현재 프로젝트 NOTES.md로 대체한다.

---

## 10. 주인과의 관계: 관찰·개입·승인

오케스트레이터 자체가 **MCP 서버**가 되어 세션에 붙는다.

| 도구 | 누가 | 하는 일 |
|---|---|---|
| `notify(message)` | hikidev | 디스코드 채널에 메시지. 뭘 알릴지는 본인이 정함 |
| `request_approval(action, why)` | hikidev | 승인 큐 등록 + 디스코드 버튼. 승인 전까진 다른 일 함 |
| `read_inbox()` | hikidev | 주인이 디스코드에 쓴 글 읽기 |
| Stop 훅 | 시스템 | 턴 끝날 때 새 inbox 메시지 있으면 알려줌 |

- 디스코드: 기존 봇을 공유, **hikidev용 채널 1개** 배정. `discord` 킷이 채널별 라우팅을 맡는다 (봇 프로세스 하나에 AI마다 채널).
- 관찰: stream-json → `logs/날짜.jsonl`. `hikidev log -f`, `hikidev status`.
- 대시보드는 안 만든다. 걔가 심심하면 직접 만들겠지.

---

## 11. 장애 대응

| 층 | 장애 | 대응 |
|---|---|---|
| 에이전트(세션) | 같은 에러 반복, 무한 루프 | 오케스트레이터가 감지(동일 에러 3회 / 턴 수 초과) → 프로젝트 paused + journal + notify. 장기적으로 DoD로 개선 |
| 에이전트 | rate limit | 리셋 시각까지 sleep |
| 에이전트 | 프로세스 죽음 | 강제 새 채팅 (9절) |
| 오케스트레이터 | 크래시 | supervisor가 재시작. 10분 내 3회면 정지 + 디스코드 **웹훅**(오케스트레이터 없이도 보내야 하므로) → 주인 개입 |
| 오케스트레이터 | 자기 수정 | **MVP 제외.** 2단계: hikidev가 PR → 승인 → supervisor가 교체, N분 내 죽으면 이전 빌드로 롤백 (blue-green) |

supervisor는 작고 절대 안 바뀌는 프로세스. pm2 또는 Windows 작업 스케줄러.

---

## 12. 킷 (공통 모듈) 전략

본체보다 **킷을 먼저** 만든다. 다른 AI 프로젝트에서도 쓰는 PC 공통 모듈.

| 킷 | 역할 | 비고 |
|---|---|---|
| `runner` | `claude -p` / Agent SDK 래퍼, stream-json 파싱, 세션 resume | 재사용 가치 최고 |
| `discord` | 봇 프로세스 1개, 채널별 notify / inbox / 승인 버튼 | 기존 모듈을 서비스 형태로 |
| `supervisor` | 프로세스 감시·재시작·웹훅 | |
| `notion` | journal → Notion DB 미러 | 진행일지 DB 구조 공통 |
| `config` / `logger` | 자잘한 공통 | |

규칙:
- **MVP에 필요한 킷만.** 킷 만들다 본체를 못 만드는 일 없게.
- 킷 레포는 private. hikidev 계정은 **읽기 + 자기 브랜치 푸시**만. main은 PR → 승인.
- hikidev가 실행 중 쓰는 킷은 작업 폴더 복사본이 아니라 **고정 릴리즈**(이미지에 설치) → 자기가 고쳐도 자기는 안 죽는다.
- 완성되면 주인이 개인 git에도 백업.

---

## 13. 오픈소스

- 라이선스: **MIT**. (특허는 고려하지 않음 — 컨셉이 일반적이라 의미 없음)
- hikidev가 만드는 프로젝트의 라이선스는 별개, 걔가 프로젝트마다 고른다 (self.md 취향).
- 이름: 공식 정책상 "Claude Code"를 제품명에 쓸 수 없음. hikidev는 문제없음.
- 설치: `npx hikidev init` → 설정 파일 생성, `claude` 로그인 여부 확인, Docker 확인, 디스코드 채널 설정.
- 지원 OS: Windows(WSL2/Docker Desktop) 우선, Linux/macOS는 Docker만 있으면 동일.
- 안전한 기본값: runner=cli, 레포 private, 승인 큐 ON, 사설망 차단 ON, 하루 가동 8시간.

---

## 14. 작업 방식: 방 구조

레포(산출물) 기준으로 세션을 나눈다. 같은 파일을 두 방이 건드리지 않는다.

| 방 | 레포 | 하는 일 | 규칙 |
|---|---|---|---|
| 설계방 | `hikidev/DESIGN.md` (이 폴더) | 결정·스펙 | 코드 안 씀. source of truth |
| 킷방 | `kits` | 공통 모듈 | hikidev 모르고도 쓸 수 있게 범용으로 |
| 본체방 | `hikidev` | 오케스트레이터·MCP·runner 조립 | 킷 import. 설계 바뀌면 설계방으로 |
| 운영방 | — | 가동 후 로그·장애·self.md 튜닝 | |

- 각 레포에 `CLAUDE.md`.
- 진행일지: Notion "hikidev 진행일지" DB, 방마다 세션 끝날 때 한 항목. hikidev 본인 일기는 "📄 Progress Diary" DB — 둘을 섞지 않는다.

---

## 15. 로드맵

### Phase 0 — 킷 (킷방)
1. `runner` (CliRunner 먼저, SdkRunner는 인터페이스만)
2. `discord` (채널 라우팅, notify, inbox, 승인 버튼)
3. `supervisor`
4. `notion`
5. 킷 완성본 개인 git 백업

### Phase 1 — MVP 본체 (본체방)
- 심장박동 + CliRunner + MCP 서버(5개 도구) + 파일 기억 구조
- Docker 이미지 (사설망 차단 포함)
- hikidev GitHub machine account, 디스코드 채널
- `self.md` 초기값 작성 (ithan's hikidev)
- `notion` 킷을 "📄 Progress Diary" DB에 연결

### Phase 2 — 운영하며 다듬기 (운영방)
- 컨디션 신호 튜닝, 포기/복귀 패턴 관찰
- 승인 큐 완화 (신뢰 쌓이면)
- SdkRunner 완성 + 예산
- 오케스트레이터 자기 수정 (PR → 승인 → blue-green)

### 가동 전 체크리스트
- [ ] 킷 완성본 개인 git 백업
- [ ] hikidev 전용 GitHub 계정 + 토큰 주입
- [ ] 디스코드 채널 + 봇 라우팅 확인
- [ ] 사설망 차단 테스트 (컨테이너에서 192.168.x.x 접근 실패 확인)
- [ ] 승인 큐 ON, 레포 private 기본값 확인
- [ ] self.md 초기값
- [ ] supervisor 웹훅 테스트 (오케스트레이터 죽였을 때 알림 오는지)

---

## 16. 미결 사항

- 디스코드 기존 모듈이 라이브러리인지 서비스인지 → `discord` 킷 형태 결정 (킷방에서)
- 컨텍스트 사용량 임계치, 심장박동 주기, 하루 가동 시간 기본값 → 돌려보며 조정
- hikidev 일기 → "📄 Progress Diary" DB로 확정. 속성(제목/일시/텍스트)에 프로젝트·컨디션 컬럼을 추가할지는 `notion` 킷 만들 때
- 킷 레포 이름, 패키지 배포 방식 (git dependency vs 로컬 레지스트리) → 킷방에서
