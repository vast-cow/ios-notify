from __future__ import annotations

import ctypes
import importlib.metadata
import platform
import sys

from ios_notify.constants import ANCS_SERVICE
from ios_notify.windows.device_discovery import find_paired_ble_devices, find_service_candidates
from ios_notify.windows.notification_identity import (
    TOAST_APP_ID,
    TOAST_DISPLAY_NAME,
    registered_display_name,
)


def _package_identity() -> bool:
    length = ctypes.c_uint32()
    # APPMODEL_ERROR_NO_PACKAGE (15700) means this is an unpackaged process.
    return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700


def _winrt_versions() -> str:
    names = (
        "winrt-Windows.Devices.Bluetooth",
        "winrt-Windows.Devices.Bluetooth.GenericAttributeProfile",
        "winrt-Windows.Devices.Enumeration",
        "winrt-Windows.Storage.Streams",
    )
    return ", ".join(
        f"{name}={importlib.metadata.version(name)}" if _installed(name) else f"{name}=not installed"
        for name in names
    )


def _installed(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


async def diagnose() -> None:
    """Print a side-effect-free Windows/BLE diagnostic report."""
    from winrt.windows.devices.bluetooth import BluetoothCacheMode, BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceAccessInformation
    from winrt.windows.ui.notifications import ToastNotificationManager

    print(f"Windows: {platform.platform()} ({platform.version()})")
    print(f"Python: {sys.version.split()[0]}")
    print(f"PyWinRT: {_winrt_versions()}")
    print(f"Package identity: {'yes' if _package_identity() else 'no'}")
    display_name = registered_display_name()
    notifier = ToastNotificationManager.create_toast_notifier_with_id(TOAST_APP_ID)
    setting = getattr(notifier.setting, "name", str(notifier.setting))
    print("Notification identity:")
    print(f"  AppUserModelID: {TOAST_APP_ID}")
    print(f"  Registry registration: {'yes' if display_name else 'no'}")
    print(f"  DisplayName: {display_name or TOAST_DISPLAY_NAME + ' (expected)'}")
    print(f"  Notifier setting: {setting}")

    devices = await find_paired_ble_devices()
    print(f"Paired BLE endpoints: {len(devices)}")
    for candidate in devices:
        print(f"- {candidate.name}: enabled={candidate.is_enabled} paired={candidate.is_paired} properties={dict(candidate.properties)!r}")
        device = await BluetoothLEDevice.from_id_async(candidate.id)
        if device is None:
            print("  device query: BluetoothLEDevice.from_id_async returned None")
            continue
        try:
            result = await device.get_gatt_services_for_uuid_with_cache_mode_async(ANCS_SERVICE, BluetoothCacheMode.UNCACHED)
            print(f"  uncached ANCS query: status={result.status} services={len(result.services)} protocol_error={getattr(result, 'protocol_error', None)}")
            for service in result.services:
                service.close()
        finally:
            device.close()

    services = await find_service_candidates(ANCS_SERVICE)
    print(f"ANCS service interfaces: {len(services)}")
    for candidate in services:
        access = DeviceAccessInformation.create_from_id(candidate.id)
        print(
            f"- {candidate.name}: enabled={candidate.is_enabled} paired={candidate.is_paired} "
            f"access={access.current_status} prompt_required={access.user_prompt_required} "
            f"properties={dict(candidate.properties)!r}"
        )
