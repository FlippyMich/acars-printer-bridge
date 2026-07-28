"""Cat-printer protocol and rasterizer tests.

Reference vectors come from rbaron/catprinter, a known-working implementation
for this printer family.

Usage:  .venv\\Scripts\\python.exe tests\\test_protocol.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acars_bridge import catprinter, config, escpos, raster  # noqa: E402
from acars_bridge.bridge import resolve_protocol  # noqa: E402


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def hx(data: bytes) -> str:
    return data.hex(" ")


def test_commands() -> bool:
    print("Protocol commands (reference vectors):")
    ok = True
    ok &= check(
        f"get_state = {hx(catprinter.cmd_get_state())}",
        catprinter.cmd_get_state() == bytes.fromhex("5178a3000100000 0ff".replace(" ", "")),
    )
    ok &= check(
        f"set_quality(0x32) = {hx(catprinter.cmd_set_quality(0x32))}",
        catprinter.cmd_set_quality(0x32) == bytes.fromhex("5178a4000100329eff"),
    )
    ok &= check(
        f"feed(48) = {hx(catprinter.cmd_feed(48))}",
        catprinter.cmd_feed(48) == bytes.fromhex("5178a10002003000f9ff"),
    )
    ok &= check(
        f"lattice start = {hx(catprinter.LATTICE_START)}",
        catprinter.LATTICE_START == bytes.fromhex("5178a6000b00aa551738445f5f5f44382ca1ff"),
    )
    ok &= check(
        f"lattice end = {hx(catprinter.LATTICE_END)}",
        catprinter.LATTICE_END == bytes.fromhex("5178a6000b00aa5517000000000000001711ff"),
    )
    ok &= check(
        f"feed_speed(0x19) = {hx(catprinter.cmd_feed_speed())}",
        catprinter.cmd_feed_speed(0x19) == bytes.fromhex("5178bd000100194fff"),
    )
    ok &= check(
        "set_energy(0xffff) is big-endian",
        catprinter.cmd_set_energy(0xFFFF)[6:8] == b"\xff\xff",
    )
    ok &= check(
        "drawing_mode(text) = 0xBE with payload 0x01",
        catprinter.cmd_drawing_mode("text")[2] == 0xBE
        and catprinter.cmd_drawing_mode("text")[6] == 0x01,
    )
    ok &= check("crc8([0x32]) == 0x9e", catprinter.crc8([0x32]) == 0x9E)
    ok &= check("crc8 of empty payload == 0", catprinter.crc8([]) == 0)
    return ok


def test_bitmap() -> bool:
    print("\nBitmap encoding:")
    ok = True
    row = [0] * 384
    row[0] = 1  # leftmost dot
    row[9] = 1
    packet = catprinter.cmd_draw_row(row)
    payload = packet[6:-2]
    ok &= check("row payload is 48 bytes", len(payload) == catprinter.ROW_BYTES)
    ok &= check("command is 0xA2", packet[2] == catprinter.CMD_DRAW_BITMAP)
    ok &= check("LSB first (px0 -> byte0 bit0)", payload[0] == 0x01)
    ok &= check("px9 -> byte1 bit1", payload[1] == 0x02)
    ok &= check("terminator 0xFF", packet[-1] == 0xFF)
    ok &= check("crc matches", packet[-2] == catprinter.crc8(payload))

    blank = [0] * 384
    rle = catprinter.cmd_draw_row(blank, compress=True)
    ok &= check("blank row compresses to 0xBF", rle[2] == catprinter.CMD_DRAW_BITMAP_RLE)
    ok &= check(f"blank row fits in {len(rle)} bytes (< 54)", len(rle) < 54)
    ok &= check(
        "run-length: 384 white dots = runs of <=127",
        list(rle[6:-2]) == [0x7F, 0x7F, 0x7F, 0x03],
    )
    dense = [1 if x % 2 else 0 for x in range(384)]
    ok &= check(
        "dense row is not worth compressing -> 0xA2",
        catprinter.cmd_draw_row(dense, compress=True)[2] == catprinter.CMD_DRAW_BITMAP,
    )
    return ok


def test_sequence() -> bool:
    print("\nFull print sequence:")
    ok = True
    rows = [[0] * 384 for _ in range(10)]
    rows[5][100] = 1
    data = catprinter.build_print(rows, energy=0x8000, feed_steps=96)

    ok &= check("starts with get_state", data.startswith(catprinter.cmd_get_state()))
    ok &= check("contains lattice start", catprinter.LATTICE_START in data)
    ok &= check("contains lattice end", catprinter.LATTICE_END in data)
    ok &= check(
        "lattice start comes before lattice end",
        data.find(catprinter.LATTICE_START) < data.find(catprinter.LATTICE_END),
    )
    ok &= check(
        "energy is set before the lattice",
        data.find(catprinter.cmd_set_energy(0x8000)) < data.find(catprinter.LATTICE_START),
    )
    ok &= check("10 bitmap rows sent", data.count(b"\x51\x78\xa2\x00\x30\x00") == 10)
    ok &= check("96 feed steps split into 2 x 48", data.count(catprinter.cmd_feed(48)) == 2)
    ok &= check("ends with get_state", data.endswith(catprinter.cmd_get_state()))

    position, count, malformed = 0, 0, 0
    while position < len(data):
        if data[position : position + 2] != catprinter.MAGIC:
            malformed += 1
            break
        length = data[position + 4] | (data[position + 5] << 8)
        payload = data[position + 6 : position + 6 + length]
        crc, terminator = data[position + 6 + length], data[position + 7 + length]
        if crc != catprinter.crc8(payload) or terminator != 0xFF:
            malformed += 1
        position += 8 + length
        count += 1
    ok &= check(f"{count} packets, all with valid CRC and terminator", malformed == 0)
    return ok


def test_notifications() -> bool:
    print("\nNotifications and flow control:")
    ok = True
    pause = bytes([0x51, 0x78, 0xAE, 0x01, 0x01, 0x00, 0x10, 0x70, 0xFF])
    resume = bytes([0x51, 0x78, 0xAE, 0x01, 0x01, 0x00, 0x00, 0x00, 0xFF])
    ok &= check("XOff recognised", catprinter.parse_notification(pause) == [(0xAE, b"\x10")])
    ok &= check("XOn recognised", catprinter.parse_notification(resume) == [(0xAE, b"\x00")])
    ok &= check(
        "two packets in one notification",
        len(catprinter.parse_notification(pause + resume)) == 2,
    )
    ok &= check("garbage does not crash", catprinter.parse_notification(b"\x00\x01\x02") == [])
    ok &= check("status: out of paper", catprinter.describe_state(b"\x01") == ["out of paper"])
    ok &= check("status: all clear", catprinter.describe_state(b"\x00") == [])
    return ok


def test_text_layout() -> bool:
    print("\nText decoding and layout:")
    ok = True
    raw = (
        b"\x1b@ACARS MSG - RCVD 1425Z\r\n"
        b"METAR LIRF 271420Z 24012KT 9999 FEW035 SCT100 28/17 Q1013 NOSIG\r\n\x0c"
    )
    text = escpos.decode_raw(raw)
    ok &= check("ESC @ and form feed removed", "\x1b" not in text and "\x0c" not in text)
    ok &= check("ESC @ does not eat the first character", text.lstrip().startswith("ACARS MSG"))
    ok &= check(
        "parameterised sequences removed whole",
        escpos.decode_raw(b"\x1bt\x00\x1ba\x01OK\x1bE\x01X").strip() == "OKX",
    )
    ok &= check(
        "binary ESC/POS detected",
        escpos.looks_binary_escpos(b"\x1dv0\x00\x30\x00\x18\x00" + b"\xff" * 48)
        and not escpos.looks_binary_escpos(raw),
    )

    fmt = {"columns": 32, "codepage": "cp437", "wrap": True, "feed_lines": 3}
    job = escpos.build_job(text, fmt)
    ok &= check("job starts with ESC @", job.startswith(b"\x1b@"))
    ok &= check("job ends with three feeds", job.endswith(b"\n\n\n"))
    body = job.decode("cp437")
    ok &= check(
        "no line exceeds 32 columns",
        not [line for line in body.splitlines() if len(line) > 32],
    )
    ok &= check("wrapping keeps every word", "NOSIG" in body and "Q1013" in body)
    ok &= check(
        "header centred when enabled",
        "TEST".center(32).rstrip() in escpos.compose_text("x", {**fmt, "header": True}, title="TEST"),
    )
    ok &= check(
        "special characters do not break encoding",
        len(escpos.build_job("Citta' pero' - 25 deg", {**fmt, "wrap": False})) > 10,
    )
    return ok


def test_raster() -> bool:
    print("\nRasterizer:")
    ok = True
    cfg = {"columns": 32, "line_spacing": 2, "threshold": 160, "margin_top": 4, "margin_bottom": 4}
    rows = raster.render_text("ACARS MSG\n0123456789", cfg)
    ok &= check(f"{len(rows)} dot rows produced", len(rows) > 20)
    ok &= check("384 dots wide", all(len(row) == 384 for row in rows))
    ok &= check("text actually drawn", any(any(row) for row in rows))
    ok &= check("values are 0/1 only", all(v in (0, 1) for row in rows for v in row))

    font = raster.load_font(32, 384)
    ok &= check(
        f"32 columns fit in 384 dots (width {font.getlength('0' * 32):.0f})",
        font.getlength("0" * 32) <= 384,
    )
    ok &= check(
        "font is maximised (33 columns would not fit)",
        font.getlength("0" * 33) > 384 - font.getlength("0"),
    )
    full = raster.render_text("X" * 32, cfg)
    ok &= check(
        f"a full line uses most of the width ({max(sum(r) for r in full)} black dots)",
        max(sum(row) for row in full) > 100,
    )
    ok &= check(
        "preview image matches the bitmap size",
        raster.rows_to_image(rows).size == (384, len(rows)),
    )
    return ok


def test_protocol_selection() -> bool:
    print("\nAutomatic protocol selection:")
    ok = True
    cat = {
        "transport": "ble",
        "protocol": "auto",
        "ble": {"write_char_uuid": "0000ae01-0000-1000-8000-00805f9b34fb"},
    }
    esc = {
        "transport": "ble",
        "protocol": "auto",
        "ble": {"write_char_uuid": "00002af1-0000-1000-8000-00805f9b34fb"},
    }
    ok &= check("AE01 -> catprinter", resolve_protocol(cat) == "catprinter")
    ok &= check("2AF1 -> escpos", resolve_protocol(esc) == "escpos")
    ok &= check(
        "serial -> escpos", resolve_protocol({"transport": "serial", "protocol": "auto"}) == "escpos"
    )
    ok &= check(
        "manual override wins",
        resolve_protocol({"transport": "ble", "protocol": "escpos", "ble": cat["ble"]}) == "escpos",
    )
    ok &= check(
        "defaults target MSFS 2024 and 2020",
        "FlightSimulator2024.exe" in config.DEFAULTS["autostart"]["processes"]
        and "FlightSimulator.exe" in config.DEFAULTS["autostart"]["processes"],
    )
    return ok


if __name__ == "__main__":
    results = [
        test_commands(),
        test_bitmap(),
        test_sequence(),
        test_notifications(),
        test_text_layout(),
        test_raster(),
        test_protocol_selection(),
    ]
    print("\nRESULT:", "ALL GOOD" if all(results) else "FAILURES PRESENT")
    sys.exit(0 if all(results) else 1)
