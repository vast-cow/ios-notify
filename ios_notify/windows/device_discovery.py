from __future__ import annotations

from uuid import UUID


async def find_service_ids(service_uuid: UUID) -> list[str]:
    """Return device IDs for bonded GATT services matching *service_uuid*."""
    from winrt.windows.devices.bluetooth.genericattributeprofile import GattDeviceService
    from winrt.windows.devices.enumeration import DeviceInformation

    selector = GattDeviceService.get_device_selector_from_uuid(service_uuid)
    devices = await DeviceInformation.find_all_async(selector)
    return [device.id for device in devices]
