"""Text rasterization for cat-printer devices.

Cat printers have no built-in fonts: the text has to be sent as an image,
384 dots per row (58 mm paper).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont

from .catprinter import PRINT_WIDTH

log = logging.getLogger("acars.raster")

# Monospaced fonts shipped with Windows, in order of preference.
FONT_CANDIDATES = [
    "consola.ttf",  # Consolas
    "lucon.ttf",  # Lucida Console
    "cour.ttf",  # Courier New
    "CascadiaMono.ttf",
    "CascadiaCode.ttf",
]

_font_cache: dict[tuple[str | None, int, int], Any] = {}


def _font_paths(explicit: str | None) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    fonts_dir = Path("C:/Windows/Fonts")
    paths.extend(fonts_dir / name for name in FONT_CANDIDATES)
    return paths


def load_font(columns: int, width: int, explicit: str | None = None) -> Any:
    """Largest monospaced font whose `columns` characters fit in `width` dots."""
    key = (explicit, columns, width)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached

    for path in _font_paths(explicit):
        if not path.exists():
            continue
        for size in range(34, 7, -1):
            try:
                font = ImageFont.truetype(str(path), size)
            except OSError:
                break
            if font.getlength("0" * columns) <= width:
                log.debug("font %s size %d for %d columns", path.name, size, columns)
                _font_cache[key] = font
                return font
    log.warning("No TrueType font found, falling back to the tiny built-in font.")
    fallback = ImageFont.load_default()
    _font_cache[key] = fallback
    return fallback


def render_text(text: str, cfg: dict[str, Any]) -> list[list[int]]:
    """Text to a list of rows, each 384 values of 0/1 (1 = black dot)."""
    width = int(cfg.get("width", PRINT_WIDTH))
    columns = int(cfg.get("columns", 32))
    spacing = int(cfg.get("line_spacing", 2))
    threshold = int(cfg.get("threshold", 160))
    margin_top = int(cfg.get("margin_top", 4))
    margin_bottom = int(cfg.get("margin_bottom", 4))

    font = load_font(columns, width, cfg.get("font"))
    lines = text.split("\n") or [""]

    try:
        ascent, descent = font.getmetrics()
        line_height = ascent + descent + spacing
    except AttributeError:  # fallback bitmap font
        line_height = 12 + spacing

    height = margin_top + line_height * len(lines) + margin_bottom
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        if line.strip():
            draw.text((0, margin_top + index * line_height), line, font=font, fill=0)

    return image_to_rows(image, threshold)


def image_to_rows(image: Image.Image, threshold: int = 160) -> list[list[int]]:
    if image.mode != "L":
        image = image.convert("L")
    if image.width != PRINT_WIDTH:
        new_height = max(1, round(image.height * PRINT_WIDTH / image.width))
        image = image.resize((PRINT_WIDTH, new_height))

    pixels = image.load()
    rows: list[list[int]] = []
    for y in range(image.height):
        rows.append([1 if pixels[x, y] < threshold else 0 for x in range(image.width)])
    return rows


def rows_to_image(rows: Sequence[Sequence[int]]) -> Image.Image:
    """Bitmap rows back to a PIL image (print preview)."""
    height = max(1, len(rows))
    width = len(rows[0]) if rows else PRINT_WIDTH
    image = Image.new("L", (width, height), 255)
    pixels = image.load()
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if value:
                pixels[x, y] = 0
    return image


def rows_to_text_preview(rows: Sequence[Sequence[int]], every: int = 3) -> str:
    """ASCII preview, for logs and debugging."""
    out = []
    for y in range(0, len(rows), every):
        row = rows[y]
        out.append("".join("#" if row[x] else "." for x in range(0, len(row), every)))
    return "\n".join(out)
