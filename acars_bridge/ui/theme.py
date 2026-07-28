"""Colours and fonts: dark cockpit panel, ECAM-style annunciator colours."""

from __future__ import annotations

import tkinter.font as tkfont

# Airbus-ish display palette: green = normal, amber = caution, red = warning.
COLORS = {
    "bg": "#070C10",
    "panel": "#0E161D",
    "panel_alt": "#111C24",
    "panel_deep": "#050A0D",
    "border": "#1E2F3B",
    "border_light": "#2C4353",
    "text": "#C6D7E2",
    "text_dim": "#6B8496",
    "text_bright": "#EAF3F9",
    "accent": "#12C9F5",
    "green": "#16E08A",
    "amber": "#FFB020",
    "red": "#FF4F52",
    "magenta": "#E56BFF",
    "discord": "#5865F2",
    "discord_hover": "#4752C4",
    "lamp_off": "#1B2A34",
}

MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "Lucida Console", "Courier New")
UI_CANDIDATES = ("Segoe UI", "Tahoma", "Arial")


def _pick(candidates: tuple[str, ...], fallback: str) -> str:
    try:
        available = {name.lower() for name in tkfont.families()}
    except Exception:  # no Tk yet
        return candidates[0]
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


class Fonts:
    """Created after the Tk root exists."""

    def __init__(self) -> None:
        mono = _pick(MONO_CANDIDATES, "Courier")
        sans = _pick(UI_CANDIDATES, "Arial")
        self.mono = mono
        self.sans = sans
        self.title = (sans, 17, "bold")
        self.subtitle = (mono, 9)
        self.section = (mono, 9, "bold")
        self.label = (mono, 9)
        self.value = (mono, 10, "bold")
        self.button = (sans, 9, "bold")
        self.button_big = (sans, 10, "bold")
        self.log = (mono, 9)
        self.tiny = (mono, 8)


def spaced(text: str, gap: str = " ") -> str:
    """'STATUS' -> 'S T A T U S' for panel captions."""
    return gap.join(text)
