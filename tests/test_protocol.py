from ios_notify.ancs.protocol import app_attributes_request, notification_attributes_request


def test_notification_request_contains_lengths() -> None:
    assert notification_attributes_request(0x12345678).hex() == (
        "00785634120001800002800003000205"
    )


def test_app_request_is_null_terminated() -> None:
    assert app_attributes_request("com.apple.MobileSMS") == (
        b"\x01com.apple.MobileSMS\x00\x00"
    )
