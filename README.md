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

The program discovers an already bonded ANCS service; it does not advertise,
scan for nearby devices, or perform pairing. Run with `--verbose` for debug
logging. Bluetooth failures are retried with bounded exponential backoff.

## Development

The protocol and parser modules do not import WinRT, so their tests work on
any platform:

```console
python -m pytest
```
