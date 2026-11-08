# hikidev 의 방. python + uv + claude CLI + 킷(고정 태그) + hikidev.
# 빌드:  docker compose build
#        (킷 레포가 private 이라 빌드 시 git 자격증명이 필요하다 — docker-compose.yml 의 secrets 참고)
ARG UV_VERSION=0.13.5
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim

ARG CLAUDE_VERSION=2.1.314

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates tzdata iptables util-linux procps openssh-client ripgrep jq \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

RUN useradd -m -s /bin/bash hikidev

# claude CLI (네이티브 설치, 버전 고정). 로그인은 사용자 몫 (CLAUDE_CODE_OAUTH_TOKEN 또는 ~/.claude 마운트).
USER hikidev
WORKDIR /home/hikidev
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_VERSION}
ENV PATH="/home/hikidev/.local/bin:${PATH}"

# hikidev 본체 + 킷 (uv.lock 에 고정된 태그 그대로)
USER root
WORKDIR /opt/hikidev
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=secret,id=git_credentials,required=false \
    if [ -f /run/secrets/git_credentials ]; then \
      git config --global credential.helper "store --file=/run/secrets/git_credentials"; fi \
    && uv sync --frozen --no-dev \
    && git config --global --unset credential.helper || true
ENV PATH="/opt/hikidev/.venv/bin:${PATH}" \
    HIKIDEV_HOME=/home/hikidev/home \
    CLAUDE_CLI_PATH=claude

COPY docker/entrypoint.sh /usr/local/bin/hikidev-entrypoint
COPY docker/check-network.sh /usr/local/bin/hikidev-check-network
RUN chmod +x /usr/local/bin/hikidev-entrypoint /usr/local/bin/hikidev-check-network \
    && mkdir -p /home/hikidev/home /home/hikidev/.claude && chown -R hikidev:hikidev /home/hikidev \
    && git config --system safe.directory '*'
# ↑ home/ 에 호스트(root 소유)에서 만든 git 레포가 있어도 "dubious ownership" 이 안 뜨게. /etc/gitconfig 는 이미지 안이라
#   컨테이너를 교체해도 남는다. 컨테이너 안은 걔 혼자라 '*' 의 보안 의미는 없다 (DESIGN §16, 2026-11-08)

# entrypoint 가 root 로 iptables 를 걸고 hikidev 사용자로 내려간다 (NET_ADMIN 필요)
ENTRYPOINT ["hikidev-entrypoint"]
CMD ["hikidev", "supervise", "--home", "/home/hikidev/home"]
