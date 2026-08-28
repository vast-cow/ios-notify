from enum import IntEnum
from struct import pack


class CommandID(IntEnum):
    GET_NOTIFICATION_ATTRIBUTES = 0
    GET_APP_ATTRIBUTES = 1
    PERFORM_NOTIFICATION_ACTION = 2


class NotificationAttributeID(IntEnum):
    APP_IDENTIFIER = 0
    TITLE = 1
    SUBTITLE = 2
    MESSAGE = 3
    MESSAGE_SIZE = 4
    DATE = 5
    POSITIVE_ACTION_LABEL = 6
    NEGATIVE_ACTION_LABEL = 7


class AppAttributeID(IntEnum):
    DISPLAY_NAME = 0


DEFAULT_ATTRIBUTES = (
    (NotificationAttributeID.APP_IDENTIFIER, None),
    (NotificationAttributeID.TITLE, 128),
    (NotificationAttributeID.SUBTITLE, 128),
    (NotificationAttributeID.MESSAGE, 512),
    (NotificationAttributeID.DATE, None),
)


def notification_attributes_request(
    uid: int,
    attributes: tuple[tuple[NotificationAttributeID, int | None], ...] = DEFAULT_ATTRIBUTES,
) -> bytes:
    request = bytearray((CommandID.GET_NOTIFICATION_ATTRIBUTES,))
    request.extend(pack("<I", uid))
    for attribute, maximum_length in attributes:
        request.append(attribute)
        if attribute in {
            NotificationAttributeID.TITLE,
            NotificationAttributeID.SUBTITLE,
            NotificationAttributeID.MESSAGE,
        }:
            if maximum_length is None:
                raise ValueError(f"maximum length required for {attribute.name}")
            request.extend(pack("<H", maximum_length))
    return bytes(request)


def app_attributes_request(app_id: str) -> bytes:
    if not app_id or "\0" in app_id:
        raise ValueError("app_id must be a non-empty null-free string")
    return bytes((CommandID.GET_APP_ATTRIBUTES,)) + app_id.encode() + b"\0" + bytes(
        (AppAttributeID.DISPLAY_NAME,)
    )
