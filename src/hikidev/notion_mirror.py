"""journal → Notion "📄 Progress Diary" 미러. 파일이 원본, 노션은 거울. 실패해도 심장박동은 멈추지 않는다."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .config import NotionConfig
from .home import HikidevHome

log = logging.getLogger("hikidev.notion")


def build_mirror(home: HikidevHome, cfg: NotionConfig):
    """토큰·DB ID 가 없으면 None."""
    token = os.environ.get("NOTION_TOKEN", "")
    ds = os.environ.get("NOTION_DATA_SOURCE_ID", "")
    if not cfg.mirror_journal or not token or not ds:
        return None
    from kits_notion import JournalMirror, NotionClient, PropertyMapping

    m = cfg.mapping
    mapping = PropertyMapping(
        title=m.get("title", "제목"), date=m.get("date"), summary=m.get("summary"), source=m.get("source")
    )
    return JournalMirror(NotionClient(token), ds, mapping, state_file=home.notion_state_json)


def mirror_journal(home: HikidevHome, cfg: NotionConfig, day: str) -> str | None:
    """오늘 journal 파일을 미러. 페이지 URL 또는 None."""
    path: Path = home.journal_path(day)
    if not path.exists():
        return None
    mirror = build_mirror(home, cfg)
    if mirror is None:
        return None
    try:
        r = mirror.mirror_file(path)
        log.info("notion mirror %s → %s (%s)", path.name, r.page_id, "created" if r.created else "updated")
        return r.url
    except Exception as e:  # noqa: BLE001
        log.warning("notion mirror 실패 (무시): %s", e)
        return None
