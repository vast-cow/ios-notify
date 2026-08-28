from struct import pack

from ios_notify.ancs.parser import AppAttributeParser, NotificationAttributeParser, parse_ancs_date
from ios_notify.ancs.protocol import NotificationAttributeID as Attribute


def _attribute(attribute: Attribute, value: str) -> bytes:
    encoded = value.encode()
    return bytes((attribute,)) + pack("<H", len(encoded)) + encoded


def test_reassembles_fragmented_notification_attributes() -> None:
    packet = b"\x00" + pack("<I", 42)
    packet += _attribute(Attribute.APP_IDENTIFIER, "com.example")
    packet += _attribute(Attribute.TITLE, "A title")
    parser = NotificationAttributeParser((Attribute.APP_IDENTIFIER, Attribute.TITLE))

    assert parser.feed(packet[:7]) is None
    assert parser.feed(packet[7:14]) is None
    response = parser.feed(packet[14:])

    assert response is not None
    assert response.uid == 42
    assert response.values[Attribute.TITLE] == "A title"


def test_reassembles_fragmented_app_name() -> None:
    packet = b"\x01com.example\x00\x00\x07\x00Example"
    parser = AppAttributeParser("com.example")
    assert parser.feed(packet[:8]) is None
    assert parser.feed(packet[8:]) == "Example"


def test_parses_ancs_date_and_tolerates_invalid_date() -> None:
    assert parse_ancs_date("20260828T123456").year == 2026
    assert parse_ancs_date("not-a-date") is None
