#!/bin/bash
# 컨테이너 시작: 사설 IP 대역 차단(iptables) → hikidev 사용자로 명령 실행.
# DESIGN.md 4절: 인터넷 O, 사설망 X. 필요한 cap: NET_ADMIN (docker-compose.yml).
set -euo pipefail

PRIVATE_RANGES="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16"

if [ "$(id -u)" = "0" ]; then
  if [ "${HIKIDEV_BLOCK_PRIVATE:-1}" = "1" ]; then
    if iptables -L OUTPUT -n >/dev/null 2>&1; then
      # 컨테이너 자신의 네트워크(브리지 게이트웨이)는 DNS/라우팅에 필요하므로 둔다 — 목적지 기준 차단이라 공인 IP 통신엔 영향 없음.
      # 단, 게이트웨이가 사설 대역이므로 게이트웨이 자체로 가는 패킷(HTTP 등)은 허용하지 않는다. docker-compose 의 dns: 로 공개 DNS 를 쓴다.
      for r in $PRIVATE_RANGES; do
        iptables -C OUTPUT -d "$r" -j REJECT 2>/dev/null || iptables -A OUTPUT -d "$r" -j REJECT --reject-with icmp-net-prohibited
      done
      echo "[entrypoint] 사설 대역 차단: $PRIVATE_RANGES"
    else
      echo "[entrypoint] 경고: iptables 를 쓸 수 없다 (cap_add: NET_ADMIN 확인). 사설망 차단 없이 진행." >&2
    fi
  fi
  chown hikidev:hikidev /home/hikidev/home 2>/dev/null || true
  # 세션 저장소(named volume). 빈 볼륨을 docker 가 root 로 만들었을 수 있으니 최상위만 넘겨준다 (내용물은 걔가 만든 거라 이미 걔 것)
  mkdir -p /home/hikidev/.claude && chown hikidev:hikidev /home/hikidev/.claude 2>/dev/null || true
  # 이 컨테이너의 정체를 남긴다. 오케스트레이터가 지난 박동의 값과 비교해 "방이 교체됐다"를 다음 박동 신호에 적는다 (DESIGN §16)
  BOOT_DIR="${HIKIDEV_HOME:-/home/hikidev/home}/.hikidev"
  mkdir -p "$BOOT_DIR" \
    && printf '{"container": "%s", "started_at": "%s"}\n' "${HOSTNAME:-$(cat /etc/hostname 2>/dev/null || echo unknown)}" "$(date -Iseconds)" > "$BOOT_DIR/boot.json" \
    && chown hikidev:hikidev "$BOOT_DIR" "$BOOT_DIR/boot.json" 2>/dev/null || true
  # git 전역 설정(user.name 등)은 home/ 안에 둔다 — /home/hikidev 는 overlay 라 교체 때 ~/.gitconfig 가 사라진다 (2026-11-08)
  exec setpriv --reuid=hikidev --regid=hikidev --init-groups --reset-env \
    env HOME=/home/hikidev PATH="$PATH" HIKIDEV_HOME="${HIKIDEV_HOME:-/home/hikidev/home}" \
        CLAUDE_CLI_PATH=claude PYTHONIOENCODING=utf-8 \
        GIT_CONFIG_GLOBAL=/home/hikidev/home/.gitconfig \
        $(env | grep -E '^(DISCORD_|NOTION_|GITHUB_|CLAUDE_CODE_|ANTHROPIC_|HIKIDEV_|YOUTUBE_|TZ=)' | sed 's/^/ /') \
    "$@"
fi
exec "$@"
