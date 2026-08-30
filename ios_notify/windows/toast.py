from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ios_notify.icons.resolver import IconResolver
from ios_notify.models import EventType, IOSNotification
from ios_notify.windows.notification_identity import TOAST_APP_ID

LOGGER = logging.getLogger(__name__)
TOAST_GROUP = "ios-ancs"
ICON_GRACE_PERIOD = 0.75


def _clear_toast(tag: str) -> None:
    from winrt.windows.ui.notifications import ToastNotificationManager

    ToastNotificationManager.history.remove_grouped_tag_with_id(
        tag,
        TOAST_GROUP,
        TOAST_APP_ID,
    )


def _show_toast(title: str, body: str, icon_path: Path | None, tag: str) -> None:
    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import (
        ToastNotification,
        ToastNotificationManager,
    )

    image = (
        f"<image placement=\"appLogoOverride\" src={quoteattr(icon_path.resolve().as_uri())}/>"
        if icon_path
        else ""
    )
    xml = XmlDocument()
    xml.load_xml(
        "<toast><visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(title)}</text><text>{escape(body)}</text>{image}"
        "</binding></visual></toast>"
    )
    toast = ToastNotification(xml)
    toast.tag = tag
    toast.group = TOAST_GROUP
    LOGGER.debug("showing Windows toast app_id=%r tag=%r", TOAST_APP_ID, tag)
    notifier = ToastNotificationManager.create_toast_notifier_with_id(TOAST_APP_ID)
    notifier.show(toast)


class ToastService:
    def __init__(
        self,
        notifications: asyncio.Queue[IOSNotification],
        icons: IconResolver | None = None,
    ) -> None:
        self.notifications = notifications
        self.icons = icons

    @staticmethod
    def _tag(notification: IOSNotification) -> str:
        return f"{notification.session_id}-{notification.uid}"

    async def show(self, notification: IOSNotification) -> None:
        tag = self._tag(notification)
        if notification.event == EventType.REMOVED:
            # Keep the synchronous WinRT operation and its objects on one worker
            # thread.
            await asyncio.to_thread(_clear_toast, tag)
            return

        title = notification.title or notification.app_name or "iPhone"
        body = "\n".join(
            part for part in (notification.subtitle, notification.message) if part
        )
        icon_path: Path | None = None
        if self.icons:
            icon_path = self.icons.get_cached(notification.app_id)
            if icon_path is None:
                task = self.icons.prefetch(notification.app_id)
                if task is not None:
                    try:
                        icon_path = await asyncio.wait_for(
                            asyncio.shield(task),
                            timeout=ICON_GRACE_PERIOD,
                        )
                    except TimeoutError:
                        pass
        _show_toast(title, body, icon_path, tag)

    async def run(self) -> None:
        while True:
            notification = await self.notifications.get()
            try:
                await self.show(notification)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("failed to display Windows toast")
