from __future__ import annotations

import json

from hikidev import notion_mirror
from hikidev.config import NotionConfig
from hikidev.home import HikidevHome


class FakeMirror:
    """kits JournalMirror 흉내: 상태 파일의 절대 경로 키로 upsert 판단."""

    def __init__(self, state_file):
        self.state_file = state_file
        self.created = 0

    def mirror_file(self, path):
        from kits_notion import MirrorResult

        state = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}
        key = str(path.resolve())
        if key in state:
            return MirrorResult(key, state[key], created=False)
        self.created += 1
        page = f"page-{self.created}"
        state[key] = page
        self.state_file.write_text(json.dumps(state), encoding="utf-8")
        return MirrorResult(key, page, created=True, url=f"https://notion/{page}")


def test_mirror_reuses_page_across_machines(home: HikidevHome, monkeypatch) -> None:
    home.journal_dir.joinpath("2026-11-01.md").write_text("# 오늘\n일기", encoding="utf-8")
    fake = FakeMirror(home.notion_state_json)
    monkeypatch.setattr(notion_mirror, "build_mirror", lambda h, c: fake)
    cfg = NotionConfig()

    assert notion_mirror.mirror_journal(home, cfg, "2026-11-01") == "https://notion/page-1"
    m = json.loads(home.notion_map_json.read_text(encoding="utf-8"))
    assert m == {"journal/2026-11-01.md": "page-1"}

    # 다른 머신에서 돌린 것처럼: 킷 상태 파일(절대 경로 키)이 비어 있어도 우리 매핑으로 같은 페이지를 갱신
    home.notion_state_json.unlink()
    notion_mirror.mirror_journal(home, cfg, "2026-11-01")
    assert fake.created == 1
    state = json.loads(home.notion_state_json.read_text(encoding="utf-8"))
    assert list(state.values()) == ["page-1"]


def test_mirror_without_token_is_noop(home: HikidevHome, monkeypatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    home.journal_dir.joinpath("2026-11-01.md").write_text("x", encoding="utf-8")
    assert notion_mirror.mirror_journal(home, NotionConfig(), "2026-11-01") is None
    assert notion_mirror.mirror_journal(home, NotionConfig(), "2026-10-31") is None
