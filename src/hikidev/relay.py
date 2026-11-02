"""MCP 서버가 파일에 남긴 요청(outbox / approvals)을 디스코드로 중계하고, 디스코드 inbox 를 파일로 적는다.

Discord 가 없으면(토큰 없음) 로그로만 남긴다 — 세션은 그래도 돈다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import DiscordConfig
from .home import HikidevHome, now_iso

log = logging.getLogger("hikidev.relay")
CHANNEL = "hikidev"


class Relay:
    def __init__(self, home: HikidevHome, cfg: DiscordConfig, token: str | None, *, owner_name: str = ""):
        self.home = home
        self.cfg = cfg
        self.owner_name = owner_name
        """inbox 파일의 from: 에 쓸 이름. 디스코드 표시명(ithan_alarm 같은) 대신."""
        self.token = token
        self.svc: Any = None
        self._approval_tasks: dict[str, asyncio.Task[None]] = {}
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return self.svc is not None

    async def start(self) -> None:
        if not self.token or not self.cfg.channel_id:
            log.warning("디스코드 비활성 (DISCORD_BOT_TOKEN 또는 discord.channel_id 없음) — notify 는 로그로만")
            return
        from kits_discord import DiscordService

        svc = DiscordService(
            self.token,
            inbox_file=self.home.inbox_jsonl,
            owner_ids=[self.cfg.owner_id] if self.cfg.owner_id else None,
            approval_timeout_s=self.cfg.approval_timeout_hours * 3600,
        )
        svc.register(CHANNEL, self.cfg.channel_id, on_inbox=self._on_inbox)
        await svc.start()
        self.svc = svc
        log.info("디스코드 봇 준비: %s (채널 %s)", svc.client.user, self.cfg.channel_id)

    async def stop(self) -> None:
        await self.stop_polling()
        for t in self._approval_tasks.values():
            t.cancel()
        if self.svc:
            await self.svc.stop()
            self.svc = None

    # ── inbox: 디스코드 → inbox/*.md ──────────────────────────
    def _on_inbox(self, m: Any) -> None:
        author = m.author_name or m.author_id
        if self.owner_name and self.cfg.owner_id and str(m.author_id) == self.cfg.owner_id:
            author = self.owner_name
        p = self.home.write_inbox(author=author, content=m.content, at=m.created_at, msg_id=m.id)
        log.info("inbox ← %s: %s", m.author_name, p.name)

    # ── notify / approvals: 파일 → 디스코드 ───────────────────
    async def notify(self, message: str) -> None:
        if self.svc:
            try:
                await self.svc.notify(CHANNEL, message)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("notify 실패: %s", e)
        log.info("[notify] %s", message)

    async def pump(self) -> None:
        """outbox 와 pending 승인을 한 번 처리한다."""
        for msg in self.home.drain_outbox():
            await self.notify(msg)
        for a in self.home.load_approvals():
            if a.status == "pending" and a.id not in self._approval_tasks:
                self._approval_tasks[a.id] = asyncio.create_task(self._handle_approval(a.id, a.action, a.why))

    async def _handle_approval(self, aid: str, action: str, why: str) -> None:
        if not self.svc:
            log.info("[approval 요청, 디스코드 없음] %s — %s (id=%s)", action, why, aid)
            return
        try:
            r = await self.svc.request_approval(CHANNEL, action, why, approval_id=aid)
            self.home.update_approval(aid, status=r.decision, decided_at=now_iso(), by=r.by)
            log.info("승인 결과 %s: %s", aid, r.decision)
        except Exception as e:  # noqa: BLE001
            log.warning("승인 요청 실패 %s: %s", aid, e)
        finally:
            self._approval_tasks.pop(aid, None)

    async def start_polling(self, interval_s: float = 1.0) -> None:
        async def loop() -> None:
            while True:
                try:
                    await self.pump()
                except Exception as e:  # noqa: BLE001
                    log.warning("relay pump 실패: %s", e)
                await asyncio.sleep(interval_s)

        self._poll_task = asyncio.create_task(loop())

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        await self.pump()
