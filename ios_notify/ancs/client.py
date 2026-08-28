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
from ios_notify.ancs.transport import AncsTransport, RawAncsEvent, RawEventKind
from ios_notify.models import EventFlag, EventType, IOSNotification, NotificationEvent

LOGGER = logging.getLogger(__name__)


class AncsClient:
    def __init__(self, transport: AncsTransport, queue_size: int = 256) -> None:
        self.transport = transport
        self.notification_queue: asyncio.Queue[IOSNotification] = asyncio.Queue(queue_size)
        self.app_cache = AppNameCache()
        self._pending_sources: deque[RawAncsEvent] = deque()
        self._suppressed_uids: set[int] = set()
        self._session_id = 0

    def _reset_session(self, session_id: int = 0) -> None:
        self._pending_sources.clear()
        self._suppressed_uids.clear()
        self.app_cache.clear()
        self._session_id = session_id

    def _suppress(self, event: NotificationEvent) -> bool:
        if event.flags & EventFlag.PRE_EXISTING:
            self._suppressed_uids.add(event.uid)
            return True
        if event.uid not in self._suppressed_uids:
            return False
        if event.event == EventType.REMOVED:
            self._suppressed_uids.remove(event.uid)
        return True

    async def _response(self, parser: object, session_id: int) -> object:
        while True:
            event = await self.transport.raw_event_queue.get()
            if event.session_id != session_id:
                if event.session_id > session_id:
                    self._reset_session(event.session_id)
                    if event.kind == RawEventKind.NOTIFICATION_SOURCE:
                        self._pending_sources.append(event)
                    raise ConnectionError("ANCS session changed while awaiting response")
                continue
            if event.kind == RawEventKind.DISCONNECTED:
                self._reset_session()
                raise ConnectionError("ANCS disconnected while awaiting response")
            if event.kind == RawEventKind.NOTIFICATION_SOURCE:
                # Preserve new events until the single-flight request completes.
                self._pending_sources.append(event)
                continue
            result = parser.feed(event.data)
            if result is not None:
                return result

    async def _app_name(self, app_id: str, session_id: int) -> str | None:
        cached = self.app_cache.get(app_id)
        if cached is not None:
            return cached
        await self.transport.write_control_point(
            app_attributes_request(app_id), session_id
        )
        name = await self._response(AppAttributeParser(app_id), session_id)
        self.app_cache.put(app_id, name)
        return name

    async def _expand(
        self, session_id: int, event: NotificationEvent
    ) -> IOSNotification:
        if event.event == EventType.REMOVED:
            return IOSNotification(
                uid=event.uid,
                event=event.event,
                session_id=session_id,
                category=event.category,
                flags=event.flags,
            )
        await self.transport.write_control_point(
            notification_attributes_request(event.uid), session_id
        )
        expected = tuple(attribute for attribute, _length in DEFAULT_ATTRIBUTES)
        response = await self._response(NotificationAttributeParser(expected), session_id)
        values = response.values
        app_id = values.get(NotificationAttributeID.APP_IDENTIFIER)
        app_name = await self._app_name(app_id, session_id) if app_id else None
        return IOSNotification(
            uid=event.uid,
            event=event.event,
            session_id=session_id,
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
                # Prefer transport events so a queued disconnect/session change
                # invalidates pending UIDs before they can be requested.
                try:
                    raw = self.transport.raw_event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    raw = self._pending_sources.popleft()
            else:
                raw = await self.transport.raw_event_queue.get()
            if raw.kind == RawEventKind.DISCONNECTED:
                if raw.session_id == self._session_id:
                    self._reset_session()
                continue
            if raw.session_id < self._session_id:
                continue
            if raw.session_id != self._session_id:
                self._reset_session(raw.session_id)
            if raw.kind != RawEventKind.NOTIFICATION_SOURCE:
                LOGGER.warning("discarding unsolicited Data Source packet")
                continue
            try:
                event = parse_notification_source(raw.data)
                if self._suppress(event):
                    continue
                await self.notification_queue.put(
                    await self._expand(raw.session_id, event)
                )
            except ConnectionError:
                LOGGER.warning("notification interrupted by disconnect")
            except Exception:
                LOGGER.exception("failed to process ANCS notification")
