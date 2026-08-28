import asyncio
from types import SimpleNamespace

from ios_notify.ancs.client import AncsClient
from ios_notify.ancs.parser import parse_notification_source


def _source(event: int, flags: int, uid: int) -> bytes:
    return bytes((event, flags, 0, 1)) + uid.to_bytes(4, "little")


def test_pre_existing_uid_is_suppressed_until_removed() -> None:
    client = AncsClient(SimpleNamespace(raw_event_queue=asyncio.Queue()))

    assert client._suppress(parse_notification_source(_source(0, 1 << 2, 42)))
    assert client._suppress(parse_notification_source(_source(1, 0, 42)))
    assert client._suppress(parse_notification_source(_source(2, 0, 42)))
    assert not client._suppress(parse_notification_source(_source(0, 0, 42)))


def test_session_reset_clears_pending_suppression_and_app_cache() -> None:
    client = AncsClient(SimpleNamespace(raw_event_queue=asyncio.Queue()))
    client._suppressed_uids.add(42)
    client.app_cache.put("com.example", "Example")

    client._reset_session(7)

    assert client._session_id == 7
    assert not client._suppressed_uids
    assert client.app_cache.get("com.example") is None
