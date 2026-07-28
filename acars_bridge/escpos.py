"""ESC/POS command generation and shared text layout."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone
from typing import Any

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
FONT_A = ESC + b"M\x00"
SIZE_NORMAL = GS + b"!\x00"
CUT = GS + b"V\x00"

# ESC t n - character code table
CODEPAGE_IDS = {
    "cp437": 0,
    "cp850": 2,
    "cp860": 3,
    "cp863": 4,
    "cp865": 5,
    "cp1252": 16,
    "cp852": 18,
    "cp858": 19,
    "ascii": 0,
}

# Characters cheap printers do not have, mapped to safe equivalents.
_TRANSLATE = {
    0x2019: "'",
    0x2018: "'",
    0x201C: '"',
    0x201D: '"',
    0x2013: "-",
    0x2014: "-",
    0x2026: "...",
    0x00B0: "deg",
    0x00A0: " ",
}

# Control sequences the Windows "Generic / Text Only" driver may emit.
# ESC @ takes no parameter, the others take one - do not eat the first
# character of the text (ESC @ + "ACARS" must not become "CARS").
_ESC_SEQ = re.compile(
    rb"\x1b@"
    rb"|\x1b[!tMaEGRSVdfipr\-23J][\x00-\xff]"
    rb"|\x1d[V!aBhwr][\x00-\xff]"
)

# Markers of an already rendered ESC/POS raster stream: pass those through
# untouched instead of re-formatting them as text.
_BINARY_MARKERS = (b"\x1dv0", b"\x1d(L", b"\x1bK", b"\x1b*")


def looks_binary_escpos(data: bytes) -> bool:
    return any(marker in data for marker in _BINARY_MARKERS)


def decode_raw(data: bytes) -> str:
    """Decode a raw spooler job into plain text."""
    cleaned = _ESC_SEQ.sub(b"", data)
    cleaned = cleaned.replace(b"\x00", b"").replace(b"\x0c", b"\n")
    for encoding in ("utf-8-sig", "cp1252", "cp437", "latin-1"):
        try:
            return cleaned.decode(encoding)
        except UnicodeDecodeError:
            continue
    return cleaned.decode("latin-1", errors="replace")


def normalize_text(text: str, fmt: dict[str, Any]) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_TRANSLATE)
    text = text.replace("\t", "    ")
    if fmt.get("strip_form_feed", True):
        text = text.replace("\x0c", "\n")
    if fmt.get("uppercase"):
        text = text.upper()

    columns = int(fmt.get("columns", 32))
    if fmt.get("wrap", True):
        wrapped: list[str] = []
        for line in text.split("\n"):
            if not line.strip():
                wrapped.append("")
            elif len(line) <= columns:
                wrapped.append(line.rstrip())
            else:
                wrapped.extend(
                    textwrap.wrap(
                        line,
                        width=columns,
                        replace_whitespace=False,
                        drop_whitespace=True,
                        break_long_words=True,
                        break_on_hyphens=False,
                    )
                    or [""]
                )
        text = "\n".join(wrapped)

    return text.rstrip("\n")


def encode_text(text: str, codepage: str) -> bytes:
    encoding = codepage if codepage.lower() != "ascii" else "ascii"
    try:
        return text.encode(encoding, errors="replace")
    except LookupError:
        return text.encode("cp437", errors="replace")


def compose_text(text: str, fmt: dict[str, Any], *, title: str | None = None) -> str:
    """Final page text: optional header plus laid-out body.

    Shared by the ESC/POS and the raster paths so both print identically.
    """
    columns = int(fmt.get("columns", 32))
    body = normalize_text(text, fmt)
    if not fmt.get("header"):
        return body
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%y  %H%MZ")
    header = "\n".join(
        [
            (title or "ACARS").center(columns).rstrip(),
            stamp.center(columns).rstrip(),
            "-" * columns,
        ]
    )
    return header + "\n" + body


def build_job(text: str, fmt: dict[str, Any], *, title: str | None = None) -> bytes:
    """Text to a complete ESC/POS byte stream."""
    fmt = dict(fmt)
    codepage = str(fmt.get("codepage", "cp437"))

    out = bytearray()
    out += INIT + FONT_A + SIZE_NORMAL + ALIGN_LEFT
    codepage_id = CODEPAGE_IDS.get(codepage.lower())
    if codepage_id is not None:
        out += ESC + b"t" + bytes([codepage_id])

    out += encode_text(compose_text(text, fmt, title=title) + "\n", codepage)

    feed = max(0, int(fmt.get("feed_lines", 4)))
    if feed:
        out += b"\n" * feed
    if fmt.get("cut"):
        out += CUT
    return bytes(out)


TEST_PAGE = """\
ACARS PRINTER TEST
FENIX A32X / MSFS 2024

.--- COLUMN CHECK ---.
123456789012345678901234567890
ABCDEFGHIJKLMNOPQRSTUVWXYZ
abcdefghijklmnopqrstuvwxyz
!"#$%&'()*+,-./:;<=>?@[]^_

/ / / / / / / / / / / / /
If you can read this line the
Bluetooth link is working.
"""
