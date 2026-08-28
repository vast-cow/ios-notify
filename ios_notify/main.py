from __future__ import annotations

# This must precede imports of libraries that can initialize COM. WinRT async
# operations require the resident process to use the multithreaded apartment.
import sys

sys.coinit_flags = 0  # COINIT_MULTITHREADED

import argparse
import asyncio
import platform

from ios_notify.ancs.client import AncsClient
from ios_notify.ancs.transport import AncsTransport
from ios_notify.config import Config
from ios_notify.logging_config import configure_logging
from ios_notify.windows.toast import ToastService


async def main(config: Config | None = None) -> None:
    config = config or Config()
    transport = AncsTransport(queue_size=config.queue_size, timeout=config.gatt_timeout)
    client = AncsClient(transport, queue_size=config.queue_size)
    toast = ToastService(client.notification_queue)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(transport.run(), name="ANCS transport")
        tasks.create_task(client.run(), name="ANCS client")
        tasks.create_task(toast.run(), name="toast service")


def run() -> None:
    parser = argparse.ArgumentParser(description="Forward iPhone notifications to Windows")
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="inspect Windows Bluetooth/ANCS state without starting the client",
    )
    args = parser.parse_args()
    configure_logging(args.verbose)
    if platform.system() != "Windows":
        parser.error("ios-notify requires Windows 11")
    try:
        if args.diagnose:
            from ios_notify.windows.diagnostics import diagnose

            asyncio.run(diagnose())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
