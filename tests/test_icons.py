import asyncio
from pathlib import Path

import pytest

from ios_notify.icons.cache import PNG_SIGNATURE, IconCache
from ios_notify.icons.app_store import _png_artwork_url
from ios_notify.icons.resolver import IconResolver


class FakeProvider:
    def __init__(self, result: bytes | None) -> None:
        self.result = result
        self.calls: list[str] = []

    async def fetch_icon(self, app_id: str) -> bytes | None:
        self.calls.append(app_id)
        return self.result


def test_app_store_artwork_requests_png_without_losing_query() -> None:
    assert _png_artwork_url("https://example.test/icon/100x100.jpg?token=1") == (
        "https://example.test/icon/100x100.png?token=1"
    )


def test_icon_cache_persists_valid_png_by_hashed_app_id(tmp_path: Path) -> None:
    cache = IconCache(tmp_path)
    data = PNG_SIGNATURE + b"image"

    path = cache.put("com.example/app", data)

    assert path.parent == tmp_path
    assert path.name == (
        "4df793bcd27660ce87d32f0edc6eb1c31ce576cc1bf1f0071a55efa19391ab71.png"
    )
    assert cache.get("com.example/app") == path


def test_icon_cache_rejects_non_png(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a PNG"):
        IconCache(tmp_path).put("com.example.app", b"not an image")


def test_resolver_uses_cache_before_provider(tmp_path: Path) -> None:
    cache = IconCache(tmp_path)
    expected = cache.put("com.example.app", PNG_SIGNATURE + b"cached")
    provider = FakeProvider(PNG_SIGNATURE + b"remote")
    resolver = IconResolver(cache, (provider,))

    assert asyncio.run(resolver.resolve("com.example.app")) == expected
    assert provider.calls == []


def test_resolver_negative_caches_missing_icon(tmp_path: Path) -> None:
    provider = FakeProvider(None)
    resolver = IconResolver(IconCache(tmp_path), (provider,))

    assert asyncio.run(resolver.resolve("com.example.missing")) is None
    assert asyncio.run(resolver.resolve("com.example.missing")) is None
    assert provider.calls == ["com.example.missing"]


def test_prefetch_deduplicates_background_resolution(tmp_path: Path) -> None:
    async def exercise() -> tuple[int, Path | None]:
        started = asyncio.Event()
        release = asyncio.Event()

        class WaitingProvider:
            calls = 0

            async def fetch_icon(self, _app_id: str) -> bytes | None:
                self.calls += 1
                started.set()
                await release.wait()
                return PNG_SIGNATURE + b"icon"

        provider = WaitingProvider()
        resolver = IconResolver(IconCache(tmp_path), (provider,))

        first = resolver.prefetch("com.example.app")
        second = resolver.prefetch("com.example.app")
        assert first is second
        await started.wait()
        release.set()
        assert first is not None
        await first
        return provider.calls, resolver.get_cached("com.example.app")

    calls, cached = asyncio.run(exercise())
    assert calls == 1
    assert cached is not None
