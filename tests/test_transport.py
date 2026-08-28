import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ios_notify.ancs.transport import AncsTransport, RawAncsEvent, RawEventKind


def test_write_control_point_uses_write_with_response_overload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = bytes.fromhex("0005040278563412")
    detached_buffer = object()
    write_with_response = object()
    success = object()

    class FakeWriter:
        def __init__(self) -> None:
            self.data = b""

        def write_bytes(self, value: bytes) -> None:
            self.data = value

        def detach_buffer(self) -> object:
            assert self.data == request
            return detached_buffer

    class FakeControlPoint:
        async def write_value_with_option_async(
            self, buffer: object, option: object
        ) -> object:
            assert buffer is detached_buffer
            assert option is write_with_response
            return success

        async def write_value_async(self, *_args: object) -> object:
            raise AssertionError("the non-overload-specific method must not be used")

    gatt_module = ModuleType(
        "winrt.windows.devices.bluetooth.genericattributeprofile"
    )
    gatt_module.GattCommunicationStatus = SimpleNamespace(SUCCESS=success)  # type: ignore[attr-defined]
    gatt_module.GattWriteOption = SimpleNamespace(  # type: ignore[attr-defined]
        WRITE_WITH_RESPONSE=write_with_response
    )
    streams_module = ModuleType("winrt.windows.storage.streams")
    streams_module.DataWriter = FakeWriter  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        gatt_module,
    )
    monkeypatch.setitem(sys.modules, "winrt.windows.storage.streams", streams_module)

    transport = AncsTransport()
    transport._control_point = FakeControlPoint()
    transport._ready.set()

    asyncio.run(transport.write_control_point(request))


def test_enqueue_reads_winrt_buffer_as_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = bytes.fromhex("0005040278563412")
    winrt_buffer = object()

    class FakeReader:
        unconsumed_buffer_length = len(expected)

        def read_buffer(self, length: int) -> bytes:
            assert length == len(expected)
            return expected

        def read_bytes(self, _value: object) -> None:
            raise AssertionError("read_bytes is a FillArray API and must not receive a length")

    class FakeDataReader:
        @staticmethod
        def from_buffer(value: object) -> FakeReader:
            assert value is winrt_buffer
            return FakeReader()

    streams_module = ModuleType("winrt.windows.storage.streams")
    streams_module.DataReader = FakeDataReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "winrt.windows.storage.streams", streams_module)

    events: list[RawAncsEvent] = []
    transport = AncsTransport()
    transport._accept_events = True
    transport._loop = SimpleNamespace(
        call_soon_threadsafe=lambda callback, event: callback(event)
    )
    monkeypatch.setattr(transport, "_put_event", events.append)

    transport._enqueue(
        RawEventKind.NOTIFICATION_SOURCE,
        SimpleNamespace(characteristic_value=winrt_buffer),
    )

    assert events == [RawAncsEvent(RawEventKind.NOTIFICATION_SOURCE, expected)]
