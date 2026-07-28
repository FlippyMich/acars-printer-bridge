"""Ways to reach the printer: BLE (GATT), serial (SPP/COM), file (debug)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

log = logging.getLogger("acars.transport")

# Write characteristics of the most common BLE thermal printers.
KNOWN_WRITE_CHARS = [
    "0000ff02-0000-1000-8000-00805f9b34fb",  # ff00 service (Goojprt/Zjiang/...)
    "00002af1-0000-1000-8000-00805f9b34fb",  # 18f0 service (generic BLE ESC/POS)
    "49535343-8841-43f4-a8d4-ecbe34729bb3",  # Microchip transparent UART (ISSC)
    "0000ffe1-0000-1000-8000-00805f9b34fb",  # HM-10 style modules
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
    "0000abf1-0000-1000-8000-00805f9b34fb",
    "0000ae01-0000-1000-8000-00805f9b34fb",  # cat printer (raster, not ESC/POS)
]

# Standard GATT services to skip while hunting for the right characteristic.
GENERIC_SERVICES = {
    "00001800-0000-1000-8000-00805f9b34fb",
    "00001801-0000-1000-8000-00805f9b34fb",
    "0000180a-0000-1000-8000-00805f9b34fb",
    "0000180f-0000-1000-8000-00805f9b34fb",
    "0000fe59-0000-1000-8000-00805f9b34fb",
}

CAT_NOTIFY_CHAR = "0000ae02-0000-1000-8000-00805f9b34fb"


class PrinterError(RuntimeError):
    pass


class BleTransport:
    """Persistent GATT client with reconnect and printer-driven flow control."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.address: str | None = cfg.get("address")
        self.name_filter: str = cfg.get("name_filter") or ""
        self.char_uuid: str | None = cfg.get("write_char_uuid")
        self.notify_uuid: str | None = cfg.get("notify_char_uuid")
        self.chunk_size = int(cfg.get("chunk_size", 180))
        self.chunk_delay = float(cfg.get("chunk_delay_ms", 20)) / 1000.0
        self.keep_connected = bool(cfg.get("keep_connected", True))
        self.connect_timeout = float(cfg.get("connect_timeout", 20.0))
        self.scan_timeout = float(cfg.get("scan_timeout", 8.0))
        self.device_name: str | None = None
        self._client: BleakClient | None = None
        self._char: BleakGATTCharacteristic | None = None
        self._lock = asyncio.Lock()
        self._resumed = asyncio.Event()
        self._resumed.set()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ------------------------------------------------------------------- lookup
    async def find_device(self) -> BLEDevice:
        if self.address:
            log.info("Looking for the printer at %s...", self.address)
            device = await BleakScanner.find_device_by_address(
                self.address, timeout=self.scan_timeout
            )
            if device:
                return device
            log.warning("Address %s not found, falling back to name lookup.", self.address)

        if not self.name_filter:
            raise PrinterError("No BLE address configured. Run a scan first.")

        needle = self.name_filter.lower()
        log.info("Scanning for a BLE device whose name contains %r...", self.name_filter)
        device = await BleakScanner.find_device_by_filter(
            lambda dev, _adv: bool(dev.name) and needle in dev.name.lower(),
            timeout=self.scan_timeout,
        )
        if not device:
            raise PrinterError(
                f"Printer not found (name filter: {self.name_filter!r}). Switch it on, make "
                "sure no phone app is connected to it, then scan again."
            )
        return device

    # ------------------------------------------------------------------ connect
    def _pick_characteristic(self, client: BleakClient) -> BleakGATTCharacteristic:
        if self.char_uuid:
            char = client.services.get_characteristic(self.char_uuid)
            if char is None:
                raise PrinterError(
                    f"Configured characteristic {self.char_uuid} does not exist on this "
                    "printer. Run a scan to detect it again."
                )
            return char

        writable: list[BleakGATTCharacteristic] = []
        for service in client.services:
            for char in service.characteristics:
                if {"write", "write-without-response"} & set(char.properties):
                    writable.append(char)

        for known in KNOWN_WRITE_CHARS:
            for char in writable:
                if char.uuid.lower() == known:
                    return char

        for char in writable:
            if char.service_uuid.lower() not in GENERIC_SERVICES:
                return char
        if writable:
            return writable[0]
        raise PrinterError("No writable characteristic found on this device.")

    def _pick_notify_uuid(self, client: BleakClient) -> str | None:
        """Characteristic the printer reports pauses and status on (AE02 on cat printers)."""
        if self.notify_uuid:
            return self.notify_uuid
        if self._char is None:
            return None
        if self._char.uuid.lower().startswith("0000ae01"):
            if client.services.get_characteristic(CAT_NOTIFY_CHAR) is not None:
                return CAT_NOTIFY_CHAR
        return None

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        from . import catprinter

        for cmd, payload in catprinter.parse_notification(bytes(data)):
            if cmd == catprinter.CMD_LINE_CONTROL and payload:
                if payload[0] == 0x10:  # XOff: buffer full
                    if self._resumed.is_set():
                        log.debug("Printer buffer full, pausing.")
                    self._resumed.clear()
                elif payload[0] == 0x00:  # XOn
                    self._resumed.set()
            elif cmd == catprinter.CMD_GET_DEV_STATE and payload:
                problems = catprinter.describe_state(payload)
                if problems:
                    log.warning("Printer status: %s", ", ".join(problems))
                else:
                    log.debug("Printer status OK (0x%02x)", payload[0])

    async def _wait_resume(self, timeout: float = 30.0) -> None:
        if self._resumed.is_set():
            return
        try:
            await asyncio.wait_for(self._resumed.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("Printer did not resume within %.0fs, continuing anyway.", timeout)
            self._resumed.set()

    def _on_disconnect(self, _client: BleakClient) -> None:
        log.warning("Printer disconnected.")
        self._client = None
        self._char = None
        self._resumed.set()

    async def connect(self) -> None:
        if self.is_connected:
            return
        device = await self.find_device()
        log.info("Connecting to %s (%s)...", device.name or "?", device.address)
        client = BleakClient(
            device,
            disconnected_callback=self._on_disconnect,
            timeout=self.connect_timeout,
        )
        await client.connect()
        self._client = client
        self._char = self._pick_characteristic(client)
        self.address = device.address
        self.device_name = device.name
        self._resumed.set()

        notify_uuid = self._pick_notify_uuid(client)
        if notify_uuid:
            try:
                await client.start_notify(notify_uuid, self._on_notify)
                log.info("Flow control active on characteristic %s.", notify_uuid)
            except Exception as exc:
                log.warning("Notifications unavailable on %s: %s", notify_uuid, exc)

        log.info(
            "Connected. Write characteristic %s (service %s, props %s, MTU %s)",
            self._char.uuid,
            self._char.service_uuid,
            ",".join(self._char.properties),
            client.mtu_size,
        )

    async def close(self) -> None:
        client, self._client, self._char = self._client, None, None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except Exception as exc:  # best effort
                log.debug("Error while disconnecting: %s", exc)

    # --------------------------------------------------------------------- send
    async def send(self, data: bytes) -> None:
        async with self._lock:
            last_error: Exception | None = None
            for attempt in (1, 2, 3):
                try:
                    await self.connect()
                    await self._write_chunks(data)
                    if not self.keep_connected:
                        await self.close()
                    return
                except Exception as exc:
                    last_error = exc
                    log.warning("Send failed (attempt %d/3): %s", attempt, exc)
                    await self.close()
                    await asyncio.sleep(1.5 * attempt)
            raise PrinterError(f"Could not print: {last_error}")

    async def _write_chunks(self, data: bytes) -> None:
        assert self._client is not None and self._char is not None
        client, char = self._client, self._char

        mtu_limit = max(20, (client.mtu_size or 23) - 3)
        size = max(20, min(self.chunk_size, mtu_limit))
        response = self.cfg.get("write_with_response")
        if response is None:
            response = "write-without-response" not in char.properties

        total = len(data)
        for offset in range(0, total, size):
            await self._wait_resume()
            await client.write_gatt_char(
                char, data[offset : offset + size], response=bool(response)
            )
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)
        log.info("Sent %d bytes to the printer.", total)
        # Give the printer time to drain its buffer before any disconnect.
        await asyncio.sleep(0.4 + total / 6000.0)


