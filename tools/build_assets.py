"""Regenerates the bundled UI icons from their vector sources.

Run after changing an icon:  python tools/build_assets.py

The Discord mark path below comes from the simple-icons project (CC0 1.0,
public domain): https://github.com/simple-icons/simple-icons
It is used solely to link to our own Discord server, as Discord's brand
guidelines allow.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT_DIR = Path(__file__).resolve().parent.parent / "acars_bridge" / "ui" / "assets"

DISCORD_VIEWBOX = 24.0
DISCORD_PATH = (
    "M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447."
    "8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077."
    "077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-"
    ".319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294"
    "a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-."
    "6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2"
    "914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c"
    ".1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.07"
    "66 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9"
    "495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.06"
    "1.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.418"
    "9 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.974"
    "8 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1"
    ".0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z"
)

_TOKEN = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _tokenize(path: str) -> list[str]:
    return _TOKEN.findall(path)


def _cubic(p0, p1, p2, p3, steps: int = 24):
    for index in range(1, steps + 1):
        t = index / steps
        u = 1 - t
        yield (
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        )


def _arc(p0, rx, ry, rotation, large_arc, sweep, p1, steps: int = 24):
    """Endpoint -> center parameterization (SVG 1.1 implementation notes F.6)."""
    if rx == 0 or ry == 0 or p0 == p1:
        yield p1
        return
    phi = math.radians(rotation)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    rx, ry = abs(rx), abs(ry)

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    factor = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        value = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        return -value if (ux * vy - uy * vx) < 0 else value

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    for index in range(1, steps + 1):
        theta = theta1 + delta * index / steps
        yield (
            cx + rx * math.cos(theta) * cos_p - ry * math.sin(theta) * sin_p,
            cy + rx * math.cos(theta) * sin_p + ry * math.sin(theta) * cos_p,
        )


def parse_path(path: str) -> list[list[tuple[float, float]]]:
    """SVG path -> list of closed sub-paths flattened to points."""
    tokens = _tokenize(path)
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    last_control: tuple[float, float] | None = None
    subpaths: list[list[tuple[float, float]]] = []
    points: list[tuple[float, float]] = []

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def flag() -> int:
        """Arc flags are single digits and may be glued together ('00' = 0 then 0)."""
        nonlocal index
        token = tokens[index]
        if token in ("0", "1"):
            index += 1
            return int(token)
        tokens[index] = token[1:]
        return int(token[0])

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                if points:
                    subpaths.append(points)
                    points = []
                current = start
                continue
        relative = command.islower()
        upper = command.upper()

        if upper == "M":
            x, y = number(), number()
            current = (current[0] + x, current[1] + y) if relative else (x, y)
            if points:
                subpaths.append(points)
            points = [current]
            start = current
            command = "l" if relative else "L"
            last_control = None
        elif upper == "L":
            x, y = number(), number()
            current = (current[0] + x, current[1] + y) if relative else (x, y)
            points.append(current)
            last_control = None
        elif upper == "H":
            x = number()
            current = (current[0] + x, current[1]) if relative else (x, current[1])
            points.append(current)
            last_control = None
        elif upper == "V":
            y = number()
            current = (current[0], current[1] + y) if relative else (current[0], y)
            points.append(current)
            last_control = None
        elif upper in ("C", "S"):
            if upper == "C":
                c1 = (number(), number())
                c2 = (number(), number())
            else:
                mirror = last_control or current
                c1 = (2 * current[0] - mirror[0], 2 * current[1] - mirror[1])
                if relative:
                    c1 = (c1[0] - current[0], c1[1] - current[1])
                c2 = (number(), number())
            end = (number(), number())
            if relative:
                c1 = (current[0] + c1[0], current[1] + c1[1])
                c2 = (current[0] + c2[0], current[1] + c2[1])
                end = (current[0] + end[0], current[1] + end[1])
            points.extend(_cubic(current, c1, c2, end))
            last_control, current = c2, end
        elif upper in ("Q", "T"):
            if upper == "Q":
                control = (number(), number())
                if relative:
                    control = (current[0] + control[0], current[1] + control[1])
            else:
                mirror = last_control or current
                control = (2 * current[0] - mirror[0], 2 * current[1] - mirror[1])
            end = (number(), number())
            if relative:
                end = (current[0] + end[0], current[1] + end[1])
            c1 = (current[0] + 2 / 3 * (control[0] - current[0]), current[1] + 2 / 3 * (control[1] - current[1]))
            c2 = (end[0] + 2 / 3 * (control[0] - end[0]), end[1] + 2 / 3 * (control[1] - end[1]))
            points.extend(_cubic(current, c1, c2, end))
            last_control, current = control, end
        elif upper == "A":
            rx, ry, rotation = number(), number(), number()
            large_arc, sweep = flag(), flag()
            end = (number(), number())
            if relative:
                end = (current[0] + end[0], current[1] + end[1])
            points.extend(_arc(current, rx, ry, rotation, bool(large_arc), bool(sweep), end))
            current = end
            last_control = None
        else:
            raise ValueError(f"unsupported path command: {command!r}")

    if points:
        subpaths.append(points)
    return subpaths


def render_path(
    path: str,
    viewbox: float,
    size: int,
    color: tuple[int, int, int] = (255, 255, 255),
    supersample: int = 8,
) -> Image.Image:
    """Rasterize a filled SVG path (even-odd rule) into an RGBA image."""
    big = size * supersample
    scale = big / viewbox
    mask = Image.new("L", (big, big), 0)
    for subpath in parse_path(path):
        if len(subpath) < 3:
            continue
        layer = Image.new("L", (big, big), 0)
        ImageDraw.Draw(layer).polygon([(x * scale, y * scale) for x, y in subpath], fill=255)
        mask = ImageChops.difference(mask, layer)  # even-odd: holes punch through
    mask = mask.resize((size, size), Image.LANCZOS)
    icon = Image.new("RGBA", (size, size), (*color, 0))
    icon.putalpha(mask)
    return icon


# Aircraft silhouette used for the window/app icon, in a 34x34 box.
AIRCRAFT = [
    (17, 3), (20, 15), (31, 21), (31, 24), (20, 21), (20, 27), (24, 31), (24, 33),
    (17, 31), (10, 33), (10, 31), (14, 27), (14, 21), (3, 24), (3, 21), (14, 15),
]
ICON_BG = (14, 22, 29)
ICON_FG = (18, 201, 245)


PAPER = (232, 240, 246)
PAPER_SHADE = (183, 200, 212)
INK = (58, 78, 92)


def draw_logo(size: int, *, tile: bool = True, supersample: int = 4) -> Image.Image:
    """The app mark: a torn ACARS printout with an aircraft climbing off it.

    Drawn as vectors so it stays crisp from 16 px to 512 px.
    """
    canvas = size * supersample
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def px(value: float) -> float:
        return value * canvas

    if tile:
        inset = px(0.045)
        draw.rounded_rectangle(
            [inset, inset, canvas - inset, canvas - inset],
            radius=px(0.19),
            fill=ICON_BG,
            outline=(34, 63, 79),
            width=max(1, int(px(0.012))),
        )

    # Receipt: rounded top, torn zigzag bottom, slight left offset.
    left, right = px(0.22), px(0.60)
    top, bottom = px(0.17), px(0.74)
    draw.rounded_rectangle([left, top, right, bottom], radius=px(0.035), fill=PAPER)

    teeth = 6
    tooth_width = (right - left) / teeth
    points = [(left, bottom - px(0.02))]
    for index in range(teeth):
        x0 = left + tooth_width * index
        points.append((x0 + tooth_width / 2, bottom + px(0.05)))
        points.append((x0 + tooth_width, bottom - px(0.02)))
    points.append((right, bottom - px(0.02)))
    draw.polygon(points, fill=PAPER)

    # Printed lines on the receipt.
    line_x0, line_x1 = left + px(0.05), right - px(0.05)
    for index, width_factor in enumerate((1.0, 0.82, 0.94, 0.62)):
        y = top + px(0.09) + index * px(0.085)
        draw.rounded_rectangle(
            [line_x0, y, line_x0 + (line_x1 - line_x0) * width_factor, y + px(0.028)],
            radius=px(0.014),
            fill=INK if index == 0 else PAPER_SHADE,
        )

    # Aircraft climbing away from the paper, pointing up-right.
    scale = canvas / 34 * 0.66
    offset_x, offset_y = px(0.40), px(0.07)
    points = [(x * scale + offset_x, y * scale + offset_y) for x, y in AIRCRAFT]

    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.rotate(-35, resample=Image.BICUBIC, center=(canvas / 2, canvas / 2))

    # A dark gap around the aircraft keeps the two shapes apart at 16-32 px,
    # where paper and plane would otherwise merge into a blob.
    if tile:
        halo = mask.filter(ImageFilter.MaxFilter(max(3, int(px(0.045)) | 1)))
        image.paste(ICON_BG, mask=halo)
    image.paste(ICON_FG, mask=mask)

    return image.resize((size, size), Image.LANCZOS)


def build_app_icon(path: Path) -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw_logo(size) for size in sizes]
    frames[-1].save(path, sizes=[(size, size) for size in sizes], append_images=frames[:-1])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (20, 40):
        icon = render_path(DISCORD_PATH, DISCORD_VIEWBOX, size)
        target = OUT_DIR / f"discord-mark-{size}.png"
        icon.save(target)
        print(f"wrote {target} ({size}x{size})")

    app_icon = OUT_DIR / "app.ico"
    build_app_icon(app_icon)
    print(f"wrote {app_icon}")

    for size in (48, 96):
        logo = draw_logo(size)
        target = OUT_DIR / f"logo-{size}.png"
        logo.save(target)
        print(f"wrote {target} ({size}x{size})")

    docs = Path(__file__).resolve().parent.parent / "docs"
    docs.mkdir(exist_ok=True)
    draw_logo(512).save(docs / "logo.png")
    draw_logo(512, tile=False).save(docs / "logo-transparent.png")
    print(f"wrote {docs / 'logo.png'} and logo-transparent.png")


if __name__ == "__main__":
    main()
