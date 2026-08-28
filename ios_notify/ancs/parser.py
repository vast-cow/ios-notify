from dataclasses import dataclass
from datetime import datetime
from struct import unpack_from

from ios_notify.ancs.protocol import CommandID, NotificationAttributeID
from ios_notify.models import EventType, NotificationEvent


class ProtocolError(ValueError):
    """Raised for a malformed ANCS packet."""


def parse_notification_source(data: bytes) -> NotificationEvent:
    if len(data) != 8:
        raise ProtocolError(f"notification source packet must be 8 bytes, got {len(data)}")
    try:
        event = EventType(data[0])
    except ValueError as error:
        raise ProtocolError(f"unknown event id {data[0]}") from error
    return NotificationEvent(event, data[1], data[2], data[3], unpack_from("<I", data, 4)[0])


def parse_ancs_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None


@dataclass(slots=True, frozen=True)
class NotificationAttributes:
    uid: int
    values: dict[NotificationAttributeID, str]


class NotificationAttributeParser:
    """Incrementally reassemble one fragmented notification response."""

    def __init__(self, expected: tuple[NotificationAttributeID, ...]) -> None:
        self._expected = expected
        self._buffer = bytearray()
        self._uid: int | None = None
        self._values: dict[NotificationAttributeID, str] = {}

    def feed(self, fragment: bytes) -> NotificationAttributes | None:
        self._buffer.extend(fragment)
        if self._uid is None:
            if len(self._buffer) < 5:
                return None
            if self._buffer[0] != CommandID.GET_NOTIFICATION_ATTRIBUTES:
                raise ProtocolError("unexpected data source command")
            self._uid = unpack_from("<I", self._buffer, 1)[0]
            del self._buffer[:5]

        while len(self._values) < len(self._expected):
            if len(self._buffer) < 3:
                return None
            raw_id = self._buffer[0]
            length = unpack_from("<H", self._buffer, 1)[0]
            if len(self._buffer) < 3 + length:
                return None
            try:
                attribute = NotificationAttributeID(raw_id)
            except ValueError as error:
                raise ProtocolError(f"unknown notification attribute {raw_id}") from error
            expected = self._expected[len(self._values)]
            if attribute != expected:
                raise ProtocolError(f"expected attribute {expected}, got {attribute}")
            value = bytes(self._buffer[3 : 3 + length]).decode("utf-8", errors="replace")
            del self._buffer[: 3 + length]
            self._values[attribute] = value

        if self._buffer:
            raise ProtocolError("trailing bytes after notification response")
        return NotificationAttributes(self._uid, dict(self._values))


class AppAttributeParser:
    """Incrementally reassemble a Get App Attributes display-name response."""

    def __init__(self, expected_app_id: str) -> None:
        self.expected_app_id = expected_app_id
        self._buffer = bytearray()

    def feed(self, fragment: bytes) -> str | None:
        self._buffer.extend(fragment)
        if not self._buffer or self._buffer[0] != CommandID.GET_APP_ATTRIBUTES:
            if self._buffer:
                raise ProtocolError("unexpected data source command")
            return None
        end = self._buffer.find(0, 1)
        if end < 0 or len(self._buffer) < end + 4:
            return None
        app_id = bytes(self._buffer[1:end]).decode("utf-8", errors="replace")
        if app_id != self.expected_app_id:
            raise ProtocolError(f"response for unexpected app id {app_id}")
        if self._buffer[end + 1] != 0:
            raise ProtocolError("unexpected app attribute")
        length = unpack_from("<H", self._buffer, end + 2)[0]
        value_start = end + 4
        if len(self._buffer) < value_start + length:
            return None
        if len(self._buffer) != value_start + length:
            raise ProtocolError("trailing bytes after app response")
        return bytes(self._buffer[value_start:]).decode("utf-8", errors="replace")
