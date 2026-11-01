"""journal → Notion "📄 Progress Diary" 미러. 파일이 원본, 노션은 거울. 실패해도 심장박동은 멈추지 않는다."""

from __future__ import annotations

import json
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


def _load_map(home: HikidevHome) -> dict[str, str]:
    """우리 매핑: home 기준 상대 경로 → 페이지 ID. 호스트/컨테이너 어디서 돌려도 같은 키."""
    p = home.notion_map_json
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sync_kit_state(home: HikidevHome, path: Path, rel: str) -> None:
    """킷 상태 파일은 절대 경로가 키라 머신이 바뀌면 같은 파일을 또 만든다.
    우리 매핑에서 이 머신의 절대 경로로 옮겨 적는다."""
    page = _load_map(home).get(rel)
    state: dict[str, str] = {}
    if home.notion_state_json.exists():
        try:
            data = json.loads(home.notion_state_json.read_text(encoding="utf-8"))
            state = data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            state = {}
    key = str(path.resolve())
    if page and state.get(key) != page:
        state[key] = page
        home.notion_state_json.parent.mkdir(parents=True, exist_ok=True)
        home.notion_state_json.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mirror_journal(home: HikidevHome, cfg: NotionConfig, day: str) -> str | None:
    """오늘 journal 파일을 미러. 페이지 URL 또는 None."""
    path: Path = home.journal_path(day)
    if not path.exists():
        return None
    mirror = build_mirror(home, cfg)
    if mirror is None:
        return None
    rel = path.relative_to(home.root).as_posix()
    try:
        _sync_kit_state(home, path, rel)
        r = mirror.mirror_file(path)
        m = _load_map(home)
        if m.get(rel) != r.page_id:
            m[rel] = r.page_id
            home.notion_map_json.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("notion mirror %s → %s (%s)", rel, r.page_id, "created" if r.created else "updated")
        return r.url
    except Exception as e:  # noqa: BLE001
        log.warning("notion mirror 실패 (무시): %s", e)
        return None
