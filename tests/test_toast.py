import asyncio

from ios_notify.models import EventType, IOSNotification
from ios_notify.windows.toast import ToastService


def test_toast_tag_uses_ancs_session_and_uid() -> None:
    notification = IOSNotification(uid=42, event=EventType.ADDED, session_id=7)

    assert ToastService(asyncio.Queue())._tag(notification) == "7-42"
