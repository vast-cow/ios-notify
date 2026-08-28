from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from ios_notify.models import EventType, IOSNotification

LOGGER = logging.getLogger(__name__)


class ToastService:
    def __init__(self, notifications: asyncio.Queue[IOSNotification]) -> None:
        self.notifications = notifications
        self.session_id = uuid4().hex

    def _tag(self, uid: int) -> str:
        return f"{self.session_id}-{uid}"

    async def show(self, notification: IOSNotification) -> None:
        from win11toast import clear_toast, toast_async

        tag = self._tag(notification.uid)
        if notification.event == EventType.REMOVED:
            # win11toast's removal API is synchronous and is the only operation
            # intentionally moved off the asyncio/WinRT thread.
            await asyncio.to_thread(clear_toast, tag=tag, group="ios-ancs")
            return
        title = notification.title or notification.app_name or "iPhone"
        body = "\n".join(
            part for part in (notification.subtitle, notification.message) if part
        )
        await toast_async(title, body, tag=tag, group="ios-ancs")

    async def run(self) -> None:
        while True:
            notification = await self.notifications.get()
            try:
                await self.show(notification)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("failed to display Windows toast")
