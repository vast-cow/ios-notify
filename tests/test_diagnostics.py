from ios_notify.windows.diagnostics import _notifier_setting


def test_notifier_setting_reports_unavailable_winrt_property() -> None:
    class FakeNotifier:
        @property
        def setting(self) -> object:
            raise OSError(-2147023728, "Element not found")

    setting = _notifier_setting(FakeNotifier())

    assert setting.startswith("unavailable (")
    assert "Element not found" in setting


def test_notifier_setting_uses_enum_name() -> None:
    class FakeSetting:
        name = "ENABLED"

    class FakeNotifier:
        setting = FakeSetting()

    assert _notifier_setting(FakeNotifier()) == "ENABLED"
