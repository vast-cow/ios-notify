class AppNameCache:
    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def get(self, app_id: str) -> str | None:
        return self._names.get(app_id)

    def put(self, app_id: str, name: str) -> None:
        self._names[app_id] = name

    def clear(self) -> None:
        self._names.clear()
