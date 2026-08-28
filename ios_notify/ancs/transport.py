from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum, auto

from ios_notify.constants import ANCS_SERVICE, BACKOFF_SECONDS, CONTROL_POINT, DATA_SOURCE, GATT_TIMEOUT, NOTIFICATION_SOURCE
from ios_notify.windows.device_discovery import find_paired_ble_devices

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
    session_id: int = 0


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
        self._accept_events = False
        self._session_id = 0

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def write_control_point(
        self, request: bytes, session_id: int | None = None
    ) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus, GattWriteOption
        from winrt.windows.storage.streams import DataWriter

        await self.wait_ready()
        if session_id is not None and session_id != self._session_id:
            raise ConnectionError("ANCS session changed before control point write")
        if self._control_point is None:
            raise ConnectionError("ANCS control point is not connected")
        writer = DataWriter()
        writer.write_bytes(request)
        async with asyncio.timeout(self.timeout):
            status = await self._control_point.write_value_with_option_async(
                writer.detach_buffer(), GattWriteOption.WRITE_WITH_RESPONSE
            )
        if status != GattCommunicationStatus.SUCCESS:
            raise ConnectionError(f"control point write failed: {status}")

    def _put_event(self, event: RawAncsEvent) -> None:
        try:
            self.raw_event_queue.put_nowait(event)
        except asyncio.QueueFull:
            LOGGER.warning("dropping ANCS event because the raw queue is full")

    def _enqueue(
        self, kind: RawEventKind, args: object, session_id: int | None = None
    ) -> None:
        from winrt.windows.storage.streams import DataReader

        session_id = self._session_id if session_id is None else session_id
        if not self._accept_events or session_id != self._session_id:
            return
        reader = DataReader.from_buffer(args.characteristic_value)
        data = bytes(reader.read_buffer(reader.unconsumed_buffer_length))
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                self._put_event, RawAncsEvent(kind, data, session_id)
            )

    def _on_data_source(self, _sender: object, args: object) -> None:
        self._enqueue(RawEventKind.DATA_SOURCE, args)

    def _on_notification_source(self, _sender: object, args: object) -> None:
        self._enqueue(RawEventKind.NOTIFICATION_SOURCE, args)

    def _on_connection_changed(self, sender: object, _args: object) -> None:
        if int(sender.connection_status) == 0 and self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnect.set)

    def _on_services_changed(self, _sender: object, _args: object) -> None:
        LOGGER.info("GATT services changed; rediscovering ANCS")
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnect.set)

    def _on_session_status_changed(self, sender: object, _args: object) -> None:
        # GattSessionStatus.CLOSED has integer value 0.
        if int(sender.session_status) == 0 and self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnect.set)

    async def _characteristic(self, service: object, uuid: object, required: int) -> object:
        from winrt.windows.devices.bluetooth import BluetoothCacheMode
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus

        async with asyncio.timeout(self.timeout):
            result = await service.get_characteristics_for_uuid_with_cache_mode_async(uuid, BluetoothCacheMode.UNCACHED)
        if result.status != GattCommunicationStatus.SUCCESS or not result.characteristics:
            raise ConnectionError(
                f"ANCS characteristic unavailable: {uuid}; status={result.status}; "
                f"protocol_error={getattr(result, 'protocol_error', None)}"
            )
        characteristic = result.characteristics[0]
        if not int(characteristic.characteristic_properties) & required:
            raise ConnectionError(f"ANCS characteristic {uuid} has incompatible properties")
        return characteristic

    async def _subscribe(self, characteristic: object, callback: object) -> object:
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattClientCharacteristicConfigurationDescriptorValue as Cccd, GattCommunicationStatus

        token = characteristic.add_value_changed(callback)
        try:
            async with asyncio.timeout(self.timeout):
                status = await characteristic.write_client_characteristic_configuration_descriptor_async(Cccd.NOTIFY)
            if status != GattCommunicationStatus.SUCCESS:
                raise ConnectionError(f"ANCS subscription failed: {status}")
        except BaseException:
            characteristic.remove_value_changed(token)
            raise
        return token

    async def _query_ancs(self, device: object) -> tuple[object | None, str]:
        from winrt.windows.devices.bluetooth import BluetoothCacheMode
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus

        for attempt in range(4):
            async with asyncio.timeout(self.timeout):
                result = await device.get_gatt_services_for_uuid_with_cache_mode_async(ANCS_SERVICE, BluetoothCacheMode.UNCACHED)
            if result.status == GattCommunicationStatus.SUCCESS:
                if not result.services:
                    return None, "ANCS is not currently published"
                selected, *unused = result.services
                for service in unused:
                    service.close()
                return selected, ""
            detail = f"status={result.status}; protocol_error={getattr(result, 'protocol_error', None)}"
            if result.status != GattCommunicationStatus.UNREACHABLE:
                return None, detail
            if attempt < 3:
                await asyncio.sleep(1)
        return None, detail

    async def _open_ancs_device(
        self,
    ) -> tuple[object, object, object, list[tuple[object, str, object]]]:
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattSession
        from winrt.windows.devices.enumeration import DeviceAccessStatus

        candidates = await find_paired_ble_devices()
        if not candidates:
            raise ConnectionError("no paired Bluetooth LE devices were found")
        failures: list[str] = []
        for candidate in candidates:
            LOGGER.debug(
                "trying BLE endpoint name=%r enabled=%s paired=%s id=%s",
                candidate.name,
                candidate.is_enabled,
                candidate.is_paired,
                candidate.id,
            )
            if not candidate.is_enabled:
                LOGGER.debug(
                    "BLE endpoint %r reports is_enabled=False; trying it anyway",
                    candidate.name,
                )
            device = session = service = None
            registrations: list[tuple[object, str, object]] = []
            try:
                try:
                    device = await BluetoothLEDevice.from_id_async(candidate.id)
                except Exception as exc:
                    failures.append(
                        f"{candidate.name}: BluetoothLEDevice.from_id_async failed: {exc!r}"
                    )
                    continue
                if device is None:
                    failures.append(f"{candidate.name}: BluetoothLEDevice.from_id_async returned None")
                    continue
                access = await device.request_access_async()
                if access != DeviceAccessStatus.ALLOWED:
                    failures.append(f"{candidate.name}: access={access}")
                    continue
                session = await GattSession.from_device_id_async(device.bluetooth_device_id)
                if session is None:
                    failures.append(f"{candidate.name}: could not create GATT session")
                    continue
                registrations.extend(
                    [
                        (
                            device,
                            "connection_status_changed",
                            device.add_connection_status_changed(
                                self._on_connection_changed
                            ),
                        ),
                        (
                            device,
                            "gatt_services_changed",
                            device.add_gatt_services_changed(self._on_services_changed),
                        ),
                        (
                            session,
                            "session_status_changed",
                            session.add_session_status_changed(
                                self._on_session_status_changed
                            ),
                        ),
                    ]
                )
                if session.can_maintain_connection:
                    session.maintain_connection = True
                service, reason = await self._query_ancs(device)
                if service is None:
                    failures.append(f"{candidate.name}: {reason}")
                    continue
                return device, session, service, registrations
            finally:
                if service is None:
                    for owner, event, token in reversed(registrations):
                        getattr(owner, f"remove_{event}")(token)
                    if session is not None:
                        if session.can_maintain_connection:
                            session.maintain_connection = False
                        session.close()
                    if device is not None:
                        device.close()
        raise ConnectionError("Unable to open ANCS from paired BLE devices:\n- " + "\n- ".join(failures))

    async def _connect_once(self) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCharacteristicProperties as Props

        self._ready.clear()
        self._disconnect.clear()
        self._control_point = None
        self._accept_events = False
        device = session = service = None
        session_id = 0
        registrations: list[tuple[object, str, object]] = []
        subscriptions: list[tuple[object, object]] = []
        self.state = TransportState.DISCOVERING
        try:
            device, session, service, registrations = await self._open_ancs_device()
            self.state = TransportState.OPENING
            self.state = TransportState.SUBSCRIBING
            data_source = await self._characteristic(service, DATA_SOURCE, int(Props.NOTIFY))
            notification_source = await self._characteristic(service, NOTIFICATION_SOURCE, int(Props.NOTIFY))
            control_point = await self._characteristic(
                service, CONTROL_POINT, int(Props.WRITE)
            )
            self._session_id += 1
            session_id = self._session_id
            self._control_point = control_point
            # ANCS can deliver pre-existing notifications during the CCCD write.
            # Accept callbacks before subscribing so those packets are not lost.
            self._accept_events = True

            def data_callback(_sender: object, args: object) -> None:
                self._enqueue(RawEventKind.DATA_SOURCE, args, session_id)

            def notification_callback(_sender: object, args: object) -> None:
                self._enqueue(RawEventKind.NOTIFICATION_SOURCE, args, session_id)

            token = await self._subscribe(data_source, data_callback)
            subscriptions.append((data_source, token))
            token = await self._subscribe(notification_source, notification_callback)
            subscriptions.append((notification_source, token))
            self.state = TransportState.READY
            self._ready.set()
            LOGGER.info("connected to iPhone ANCS")
            await self._disconnect.wait()
        finally:
            self._ready.clear()
            self._accept_events = False
            self._control_point = None
            for characteristic, token in reversed(subscriptions):
                characteristic.remove_value_changed(token)
            for owner, event, token in reversed(registrations):
                getattr(owner, f"remove_{event}")(token)
            if session is not None:
                if session.can_maintain_connection:
                    session.maintain_connection = False
            if service is not None:
                service.close()
            if session is not None:
                session.close()
            if device is not None:
                device.close()
            if session_id:
                self._put_event(
                    RawAncsEvent(
                        RawEventKind.DISCONNECTED, session_id=session_id
                    )
                )

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        attempt = 0
        while True:
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
