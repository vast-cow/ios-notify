from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from ios_notify.icons.cache import IconCache

LOGGER = logging.getLogger(__name__)


class IconProvider(Protocol):
    async def fetch_icon(self, app_id: str) -> bytes | None: ...


class IconResolver:
    def __init__(self, cache: IconCache, providers: tuple[IconProvider, ...]) -> None:
        self.cache = cache
        self.providers = providers
        self._pending: dict[str, asyncio.Task[Path | None]] = {}

    def get_cached(self, app_id: str | None) -> Path | None:
        return self.cache.get(app_id) if app_id else None

    async def resolve(self, app_id: str | None) -> Path | None:
        if not app_id:
            return None
        cached = self.cache.get(app_id)
        if cached or self.cache.is_negative(app_id):
            return cached
        for provider in self.providers:
            try:
                data = await provider.fetch_icon(app_id)
                if data:
                    return self.cache.put(app_id, data)
            except (OSError, ValueError, TimeoutError):
                LOGGER.debug("icon provider failed for %s", app_id, exc_info=True)
        self.cache.mark_negative(app_id)
        return None

    def prefetch(
        self, app_id: str | None
    ) -> asyncio.Task[Path | None] | None:
        if not app_id or self.get_cached(app_id) or self.cache.is_negative(app_id):
            return None
        existing = self._pending.get(app_id)
        if existing and not existing.done():
            return existing
        task = asyncio.create_task(self.resolve(app_id), name=f"icon: {app_id}")
        self._pending[app_id] = task
        task.add_done_callback(lambda completed: self._finished(app_id, completed))
        return task

    def _finished(self, app_id: str, task: asyncio.Task[Path | None]) -> None:
        if self._pending.get(app_id) is task:
            self._pending.pop(app_id, None)
        if not task.cancelled() and task.exception():
            LOGGER.warning(
                "unexpected icon resolution failure for %s: %s",
                app_id,
                task.exception(),
            )
