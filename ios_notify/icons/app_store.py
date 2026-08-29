from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request


def _png_artwork_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = parts.path.rsplit(".", 1)[0] + ".png"
    return urllib.parse.urlunsplit(parts._replace(path=path))


class AppStoreIconProvider:
    """Resolve public App Store artwork without blocking notification delivery."""

    def __init__(self, country: str | None = None, timeout: float = 5.0) -> None:
        self.country = country
        self.timeout = timeout

    async def fetch_icon(self, app_id: str) -> bytes | None:
        return await asyncio.to_thread(self._fetch, app_id)

    def _fetch(self, app_id: str) -> bytes | None:
        query = {"bundleId": app_id, "entity": "software", "limit": "1"}
        if self.country:
            query["country"] = self.country
        lookup_url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            lookup_url, headers={"User-Agent": "ios-notify/0.1"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        results = payload.get("results", [])
        if not results:
            return None
        artwork_url = results[0].get("artworkUrl100") or results[0].get("artworkUrl512")
        if not artwork_url:
            return None
        # The artwork endpoint supports an explicit PNG suffix; the metadata URL
        # commonly defaults to JPEG even when its source asset is a PNG.
        request = urllib.request.Request(
            _png_artwork_url(artwork_url),
            headers={"User-Agent": "ios-notify/0.1"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()
