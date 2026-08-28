import asyncio
import sys
from types import ModuleType

import pytest

from ios_notify.models import EventType, IOSNotification
from ios_notify.windows.toast import (
    TOAST_APP_ID,
    TOAST_GROUP,
    ToastService,
    _clear_toast,
)


def test_toast_tag_uses_ancs_session_and_uid() -> None:
    notification = IOSNotification(uid=42, event=EventType.ADDED, session_id=7)

    assert ToastService(asyncio.Queue())._tag(notification) == "7-42"


def test_clear_toast_uses_grouped_tag_with_id_overload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple[str, str, str]] = []

    class FakeHistory:
        def remove_grouped_tag_with_id(
            self, tag: str, group: str, app_id: str
        ) -> None:
            removed.append((tag, group, app_id))

        def remove(self, *_args: object) -> None:
            raise AssertionError("the non-overload-specific method must not be used")

    class FakeToastNotificationManager:
        history = FakeHistory()

    notifications_module = ModuleType("winrt.windows.ui.notifications")
    notifications_module.ToastNotificationManager = (  # type: ignore[attr-defined]
        FakeToastNotificationManager
    )
    monkeypatch.setitem(
        sys.modules, "winrt.windows.ui.notifications", notifications_module
    )

    _clear_toast("7-42")

    assert removed == [("7-42", TOAST_GROUP, TOAST_APP_ID)]
