from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Config:
    gatt_timeout: float = 15.0
    queue_size: int = 256
