# iOS Notify

A resident Windows 11 application that reads notifications from a paired
iPhone through Apple's Notification Center Service (ANCS) and displays them
as native Windows toasts.

## Prerequisites

1. Use **Phone Link** once to pair the iPhone with Windows.
2. Enable **Share System Notifications** for the PC in the iPhone's Bluetooth
   settings.
3. Disable Phone Link's notification display to prevent duplicates.
4. Install Python 3.11 or newer on Windows 11.

## Install and run

```powershell
py -m pip install .
ios-notify
```

The program checks paired Bluetooth LE devices for ANCS; it does not advertise,
scan for nearby devices, or perform pairing. It retains a GATT session and uses
uncached discovery so stale Windows service interfaces are not selected. Run
with `--verbose` for debug logging. Bluetooth failures are retried with bounded
exponential backoff.

Notification app icons are resolved from the notification's bundle identifier
using Apple's public App Store metadata and cached under
`%LOCALAPPDATA%\ios-notify\icons`. On a cache miss, notification display waits
briefly for the icon; if the lookup takes longer, the toast is shown without it
while the download continues in the background for subsequent notifications.
System, private, and region-restricted apps that cannot be resolved are shown
without a per-notification icon.

To inspect paired endpoints, ANCS interfaces, access status, and an uncached
device-level ANCS query without starting notification or toast workers, run:

```powershell
ios-notify --diagnose
```

The diagnostic report also checks the registered Windows notification identity
and notification permission. To test Windows toast delivery independently of
Bluetooth and ANCS, run:

```powershell
ios-notify --test-toast
```

## Development

The protocol and parser modules do not import WinRT, so their tests work on
any platform:

```console
python -m pytest
```
