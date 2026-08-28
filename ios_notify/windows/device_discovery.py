from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

LOGGER = logging.getLogger(__name__)

DEVICE_PROPERTIES = [
    "System.Devices.Aep.DeviceAddress",
    "System.Devices.Aep.IsConnected",
]


@dataclass(frozen=True, slots=True)
class ServiceCandidate:
    id: str
    name: str
    is_enabled: bool
    is_paired: bool
    properties: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BleDeviceCandidate:
    id: str
    name: str
    is_enabled: bool
    is_paired: bool
    properties: Mapping[str, object]


def _candidate(info: object, cls: type[ServiceCandidate] | type[BleDeviceCandidate]):
    pairing = getattr(info, "pairing", None)
    return cls(
        id=info.id,
        name=getattr(info, "name", "") or "(unnamed)",
        is_enabled=bool(getattr(info, "is_enabled", True)),
        is_paired=bool(getattr(pairing, "is_paired", False)),
        properties=dict(getattr(info, "properties", {}) or {}),
    )


def _short_id(value: str) -> str:
    return value if len(value) <= 36 else f"{value[:16]}...{value[-12:]}"


async def find_service_candidates(service_uuid: UUID) -> list[ServiceCandidate]:
    """Return rich Windows service-interface records matching *service_uuid*."""
    from winrt.windows.devices.bluetooth.genericattributeprofile import GattDeviceService
    from winrt.windows.devices.enumeration import DeviceInformation

    selector = GattDeviceService.get_device_selector_from_uuid(service_uuid)
    devices = await DeviceInformation.find_all_async_aqs_filter_and_additional_properties(
        selector, DEVICE_PROPERTIES
    )
    candidates = [_candidate(info, ServiceCandidate) for info in devices]
    LOGGER.debug("found %d ANCS service candidate(s)", len(candidates))
    for item in candidates:
        LOGGER.debug(
            "ANCS service name=%r enabled=%s paired=%s id=%s properties=%r",
            item.name,
            item.is_enabled,
            item.is_paired,
            _short_id(item.id),
            item.properties,
        )
    return candidates


async def find_paired_ble_devices() -> list[BleDeviceCandidate]:
    """Enumerate paired BLE association endpoints, retaining useful metadata."""
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind

    selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
    devices = await (
        DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties(
            selector, DEVICE_PROPERTIES, DeviceInformationKind.ASSOCIATION_ENDPOINT
        )
    )
    candidates = [_candidate(info, BleDeviceCandidate) for info in devices]
    LOGGER.debug("found %d paired BLE endpoint(s)", len(candidates))
    for item in candidates:
        LOGGER.debug(
            "BLE endpoint name=%r enabled=%s paired=%s id=%s properties=%r",
            item.name,
            item.is_enabled,
            item.is_paired,
            _short_id(item.id),
            item.properties,
        )
    return candidates


async def find_service_ids(service_uuid: UUID) -> list[str]:
    """Compatibility helper returning IDs from rich service candidates."""
    return [item.id for item in await find_service_candidates(service_uuid)]
