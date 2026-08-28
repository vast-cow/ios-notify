from __future__ import annotations

import asyncio
import logging

from ios_notify.models import EventType, IOSNotification

LOGGER = logging.getLogger(__name__)
TOAST_APP_ID = "Python"
TOAST_GROUP = "ios-ancs"


def _clear_toast(tag: str) -> None:
    from winrt.windows.ui.notifications import ToastNotificationManager

    ToastNotificationManager.history.remove_grouped_tag_with_id(
        tag,
        TOAST_GROUP,
        TOAST_APP_ID,
    )


class ToastService:
    def __init__(self, notifications: asyncio.Queue[IOSNotification]) -> None:
        self.notifications = notifications

    @staticmethod
    def _tag(notification: IOSNotification) -> str:
        return f"{notification.session_id}-{notification.uid}"

    async def show(self, notification: IOSNotification) -> None:
        tag = self._tag(notification)
        if notification.event == EventType.REMOVED:
            # Keep the synchronous WinRT operation and its objects on one worker
            # thread. win11toast.clear_toast uses a pre-PyWinRT 3.x overload name.
            await asyncio.to_thread(_clear_toast, tag)
            return

        from win11toast import toast_async

        title = notification.title or notification.app_name or "iPhone"
        body = "\n".join(
            part for part in (notification.subtitle, notification.message) if part
        )
        await toast_async(
            title,
            body,
            tag=tag,
            group=TOAST_GROUP,
            app_id=TOAST_APP_ID,
        )

    async def run(self) -> None:
        while True:
            notification = await self.notifications.get()
            try:
                await self.show(notification)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("failed to display Windows toast")
