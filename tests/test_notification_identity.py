import sys
from types import ModuleType, SimpleNamespace

import pytest

from ios_notify.windows.notification_identity import (
    REGISTRY_PATH,
    TOAST_APP_ID,
    TOAST_DISPLAY_NAME,
    ensure_notification_identity,
    registered_display_name,
)


class FakeKey:
    def __enter__(self) -> "FakeKey":
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def _fake_winreg() -> tuple[ModuleType, dict[str, object]]:
    module = ModuleType("winreg")
    values: dict[str, object] = {}
    module.HKEY_CURRENT_USER = "HKCU"  # type: ignore[attr-defined]
    module.KEY_SET_VALUE = 1  # type: ignore[attr-defined]
    module.KEY_READ = 2  # type: ignore[attr-defined]
    module.REG_SZ = 3  # type: ignore[attr-defined]

    def create_key(root: object, path: str, reserved: int, access: int) -> FakeKey:
        assert (root, path, reserved, access) == ("HKCU", REGISTRY_PATH, 0, 1)
        return FakeKey()

    def set_value(
        _key: FakeKey, name: str, reserved: int, kind: int, value: str
    ) -> None:
        assert (name, reserved, kind) == ("DisplayName", 0, 3)
        values[name] = value

    module.CreateKeyEx = create_key  # type: ignore[attr-defined]
    module.SetValueEx = set_value  # type: ignore[attr-defined]
    return module, values


def test_ensure_notification_identity_registers_and_sets_process_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winreg, values = _fake_winreg()
    app_ids: list[str] = []

    class FakeSetAppId:
        argtypes: object = None
        restype: object = None

        def __call__(self, app_id: str) -> int:
            app_ids.append(app_id)
            return 0

    monkeypatch.setitem(sys.modules, "winreg", winreg)
    monkeypatch.setattr(
        "ios_notify.windows.notification_identity.ctypes.windll",
        SimpleNamespace(
            shell32=SimpleNamespace(
                SetCurrentProcessExplicitAppUserModelID=FakeSetAppId()
            )
        ),
        raising=False,
    )

    ensure_notification_identity()

    assert TOAST_APP_ID == "VastCow.IosNotify"
    assert values == {"DisplayName": TOAST_DISPLAY_NAME}
    assert app_ids == [TOAST_APP_ID]


def test_registered_display_name_reads_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    winreg, _ = _fake_winreg()
    winreg.OpenKey = lambda *_args: FakeKey()  # type: ignore[attr-defined]
    winreg.QueryValueEx = lambda *_args: (TOAST_DISPLAY_NAME, 3)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "winreg", winreg)

    assert registered_display_name() == TOAST_DISPLAY_NAME
