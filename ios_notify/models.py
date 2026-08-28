from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, IntFlag


class EventType(IntEnum):
    ADDED = 0
    MODIFIED = 1
    REMOVED = 2


class EventFlag(IntFlag):
    SILENT = 1 << 0
    IMPORTANT = 1 << 1
    PRE_EXISTING = 1 << 2
    POSITIVE_ACTION = 1 << 3
    NEGATIVE_ACTION = 1 << 4


@dataclass(slots=True, frozen=True)
class NotificationEvent:
    event: EventType
    flags: EventFlag
    category: int
    category_count: int
    uid: int


@dataclass(slots=True)
class IOSNotification:
    uid: int
    event: EventType
    session_id: int = 0
    app_id: str | None = None
    app_name: str | None = None
    title: str | None = None
    subtitle: str | None = None
    message: str | None = None
    category: int = 0
    flags: EventFlag = EventFlag(0)
    date: datetime | None = None
