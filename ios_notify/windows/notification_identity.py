from __future__ import annotations

import ctypes

TOAST_APP_ID = "VastCow.IosNotify"
TOAST_DISPLAY_NAME = "iOS Notify"
REGISTRY_PATH = rf"Software\Classes\AppUserModelId\{TOAST_APP_ID}"


def ensure_notification_identity() -> None:
    """Register and apply the notification identity for this process."""
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        REGISTRY_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, TOAST_DISPLAY_NAME)

    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    result = set_app_id(TOAST_APP_ID)
    if result != 0:
        raise OSError(result, "failed to set the process AppUserModelID")


def registered_display_name() -> str | None:
    """Return the registered display name, or ``None`` when it is absent."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ
        ) as key:
            value, value_type = winreg.QueryValueEx(key, "DisplayName")
    except FileNotFoundError:
        return None
    return value if value_type == winreg.REG_SZ else None
