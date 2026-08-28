import pytest

from ios_notify.ancs.parser import ProtocolError, parse_notification_source
from ios_notify.models import EventFlag, EventType


def test_parses_notification_source_packet() -> None:
    event = parse_notification_source(bytes.fromhex("0005040278563412"))
    assert event.event is EventType.ADDED
    assert event.flags == 5
    assert event.flags & EventFlag.PRE_EXISTING
    assert event.category == 4
    assert event.category_count == 2
    assert event.uid == 0x12345678


@pytest.mark.parametrize("packet", [b"", b"1234567", b"123456789"])
def test_rejects_wrong_packet_length(packet: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_notification_source(packet)
