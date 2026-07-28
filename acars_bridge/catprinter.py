"""Protocol of the "cat printer" BLE thermal printers (service AE30 / char AE01).

Family: X6/X6h, GB01/GB02/GT01, MX05/MX06, YHK and clones. These do NOT speak
ESC/POS - they only accept binary packets carrying one bitmap row at a time.

Packet layout:
    0x51 0x78 <cmd> <dir=0x00> <len_lo> <len_hi> <payload...> <crc8> 0xFF

The CRC8 (polynomial 0x07) covers the payload only. Constants are verified
against the reference implementation rbaron/catprinter.
"""

from __future__ import annotations

from typing import Iterable, Sequence

PRINT_WIDTH = 384  # dots across 58 mm paper
ROW_BYTES = PRINT_WIDTH // 8

MAGIC = b"\x51\x78"
TERMINATOR = 0xFF

CMD_FEED_PAPER = 0xA1
CMD_DRAW_BITMAP = 0xA2
CMD_GET_DEV_STATE = 0xA3
CMD_SET_QUALITY = 0xA4
CMD_LATTICE = 0xA6
CMD_GET_DEV_INFO = 0xA8
CMD_LINE_CONTROL = 0xAE  # printer -> host XOn/XOff notification
CMD_SET_ENERGY = 0xAF
CMD_OTHER_FEED = 0xBD
CMD_DRAWING_MODE = 0xBE
CMD_DRAW_BITMAP_RLE = 0xBF

DRAWING_MODE_IMAGE = 0x00
DRAWING_MODE_TEXT = 0x01

# Constant "lattice" payloads that open and close a printout.
LATTICE_START_PAYLOAD = [0xAA, 0x55, 0x17, 0x38, 0x44, 0x5F, 0x5F, 0x5F, 0x44, 0x38, 0x2C]
LATTICE_END_PAYLOAD = [0xAA, 0x55, 0x17, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x17]

# Status bits reported in a CMD_GET_DEV_STATE reply.
STATE_FLAGS = {
    0x01: "out of paper",
    0x02: "cover open",
    0x04: "print head hot",
    0x08: "battery low",
}
STATE_BUSY = 0x80

_CRC8_TABLE: list[int] = []
for _byte in range(256):
    _crc = _byte
    for _ in range(8):
        _crc = ((_crc << 1) ^ 0x07) & 0xFF if _crc & 0x80 else (_crc << 1) & 0xFF
    _CRC8_TABLE.append(_crc)


def crc8(payload: Iterable[int]) -> int:
    crc = 0
    for byte in payload:
        crc = _CRC8_TABLE[(crc ^ byte) & 0xFF]
    return crc


def packet(cmd: int, payload: Sequence[int]) -> bytes:
    length = len(payload)
    if length > 0xFFFF:
        raise ValueError("payload too long")
    body = bytes(payload)
    return (
        MAGIC
        + bytes([cmd, 0x00, length & 0xFF, (length >> 8) & 0xFF])
        + body
        + bytes([crc8(body), TERMINATOR])
    )


LATTICE_START = packet(CMD_LATTICE, LATTICE_START_PAYLOAD)
LATTICE_END = packet(CMD_LATTICE, LATTICE_END_PAYLOAD)


# --------------------------------------------------------------------- commands
def cmd_get_state() -> bytes:
    return packet(CMD_GET_DEV_STATE, [0x00])


def cmd_set_quality(quality: int = 0x33) -> bytes:
    return packet(CMD_SET_QUALITY, [quality & 0xFF])


def cmd_set_energy(energy: int) -> bytes:
    energy = max(0, min(0xFFFF, int(energy)))
    return packet(CMD_SET_ENERGY, [(energy >> 8) & 0xFF, energy & 0xFF])


def normalize_drawing_mode(mode: str | int) -> int:
    if isinstance(mode, str):
        return DRAWING_MODE_TEXT if mode.lower() == "text" else DRAWING_MODE_IMAGE
    return int(mode) & 0xFF


def cmd_drawing_mode(mode: str | int = DRAWING_MODE_TEXT) -> bytes:
    return packet(CMD_DRAWING_MODE, [normalize_drawing_mode(mode)])


def cmd_feed(steps: int) -> bytes:
    """Advance the paper by N steps (one step = one dot row)."""
    steps = max(0, min(0xFFFF, int(steps)))
    return packet(CMD_FEED_PAPER, [steps & 0xFF, (steps >> 8) & 0xFF])


def cmd_feed_speed(value: int = 0x19) -> bytes:
    """0xBD: feed speed used for blank paper advance."""
    return packet(CMD_OTHER_FEED, [value & 0xFF])


def _pack_row_bits(row: Sequence[int]) -> bytes:
    """384 bits to 48 bytes, LSB first (bit 0 = leftmost dot)."""
    out = bytearray(ROW_BYTES)
    for index, value in enumerate(row):
        if value:
            out[index >> 3] |= 1 << (index & 7)
    return bytes(out)


def _rle_row(row: Sequence[int]) -> bytes:
    """Run-length encoding: 7-bit count, bit 7 carries the run colour."""
    out = bytearray()
    last = row[0] if row else 0
    count = 0
    for value in row:
        bit = 1 if value else 0
        if bit == last and count < 0x7F:
            count += 1
            continue
        if count:
            out.append((last << 7) | count)
        last, count = bit, 1
    if count:
        out.append((last << 7) | count)
    return bytes(out)


def cmd_draw_row(row: Sequence[int], compress: bool = False) -> bytes:
    if compress:
        encoded = _rle_row(row)
        if len(encoded) < ROW_BYTES:
            return packet(CMD_DRAW_BITMAP_RLE, encoded)
    return packet(CMD_DRAW_BITMAP, _pack_row_bits(row))


def build_print(
    rows: Sequence[Sequence[int]],
    *,
    energy: int = 58000,
    quality: int = 0x33,
    drawing_mode: str | int = "text",
    feed_steps: int = 120,
    compress: bool = False,
) -> bytes:
    """Bitmap rows (384 bits each) to a complete printer command stream."""
    out = bytearray()
    out += cmd_get_state()
    out += cmd_set_quality(quality)
    out += cmd_set_energy(energy)
    out += cmd_drawing_mode(drawing_mode)
    out += LATTICE_START
    for row in rows:
        out += cmd_draw_row(row, compress)
    out += cmd_feed_speed(0x19)
    # Split the feed: some models ignore large single values.
    remaining = max(0, int(feed_steps))
    while remaining > 0:
        step = min(48, remaining)
        out += cmd_feed(step)
        remaining -= step
    out += LATTICE_END
    out += cmd_get_state()
    return bytes(out)


# ---------------------------------------------------------- notification parsing
def parse_notification(data: bytes) -> list[tuple[int, bytes]]:
    """Extract (cmd, payload) pairs from a printer notification."""
    found: list[tuple[int, bytes]] = []
    position = 0
    while True:
        start = data.find(MAGIC, position)
        if start < 0 or start + 6 > len(data):
            return found
        cmd = data[start + 2]
        length = data[start + 4] | (data[start + 5] << 8)
        payload = data[start + 6 : start + 6 + length]
        found.append((cmd, payload))
        position = start + 6 + length + 2


def describe_state(payload: bytes) -> list[str]:
    if not payload:
        return []
    flags = payload[0]
    return [text for bit, text in STATE_FLAGS.items() if flags & bit]
