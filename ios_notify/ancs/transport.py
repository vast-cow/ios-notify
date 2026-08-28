from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum, auto

from ios_notify.constants import (
    ANCS_SERVICE,
    BACKOFF_SECONDS,
    CONTROL_POINT,
    DATA_SOURCE,
    GATT_TIMEOUT,
    NOTIFICATION_SOURCE,
)
from ios_notify.windows.device_discovery import find_service_ids

LOGGER = logging.getLogger(__name__)


class TransportState(Enum):
    DISCONNECTED = auto()
    DISCOVERING = auto()
    OPENING = auto()
    SUBSCRIBING = auto()
    READY = auto()
    BACKOFF = auto()


class RawEventKind(Enum):
    NOTIFICATION_SOURCE = auto()
    DATA_SOURCE = auto()
    DISCONNECTED = auto()


@dataclass(slots=True, frozen=True)
class RawAncsEvent:
    kind: RawEventKind
    data: bytes = b""


class AncsTransport:
    """Own the WinRT GATT objects and enqueue callback data without parsing it."""

    def __init__(self, queue_size: int = 256, timeout: float = GATT_TIMEOUT) -> None:
        self.raw_event_queue: asyncio.Queue[RawAncsEvent] = asyncio.Queue(queue_size)
        self.state = TransportState.DISCONNECTED
        self.timeout = timeout
        self._control_point = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = asyncio.Event()
        self._disconnect = asyncio.Event()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def write_control_point(self, request: bytes) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattCommunicationStatus,
            GattWriteOption,
        )
        from winrt.windows.storage.streams import DataWriter

        await self.wait_ready()
        if self._control_point is None:
            raise ConnectionError("ANCS control point is not connected")
        writer = DataWriter()
        writer.write_bytes(request)
        async with asyncio.timeout(self.timeout):
            status = await self._control_point.write_value_async(
                writer.detach_buffer(), GattWriteOption.WRITE_WITH_RESPONSE
            )
        if status != GattCommunicationStatus.SUCCESS:
            raise ConnectionError(f"control point write failed: {status}")

    def _enqueue(self, kind: RawEventKind, args: object) -> None:
        from winrt.windows.storage.streams import DataReader

        reader = DataReader.from_buffer(args.characteristic_value)
        data = bytes(reader.read_bytes(reader.unconsumed_buffer_length))
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                self.raw_event_queue.put_nowait, RawAncsEvent(kind, data)
            )

    def _on_data_source(self, _sender: object, args: object) -> None:
        self._enqueue(RawEventKind.DATA_SOURCE, args)

    def _on_notification_source(self, _sender: object, args: object) -> None:
        self._enqueue(RawEventKind.NOTIFICATION_SOURCE, args)

    def _on_connection_changed(self, sender: object, _args: object) -> None:
        # BluetoothConnectionStatus.DISCONNECTED has integer value 0.
        if int(sender.connection_status) == 0 and self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnect.set)

    async def _characteristic(self, service: object, uuid: object) -> object:
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus

        async with asyncio.timeout(self.timeout):
            result = await service.get_characteristics_for_uuid_async(uuid)
        if result.status != GattCommunicationStatus.SUCCESS or not result.characteristics:
            raise ConnectionError(f"ANCS characteristic unavailable: {uuid}")
        return result.characteristics[0]

    async def _subscribe(self, characteristic: object, callback: object) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattClientCharacteristicConfigurationDescriptorValue as Cccd,
            GattCommunicationStatus,
        )

        characteristic.add_value_changed(callback)
        async with asyncio.timeout(self.timeout):
            status = await characteristic.write_client_characteristic_configuration_descriptor_async(
                Cccd.NOTIFY
            )
        if status != GattCommunicationStatus.SUCCESS:
            raise ConnectionError(f"ANCS subscription failed: {status}")

    async def _connect_once(self) -> None:
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattDeviceService,
            GattOpenStatus,
            GattSharingMode,
        )
        from winrt.windows.devices.enumeration import DeviceAccessStatus

        self.state = TransportState.DISCOVERING
        async with asyncio.timeout(self.timeout):
            service_ids = await find_service_ids(ANCS_SERVICE)
        if not service_ids:
            raise ConnectionError("no bonded iPhone exposing ANCS was found")

        self.state = TransportState.OPENING
        async with asyncio.timeout(self.timeout):
            service = await GattDeviceService.from_id_async(service_ids[0])
        if service is None:
            raise ConnectionError("could not create the ANCS GATT service")
        access = await service.request_access_async()
        if access != DeviceAccessStatus.ALLOWED:
            service.close()
            raise PermissionError(f"ANCS access denied: {access}")
        async with asyncio.timeout(self.timeout):
            opened = await service.open_async(GattSharingMode.SHARED_READ_AND_WRITE)
        if opened.status != GattOpenStatus.SUCCESS:
            service.close()
            raise ConnectionError(f"could not open ANCS service: {opened.status}")

        device = await BluetoothLEDevice.from_id_async(service.device_id)
        device.add_connection_status_changed(self._on_connection_changed)
        self.state = TransportState.SUBSCRIBING
        # Uncached lookup and Data Source first ensure no event response is missed.
        data_source = await self._characteristic(service, DATA_SOURCE)
        notification_source = await self._characteristic(service, NOTIFICATION_SOURCE)
        self._control_point = await self._characteristic(service, CONTROL_POINT)
        await self._subscribe(data_source, self._on_data_source)
        await self._subscribe(notification_source, self._on_notification_source)
        self.state = TransportState.READY
        self._ready.set()
        LOGGER.info("connected to iPhone ANCS")
        try:
            await self._disconnect.wait()
        finally:
            self._ready.clear()
            self._control_point = None
            device.close()
            service.close()
            await self.raw_event_queue.put(RawAncsEvent(RawEventKind.DISCONNECTED))

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        attempt = 0
        while True:
            self._disconnect.clear()
            try:
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("ANCS connection failed")
            self.state = TransportState.BACKOFF
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)
            self.state = TransportState.DISCONNECTED
