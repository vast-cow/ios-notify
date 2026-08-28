import asyncio
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest

from ios_notify.windows.device_discovery import find_service_candidates


def test_finds_services_with_the_aqs_filter_overload(monkeypatch: pytest.MonkeyPatch) -> None:
    service_uuid = UUID("7905f431-b5ce-4e99-a40f-4b1e122d00d0")
    selector = 'System.Devices.AepService.ProtocolId:="{6e3bb679-4372-40c8-9eaa-4509df260cd8}"'

    class FakeGattDeviceService:
        @staticmethod
        def get_device_selector_from_uuid(value: UUID) -> str:
            assert value == service_uuid
            return selector

    class FakeDeviceInformation:
        @staticmethod
        async def find_all_async_aqs_filter_and_additional_properties(
            value: str, properties: list[str]
        ) -> list[SimpleNamespace]:
            assert value == selector
            assert properties == [
                "System.Devices.Aep.DeviceAddress",
                "System.Devices.Aep.IsConnected",
            ]
            return [
                SimpleNamespace(id="service-1", name="iPhone", is_enabled=True,
                    pairing=SimpleNamespace(is_paired=True), properties={"connected": True}),
                SimpleNamespace(id="service-2", name="old iPhone", is_enabled=False,
                    pairing=SimpleNamespace(is_paired=False), properties={}),
            ]

        @staticmethod
        async def find_all_async() -> list[SimpleNamespace]:
            raise AssertionError("the parameterless overload must not be used")

    bluetooth_module = ModuleType(
        "winrt.windows.devices.bluetooth.genericattributeprofile"
    )
    bluetooth_module.GattDeviceService = FakeGattDeviceService  # type: ignore[attr-defined]
    enumeration_module = ModuleType("winrt.windows.devices.enumeration")
    enumeration_module.DeviceInformation = FakeDeviceInformation  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        bluetooth_module,
    )
    monkeypatch.setitem(
        sys.modules, "winrt.windows.devices.enumeration", enumeration_module
    )

    candidates = asyncio.run(find_service_candidates(service_uuid))
    assert [candidate.id for candidate in candidates] == ["service-1", "service-2"]
    assert candidates[0].name == "iPhone"
    assert candidates[0].is_paired is True
    assert candidates[0].properties == {"connected": True}
