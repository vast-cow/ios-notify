from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum


class EventType(IntEnum):
    ADDED = 0
    MODIFIED = 1
    REMOVED = 2


@dataclass(slots=True, frozen=True)
class NotificationEvent:
    event: EventType
    flags: int
    category: int
    category_count: int
    uid: int


@dataclass(slots=True)
class IOSNotification:
    uid: int
    event: EventType
    app_id: str | None = None
    app_name: str | None = None
    title: str | None = None
    subtitle: str | None = None
    message: str | None = None
    category: int = 0
    flags: int = 0
    date: datetime | None = None
