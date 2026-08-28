from __future__ import annotations

import asyncio
import logging
from collections import deque

from ios_notify.ancs.app_cache import AppNameCache
from ios_notify.ancs.parser import (
    AppAttributeParser,
    NotificationAttributeParser,
    parse_ancs_date,
    parse_notification_source,
)
from ios_notify.ancs.protocol import (
    DEFAULT_ATTRIBUTES,
    NotificationAttributeID,
    app_attributes_request,
    notification_attributes_request,
)
from ios_notify.ancs.transport import AncsTransport, RawEventKind
from ios_notify.models import EventType, IOSNotification

LOGGER = logging.getLogger(__name__)


class AncsClient:
    def __init__(self, transport: AncsTransport, queue_size: int = 256) -> None:
        self.transport = transport
        self.notification_queue: asyncio.Queue[IOSNotification] = asyncio.Queue(queue_size)
        self.app_cache = AppNameCache()
        self._pending_sources: deque[bytes] = deque()

    async def _response(self, parser: object) -> object:
        while True:
            event = await self.transport.raw_event_queue.get()
            if event.kind == RawEventKind.DISCONNECTED:
                self.app_cache.clear()
                raise ConnectionError("ANCS disconnected while awaiting response")
            if event.kind == RawEventKind.NOTIFICATION_SOURCE:
                # Preserve new events until the single-flight request completes.
                self._pending_sources.append(event.data)
                continue
            result = parser.feed(event.data)
            if result is not None:
                return result

    async def _app_name(self, app_id: str) -> str | None:
        cached = self.app_cache.get(app_id)
        if cached is not None:
            return cached
        await self.transport.write_control_point(app_attributes_request(app_id))
        name = await self._response(AppAttributeParser(app_id))
        self.app_cache.put(app_id, name)
        return name

    async def _expand(self, source: bytes) -> IOSNotification:
        event = parse_notification_source(source)
        if event.event == EventType.REMOVED:
            return IOSNotification(
                uid=event.uid, event=event.event, category=event.category, flags=event.flags
            )
        await self.transport.write_control_point(notification_attributes_request(event.uid))
        expected = tuple(attribute for attribute, _length in DEFAULT_ATTRIBUTES)
        response = await self._response(NotificationAttributeParser(expected))
        values = response.values
        app_id = values.get(NotificationAttributeID.APP_IDENTIFIER)
        app_name = await self._app_name(app_id) if app_id else None
        return IOSNotification(
            uid=event.uid,
            event=event.event,
            app_id=app_id,
            app_name=app_name,
            title=values.get(NotificationAttributeID.TITLE),
            subtitle=values.get(NotificationAttributeID.SUBTITLE),
            message=values.get(NotificationAttributeID.MESSAGE),
            category=event.category,
            flags=event.flags,
            date=parse_ancs_date(values.get(NotificationAttributeID.DATE, "")),
        )

    async def run(self) -> None:
        while True:
            if self._pending_sources:
                source = self._pending_sources.popleft()
                kind = RawEventKind.NOTIFICATION_SOURCE
            else:
                raw = await self.transport.raw_event_queue.get()
                source, kind = raw.data, raw.kind
            if kind == RawEventKind.DISCONNECTED:
                self.app_cache.clear()
                continue
            if kind != RawEventKind.NOTIFICATION_SOURCE:
                LOGGER.warning("discarding unsolicited Data Source packet")
                continue
            try:
                await self.notification_queue.put(await self._expand(source))
            except ConnectionError:
                LOGGER.warning("notification interrupted by disconnect")
            except Exception:
                LOGGER.exception("failed to process ANCS notification")
