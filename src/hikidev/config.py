"""hikidev.yaml 로드. 비밀은 여기 없다 (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class ScheduleConfig:
    heartbeat_minutes: int = 30
    max_active_hours_per_day: float = 8
    rate_limit_fallback_minutes: int = 60
    """rate limit인데 리셋 시각을 모를 때 자는 시간"""


@dataclass(slots=True)
class BudgetConfig:
    daily_usd: float = 10
    on_exceed: str = "sleep"


@dataclass(slots=True)
class SessionConfig:
    context_window_tokens: int = 200_000
    context_threshold: float = 0.85
    max_turns: int = 200
    timeout_minutes: int = 120
    permission_mode: str = "bypassPermissions"
    model: str | None = None
    max_consecutive_failures: int = 3
    """같은 세션에서 연속 실패가 이 횟수면 강제 새 채팅"""


@dataclass(slots=True)
class DiscordConfig:
    channel_id: str = ""
    owner_id: str = ""
    approval_timeout_hours: float = 24


@dataclass(slots=True)
class NotionConfig:
    mirror_journal: bool = True
    mapping: dict[str, str] = field(
        default_factory=lambda: {"title": "제목", "date": "일시", "summary": "텍스트", "source": "텍스트 1"}
    )


@dataclass(slots=True)
class Config:
    name: str = "hikidev"
    owner: str = ""
    """hikidev 가 부르는 이름. 비면 "친구". 디스코드 ID 는 discord.owner_id"""
    runner: str = "cli"
    language: str = "ko"
    timezone: str = "Asia/Seoul"
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    notion: NotionConfig = field(default_factory=NotionConfig)


def _fill(cls: type, data: Any) -> Any:
    if not isinstance(data, dict):
        return cls()
    kwargs: dict[str, Any] = {}
    for f in cls.__dataclass_fields__.values():  # type: ignore[attr-defined]
        if f.name not in data:
            continue
        v = data[f.name]
        sub = {
            "budget": BudgetConfig,
            "schedule": ScheduleConfig,
            "session": SessionConfig,
            "discord": DiscordConfig,
            "notion": NotionConfig,
        }.get(f.name)
        kwargs[f.name] = _fill(sub, v) if sub else v
    return cls(**kwargs)


def load_config(path: str | Path) -> Config:
    """yaml → Config. 파일이 없으면 기본값. 환경변수 DISCORD_CHANNEL_ID / DISCORD_OWNER_ID 가 있으면 덮어쓴다."""
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg: Config = _fill(Config, data or {})
    if v := os.environ.get("DISCORD_CHANNEL_ID"):
        cfg.discord.channel_id = v
    if v := os.environ.get("DISCORD_OWNER_ID"):
        cfg.discord.owner_id = v
    cfg.discord.channel_id = str(cfg.discord.channel_id or "")
    cfg.discord.owner_id = str(cfg.discord.owner_id or "")
    return cfg
