#!/bin/bash
# 가동 전 체크리스트: 컨테이너에서 사설망은 막히고 인터넷은 되는지.
#   docker compose run --rm hikidev hikidev-check-network
set -u
ok=0
for ip in 192.168.0.1 10.0.0.1 172.16.0.1 169.254.169.254; do
  if curl -s -m 3 -o /dev/null "http://$ip/"; then
    echo "FAIL: $ip 에 접속됨 (사설망 차단 안 됨)"; ok=1
  else
    echo "ok: $ip 차단"
  fi
done
if curl -s -m 10 -o /dev/null https://api.github.com/; then
  echo "ok: 인터넷 됨"
else
  echo "FAIL: 인터넷 안 됨"; ok=1
fi
claude --version 2>/dev/null && echo "ok: claude CLI" || { echo "FAIL: claude CLI 없음"; ok=1; }
exit $ok
