from __future__ import annotations

from pathlib import Path

import pytest

from hikidev.config import Config
from hikidev.home import HikidevHome


@pytest.fixture
def home(tmp_path: Path) -> HikidevHome:
    h = HikidevHome(tmp_path / "home")
    h.init(name="test hikidev", values={"interests": "테스트", "channel_id": "123", "owner_id": "9"})
    return h


@pytest.fixture
def cfg() -> Config:
    c = Config(name="test hikidev")
    c.schedule.heartbeat_minutes = 1
    c.notion.mirror_journal = False
    return c
