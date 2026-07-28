"""Recognise thermal printers among the Bluetooth LE devices in range.

A BLE scan sees everything: headphones, TVs, phones, tyre sensors. This module
scores each device on the services it advertises and on its name, so the setup
wizard can show "these are your printers" instead of a wall of MAC addresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

CAT_PRINTER = "cat-printer"
ESCPOS_BLE = "escpos-ble"
UNKNOWN = "unknown"

PROTOCOL_BY_FAMILY = {CAT_PRINTER: "catprinter", ESCPOS_BLE: "escpos", UNKNOWN: "auto"}

FAMILY_LABEL = {
    CAT_PRINTER: "Cat-printer (raster)",
    ESCPOS_BLE: "ESC/POS over BLE",
    UNKNOWN: "Unknown device",
}

# Services advertised by the cat-printer family (X6/X6h, GB01, MX05, ...).
# Note AF30: the X6h advertises AF30 but serves AE30 once connected.
CAT_SERVICES = {
    "0000ae30-0000-1000-8000-00805f9b34fb",
    "0000af30-0000-1000-8000-00805f9b34fb",
    "0000ae3a-0000-1000-8000-00805f9b34fb",
}

# Services used by BLE ESC/POS printers and by the serial-bridge modules in them.
ESCPOS_SERVICES = {
    "000018f0-0000-1000-8000-00805f9b34fb",
    "0000ff00-0000-1000-8000-00805f9b34fb",
    "0000ffe0-0000-1000-8000-00805f9b34fb",
    "0000abf0-0000-1000-8000-00805f9b34fb",
    "49535343-fe7d-4ae5-8fa9-9fafd205e455",
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
}

# Name patterns of printers sold on the usual marketplaces.
NAME_PATTERNS: list[tuple[str, str, int, str]] = [
    (r"^x6h?\b|^x6", CAT_PRINTER, 78, "X6 series name"),
    (r"^g[bt]0[0-9]", CAT_PRINTER, 78, "GB/GT series name"),
    (r"^mx0[0-9]", CAT_PRINTER, 78, "MX series name"),
    (r"\byhk\b|^yhk", CAT_PRINTER, 70, "YHK clone name"),
    (r"^(m02|m03|m110|m120|t02|d30|q30)\b", CAT_PRINTER, 70, "Phomemo-style name"),
    (r"cat\s*printer|kitty\s*printer", CAT_PRINTER, 80, "cat printer name"),
    (r"^mtp-?|^rpp0?[0-9]|^pt-?2[0-9]|^zj-?[0-9]", ESCPOS_BLE, 74, "POS printer series name"),
    (r"goojprt|zjiang|xprinter|^xp-|munbyn|sunmi|issc", ESCPOS_BLE, 74, "known printer brand"),
    # No \b around "pos": names like "POS58mm" have no word boundary there.
    (r"(^|[^a-z])pos([^a-z]|$|\d)|printer|\bprt\b|thermal|receipt", ESCPOS_BLE, 62, "generic printer name"),
    (r"(58|80)\s*mm", ESCPOS_BLE, 62, "paper width in the name"),
]

# Devices that must never be offered as a printer.
NEGATIVE_PATTERNS = [
    r"buds|airpods|headset|headphone|speaker|soundbar|watch|band|tv\b|webos|bravia",
    r"iphone|galaxy|pixel|redmi|xiaomi mi\b|macbook|ipad|mouse|keyboard|controller",
    r"tire|tyre|thermometer|scale|lamp|led|bulb|beacon|tracker|tag\b",
]


@dataclass
class PrinterCandidate:
    name: str
    address: str
    rssi: int = 0
    family: str = UNKNOWN
    confidence: int = 0
    reasons: list[str] = field(default_factory=list)
    service_uuids: list[str] = field(default_factory=list)

    @property
    def protocol(self) -> str:
        return PROTOCOL_BY_FAMILY.get(self.family, "auto")

    @property
    def label(self) -> str:
        return FAMILY_LABEL.get(self.family, FAMILY_LABEL[UNKNOWN])

    @property
    def is_printer(self) -> bool:
        return self.confidence >= 60

    def describe(self) -> str:
        return f"{self.name} [{self.label}, {self.confidence}%] {self.address}"


def classify(
    name: str | None, service_uuids: Iterable[str] | None = None, rssi: int = 0, address: str = ""
) -> PrinterCandidate:
    """Score one device. 60% or more counts as a printer."""
    clean_name = (name or "").strip()
    lowered = clean_name.lower()
    services = [uuid.lower() for uuid in (service_uuids or [])]
    candidate = PrinterCandidate(
        name=clean_name or "(unnamed)",
        address=address,
        rssi=rssi,
        service_uuids=services,
    )

    for uuid in services:
        if uuid in CAT_SERVICES:
            candidate.family = CAT_PRINTER
            candidate.confidence = 96
            candidate.reasons.append(f"advertises cat-printer service {uuid.split('-')[0]}")
            break
        if uuid in ESCPOS_SERVICES:
            candidate.family = ESCPOS_BLE
            candidate.confidence = 92
            candidate.reasons.append(f"advertises printer service {uuid.split('-')[0]}")
            break

    if lowered:
        for pattern, family, score, reason in NAME_PATTERNS:
            if re.search(pattern, lowered):
                candidate.reasons.append(reason)
                if candidate.confidence:
                    # service and name agree: as certain as it gets
                    candidate.confidence = min(99, candidate.confidence + 3)
                    if candidate.family == UNKNOWN:
                        candidate.family = family
                else:
                    candidate.family = family
                    candidate.confidence = score
                break

    if candidate.confidence < 90 and lowered:
        for pattern in NEGATIVE_PATTERNS:
            if re.search(pattern, lowered):
                candidate.confidence = 0
                candidate.family = UNKNOWN
                candidate.reasons = ["looks like a phone/audio/sensor device"]
                break

    return candidate


def scan_results_to_candidates(items: Iterable[tuple[Any, Any]]) -> list[PrinterCandidate]:
    """Convert bleak (device, advertisement) pairs into scored candidates."""
    candidates: list[PrinterCandidate] = []
    for device, adv in items:
        candidates.append(
            classify(
                getattr(adv, "local_name", None) or getattr(device, "name", None),
                getattr(adv, "service_uuids", None) or [],
                getattr(adv, "rssi", 0) or 0,
                getattr(device, "address", ""),
            )
        )
    candidates.sort(key=lambda item: (item.confidence, item.rssi), reverse=True)
    return candidates


def printers_only(candidates: Iterable[PrinterCandidate]) -> list[PrinterCandidate]:
    return [candidate for candidate in candidates if candidate.is_printer]
