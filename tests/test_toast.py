import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ios_notify.models import EventType, IOSNotification
from ios_notify.windows.toast import (
    TOAST_APP_ID,
    TOAST_GROUP,
    ToastService,
    _clear_toast,
    _show_toast,
)


def _install_fake_winrt(monkeypatch: pytest.MonkeyPatch) -> tuple[type, list[object]]:
    shown: list[object] = []

    class FakeXmlDocument:
        source = ""

        def load_xml(self, source: str) -> None:
            self.source = source

    class FakeToastNotification:
        def __init__(self, xml: FakeXmlDocument) -> None:
            self.xml = xml
            self.tag = ""
            self.group = ""

    class FakeNotifier:
        def show(self, toast: object) -> None:
            shown.append(toast)

    class FakeToastNotificationManager:
        @staticmethod
        def create_toast_notifier_with_id(app_id: str) -> FakeNotifier:
            assert app_id == TOAST_APP_ID
            return FakeNotifier()

    xml_module = ModuleType("winrt.windows.data.xml.dom")
    xml_module.XmlDocument = FakeXmlDocument  # type: ignore[attr-defined]
    notifications_module = ModuleType("winrt.windows.ui.notifications")
    notifications_module.ToastNotification = FakeToastNotification  # type: ignore[attr-defined]
    notifications_module.ToastNotificationManager = (  # type: ignore[attr-defined]
        FakeToastNotificationManager
    )
    monkeypatch.setitem(sys.modules, "winrt.windows.data.xml.dom", xml_module)
    monkeypatch.setitem(
        sys.modules, "winrt.windows.ui.notifications", notifications_module
    )
    return FakeToastNotification, shown


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


def test_show_toast_uses_winrt_with_escaped_text_and_icon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toast_type, shown = _install_fake_winrt(monkeypatch)
    icon = tmp_path / "icon & image.png"
    icon.write_bytes(b"png")

    _show_toast("A <title>", "body & more", icon, "7-42")

    assert len(shown) == 1
    toast = shown[0]
    assert isinstance(toast, toast_type)
    assert toast.tag == "7-42"
    assert toast.group == TOAST_GROUP
    assert "<text>A &lt;title&gt;</text>" in toast.xml.source
    assert "<text>body &amp; more</text>" in toast.xml.source
    assert 'placement="appLogoOverride"' in toast.xml.source
    assert icon.resolve().as_uri().replace("&", "&amp;") in toast.xml.source


def test_show_uses_cached_icon_as_square_app_logo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, shown = _install_fake_winrt(monkeypatch)
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"png")

    class FakeResolver:
        def get_cached(self, _app_id: str | None) -> Path:
            return icon

        def prefetch(self, _app_id: str | None) -> None:
            raise AssertionError("a cached icon must not be prefetched")

    notification = IOSNotification(
        uid=1,
        event=EventType.ADDED,
        session_id=2,
        app_id="com.example.app",
        title="Title",
    )
    service = ToastService(asyncio.Queue(), FakeResolver())  # type: ignore[arg-type]

    asyncio.run(service.show(notification))

    assert icon.resolve().as_uri() in shown[0].xml.source


def test_show_waits_briefly_for_first_icon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, shown = _install_fake_winrt(monkeypatch)
    icon = tmp_path / "downloaded.png"
    icon.write_bytes(b"png")

    class FakeResolver:
        def get_cached(self, _app_id: str | None) -> None:
            return None

        def prefetch(self, _app_id: str | None) -> asyncio.Task[Path]:
            async def resolve() -> Path:
                await asyncio.sleep(0)
                return icon

            return asyncio.create_task(resolve())

    notification = IOSNotification(
        uid=1,
        event=EventType.ADDED,
        session_id=2,
        app_id="com.example.app",
    )
    service = ToastService(asyncio.Queue(), FakeResolver())  # type: ignore[arg-type]

    asyncio.run(service.show(notification))

    assert icon.resolve().as_uri() in shown[0].xml.source


def test_show_does_not_cancel_slow_icon_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, shown = _install_fake_winrt(monkeypatch)
    monkeypatch.setattr("ios_notify.windows.toast.ICON_GRACE_PERIOD", 0.001)

    async def exercise() -> bool:
        release = asyncio.Event()

        class FakeResolver:
            task: asyncio.Task[Path | None] | None = None

            def get_cached(self, _app_id: str | None) -> None:
                return None

            def prefetch(
                self, _app_id: str | None
            ) -> asyncio.Task[Path | None]:
                async def resolve() -> Path | None:
                    await release.wait()
                    return None

                self.task = asyncio.create_task(resolve())
                return self.task

        resolver = FakeResolver()
        notification = IOSNotification(
            uid=1,
            event=EventType.ADDED,
            session_id=2,
            app_id="com.example.app",
        )
        service = ToastService(
            asyncio.Queue(), resolver  # type: ignore[arg-type]
        )

        await service.show(notification)
        assert resolver.task is not None
        still_running = not resolver.task.done()
        release.set()
        await resolver.task
        return still_running

    assert asyncio.run(exercise())
    assert "<image" not in shown[0].xml.source
