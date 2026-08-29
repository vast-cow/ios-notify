from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def default_cache_directory() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "ios-notify" / "icons"
    return Path.home() / ".cache" / "ios-notify" / "icons"


class IconCache:
    """Persistent, bundle-ID-keyed PNG and negative-result cache."""

    def __init__(
        self, directory: Path | None = None, negative_ttl: float = 86400
    ) -> None:
        self.directory = directory or default_cache_directory()
        self.negative_ttl = negative_ttl
        self._negative_file = self.directory / "negative.json"

    def _path(self, app_id: str) -> Path:
        name = hashlib.sha256(app_id.encode("utf-8")).hexdigest()
        return self.directory / f"{name}.png"

    def get(self, app_id: str) -> Path | None:
        path = self._path(app_id)
        try:
            if path.is_file() and path.read_bytes().startswith(PNG_SIGNATURE):
                return path
        except OSError:
            return None
        return None

    def put(self, app_id: str, data: bytes) -> Path:
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError("icon provider returned data that is not a PNG")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(app_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        self.clear_negative(app_id)
        return path

    def is_negative(self, app_id: str) -> bool:
        failed_at = self._read_negative().get(app_id)
        return failed_at is not None and time.time() - failed_at < self.negative_ttl

    def mark_negative(self, app_id: str) -> None:
        failures = self._read_negative()
        failures[app_id] = time.time()
        self._write_negative(failures)

    def clear_negative(self, app_id: str) -> None:
        failures = self._read_negative()
        if failures.pop(app_id, None) is not None:
            self._write_negative(failures)

    def _read_negative(self) -> dict[str, float]:
        try:
            value = json.loads(self._negative_file.read_text(encoding="utf-8"))
            return {str(key): float(timestamp) for key, timestamp in value.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _write_negative(self, failures: dict[str, float]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self._negative_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(failures, sort_keys=True), encoding="utf-8")
        temporary.replace(self._negative_file)