class SerialTransport:
    """For printers exposing classic Bluetooth (SPP) on a COM port."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.port = cfg.get("port", "COM5")
        self.baudrate = int(cfg.get("baudrate", 9600))
        self.chunk_size = int(cfg.get("chunk_size", 256))
        self.chunk_delay = float(cfg.get("chunk_delay_ms", 10)) / 1000.0
        self.device_name = self.port
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await asyncio.to_thread(self._probe)
        self._connected = True

    def _probe(self) -> None:
        import serial

        with serial.Serial(self.port, self.baudrate, timeout=2, write_timeout=10):
            pass

    async def send(self, data: bytes) -> None:
        async with self._lock:
            await asyncio.to_thread(self._send_blocking, data)
            log.info("Sent %d bytes on %s.", len(data), self.port)

    def _send_blocking(self, data: bytes) -> None:
        try:
            import serial
        except ImportError as exc:
            raise PrinterError("pyserial is not installed: pip install pyserial") from exc

        import time

        with serial.Serial(self.port, self.baudrate, timeout=2, write_timeout=15) as ser:
            for offset in range(0, len(data), self.chunk_size):
                ser.write(data[offset : offset + self.chunk_size])
                ser.flush()
                if self.chunk_delay:
                    time.sleep(self.chunk_delay)

    async def close(self) -> None:
        self._connected = False


class FileTransport:
    """Debug sink: append the byte stream to a file instead of printing."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        from .config import resolve_path

        self.path = resolve_path(cfg.get("path", "logs/raw_output.bin"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.device_name = str(self.path.name)

    @property
    def is_connected(self) -> bool:
        return True

    async def connect(self) -> None:
        return None

    async def send(self, data: bytes) -> None:
        with self.path.open("ab") as handle:
            handle.write(data)
        log.info("Wrote %d bytes to %s (transport=file).", len(data), self.path)

    async def close(self) -> None:
        return None


Transport = BleTransport | SerialTransport | FileTransport


def build_transport(cfg: dict[str, Any]) -> Transport:
    kind = str(cfg.get("transport", "ble")).lower()
    if kind == "ble":
        return BleTransport(cfg["ble"])
    if kind == "serial":
        return SerialTransport(cfg["serial"])
    if kind == "file":
        return FileTransport(cfg["file"])
    raise SystemExit(f"invalid transport '{kind}' (use ble, serial or file).")


# ------------------------------------------------------------------------- tools
async def scan_devices(timeout: float = 8.0) -> list[tuple[BLEDevice, Any]]:
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    items = list(found.values())
    items.sort(key=lambda item: item[1].rssi or -999, reverse=True)
    return items


async def probe_device(
    address_or_device: str | BLEDevice, timeout: float = 20.0
) -> dict[str, Any]:
    """Connect and return the full service/characteristic map."""
    async with BleakClient(address_or_device, timeout=timeout) as client:
        services = []
        for service in client.services:
            characteristics = [
                {
                    "uuid": char.uuid,
                    "handle": char.handle,
                    "properties": list(char.properties),
                    "description": char.description,
                }
                for char in service.characteristics
            ]
            services.append(
                {
                    "uuid": service.uuid,
                    "description": service.description,
                    "characteristics": characteristics,
                }
            )
        return {
            "address": client.address,
            "name": getattr(client, "name", None),
            "mtu": client.mtu_size,
            "services": services,
        }


def pick_write_characteristic(info: dict[str, Any]) -> tuple[str, str] | None:
    """Best write characteristic from a probe_device() result."""
    candidates: list[tuple[str, str]] = []
    for service in info["services"]:
        for char in service["characteristics"]:
            if {"write", "write-without-response"} & set(char["properties"]):
                candidates.append((char["uuid"], service["uuid"]))
    if not candidates:
        return None
    for known in KNOWN_WRITE_CHARS:
        for uuid, service_uuid in candidates:
            if uuid.lower() == known:
                return uuid, service_uuid
    for uuid, service_uuid in candidates:
        if service_uuid.lower() not in GENERIC_SERVICES:
            return uuid, service_uuid
    return candidates[0]
