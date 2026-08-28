import sys
from types import ModuleType, SimpleNamespace

import pytest

from ios_notify.ancs.transport import AncsTransport, RawAncsEvent, RawEventKind


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
