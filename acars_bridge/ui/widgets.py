"""Custom widgets: panels, annunciator lamps, cockpit buttons, log console."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from .theme import COLORS, Fonts, spaced

ASSETS = Path(__file__).resolve().parent / "assets"


class Panel(tk.Frame):
    """Bordered box with a caption bar, like an EFB/MCDU section."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, title: str, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLORS["panel"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            **kwargs,
        )
        self.fonts = fonts
        head = tk.Frame(self, bg=COLORS["panel"])
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(
            head,
            text=spaced(title.upper()),
            font=fonts.section,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
        ).pack(side="left")
        self.head = head
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x", padx=10, pady=(6, 0))
        self.body = tk.Frame(self, bg=COLORS["panel"])
        self.body.pack(fill="both", expand=True, padx=10, pady=8)


class Lamp(tk.Canvas):
    """Annunciator lamp with a soft halo."""

    def __init__(self, parent: tk.Misc, size: int = 14, bg: str | None = None) -> None:
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=bg or COLORS["panel"],
            highlightthickness=0,
            bd=0,
        )
        self._halo = self.create_oval(1, 1, size - 1, size - 1, outline="", fill=COLORS["lamp_off"])
        inset = size * 0.28
        self._core = self.create_oval(
            inset, inset, size - inset, size - inset, outline="", fill=COLORS["lamp_off"]
        )
        self.set("off")

    def set(self, state: str) -> None:
        color = {
            "on": COLORS["green"],
            "green": COLORS["green"],
            "caution": COLORS["amber"],
            "amber": COLORS["amber"],
            "fault": COLORS["red"],
            "red": COLORS["red"],
            "info": COLORS["accent"],
            "off": COLORS["lamp_off"],
        }.get(state, COLORS["lamp_off"])
        halo = COLORS["lamp_off"] if color == COLORS["lamp_off"] else _dim(color, 0.35)
        self.itemconfigure(self._core, fill=color)
        self.itemconfigure(self._halo, fill=halo)


def _dim(hex_color: str, factor: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


class StatusRow(tk.Frame):
    """lamp + label + value, one line of the status panel."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, label: str) -> None:
        super().__init__(parent, bg=COLORS["panel"])
        self.lamp = Lamp(self, 13)
        self.lamp.pack(side="left", padx=(0, 8))
        tk.Label(
            self,
            text=label,
            font=fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            width=15,
            anchor="w",
        ).pack(side="left")
        self.value = tk.Label(
            self,
            text="---",
            font=fonts.value,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            anchor="w",
        )
        self.value.pack(side="left", fill="x", expand=True)

    def set(self, state: str, text: str, color: str | None = None) -> None:
        self.lamp.set(state)
        default = {
            "on": COLORS["green"],
            "green": COLORS["green"],
            "caution": COLORS["amber"],
            "amber": COLORS["amber"],
            "fault": COLORS["red"],
            "red": COLORS["red"],
            "info": COLORS["accent"],
        }.get(state, COLORS["text_dim"])
        self.value.configure(text=text, fg=color or default)


class DataRow(tk.Frame):
    """label + value without a lamp."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, label: str, value: str = "---") -> None:
        super().__init__(parent, bg=COLORS["panel"])
        tk.Label(
            self,
            text=label,
            font=fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            width=7,
            anchor="w",
        ).pack(side="left")
        self.value = tk.Label(
            self,
            text=value,
            font=fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            anchor="w",
        )
        self.value.pack(side="left", fill="x", expand=True)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.configure(text=text, fg=color or COLORS["text"])


class CockpitButton(tk.Frame):
    """Flat panel switch: 1 px border, hover highlight, optional accent bar."""

    KINDS = {
        "normal": (COLORS["panel_alt"], COLORS["text"], COLORS["border_light"]),
        "primary": ("#0C2E38", COLORS["accent"], COLORS["accent"]),
        "go": ("#0B3226", COLORS["green"], COLORS["green"]),
        "stop": ("#331416", COLORS["red"], COLORS["red"]),
        "ghost": (COLORS["panel"], COLORS["text_dim"], COLORS["border"]),
    }

    def __init__(
        self,
        parent: tk.Misc,
        fonts: Fonts,
        text: str,
        command: Callable[[], None],
        kind: str = "normal",
        width: int = 0,
        big: bool = False,
    ) -> None:
        bg, fg, border = self.KINDS.get(kind, self.KINDS["normal"])
        super().__init__(
            parent,
            bg=bg,
            highlightbackground=border,
            highlightthickness=1,
            bd=0,
            cursor="hand2",
        )
        self._kind = kind
        self._bg = bg
        self._command = command
        self._enabled = True
        self.label = tk.Label(
            self,
            text=text,
            font=fonts.button_big if big else fonts.button,
            bg=bg,
            fg=fg,
            padx=12,
            pady=8 if big else 6,
            width=width or 0,
            cursor="hand2",
        )
        self.label.pack(fill="both", expand=True)
        for widget in (self, self.label):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    # ------------------------------------------------------------------ events
    def _on_click(self, _event: object) -> None:
        if self._enabled:
            self._command()

    def _on_enter(self, _event: object) -> None:
        if self._enabled:
            hover = _mix(self._bg, "#ffffff", 0.10)
            self.configure(bg=hover)
            self.label.configure(bg=hover)

    def _on_leave(self, _event: object) -> None:
        self.configure(bg=self._bg)
        self.label.configure(bg=self._bg)

    # ------------------------------------------------------------------- state
    def set_kind(self, kind: str, text: str | None = None) -> None:
        bg, fg, border = self.KINDS.get(kind, self.KINDS["normal"])
        self._kind, self._bg = kind, bg
        self.configure(bg=bg, highlightbackground=border)
        self.label.configure(bg=bg, fg=fg)
        if text is not None:
            self.label.configure(text=text)

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        _, fg, _ = self.KINDS.get(self._kind, self.KINDS["normal"])
        self.label.configure(fg=fg if enabled else COLORS["lamp_off"])
        cursor = "hand2" if enabled else "arrow"
        self.configure(cursor=cursor)
        self.label.configure(cursor=cursor)


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    parts = []
    for index in (0, 2, 4):
        va, vb = int(a[index : index + 2], 16), int(b[index : index + 2], 16)
        parts.append(int(va + (vb - va) * ratio))
    return "#%02x%02x%02x" % tuple(parts)


class Toggle(tk.Frame):
    """Push-button style toggle that lights up when engaged."""

    def __init__(
        self,
        parent: tk.Misc,
        fonts: Fonts,
        text: str,
        value: bool,
        command: Callable[[bool], None],
    ) -> None:
        super().__init__(parent, bg=COLORS["panel"], cursor="hand2")
        self._value = bool(value)
        self._command = command
        self.dot = tk.Canvas(
            self, width=26, height=13, bg=COLORS["panel"], highlightthickness=0, bd=0
        )
        self._track = self.dot.create_rectangle(0, 2, 26, 11, outline="", fill=COLORS["lamp_off"])
        self._knob = self.dot.create_oval(0, 0, 13, 13, outline="", fill=COLORS["text_dim"])
        self.dot.pack(side="left", padx=(0, 8))
        self.label = tk.Label(
            self,
            text=text,
            font=fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            cursor="hand2",
        )
        self.label.pack(side="left")
        for widget in (self, self.dot, self.label):
            widget.bind("<Button-1>", self._toggle)
        self._render()

    def _toggle(self, _event: object) -> None:
        self._value = not self._value
        self._render()
        self._command(self._value)

    def _render(self) -> None:
        if self._value:
            self.dot.itemconfigure(self._track, fill=_dim(COLORS["accent"], 0.45))
            self.dot.itemconfigure(self._knob, fill=COLORS["accent"])
            self.dot.coords(self._knob, 13, 0, 26, 13)
            self.label.configure(fg=COLORS["text_bright"])
        else:
            self.dot.itemconfigure(self._track, fill=COLORS["lamp_off"])
            self.dot.itemconfigure(self._knob, fill=COLORS["text_dim"])
            self.dot.coords(self._knob, 0, 0, 13, 13)
            self.label.configure(fg=COLORS["text_dim"])

    @property
    def value(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self._render()


class Slider(tk.Canvas):
    """Custom slider: dark track, accent fill, bright handle.

    tk.Scale cannot colour its handle separately from its background, which
    looks wrong on a dark panel.
    """

    def __init__(
        self,
        parent: tk.Misc,
        low: int,
        high: int,
        value: int,
        command: Callable[[int], None],
        width: int = 250,
        step: int = 500,
    ) -> None:
        super().__init__(
            parent, width=width, height=22, bg=COLORS["panel"], highlightthickness=0, bd=0
        )
        self.low, self.high, self.step = low, high, max(1, step)
        self._value = max(low, min(high, value))
        self._command = command
        self._width = width
        self._pad = 8
        self._track = self.create_rectangle(
            self._pad, 9, width - self._pad, 13, outline="", fill=COLORS["panel_deep"]
        )
        self._fill = self.create_rectangle(self._pad, 9, self._pad, 13, outline="", fill=COLORS["accent"])
        self._handle = self.create_rectangle(0, 3, 0, 19, outline="", fill=COLORS["text_bright"])
        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self._render()

    def _position(self) -> float:
        span = max(1, self.high - self.low)
        usable = self._width - 2 * self._pad
        return self._pad + usable * (self._value - self.low) / span

    def _render(self) -> None:
        x = self._position()
        self.coords(self._fill, self._pad, 9, x, 13)
        self.coords(self._handle, x - 4, 3, x + 4, 19)

    def _on_drag(self, event: tk.Event) -> None:
        usable = self._width - 2 * self._pad
        ratio = min(1.0, max(0.0, (event.x - self._pad) / usable))
        raw = self.low + ratio * (self.high - self.low)
        value = int(round(raw / self.step) * self.step)
        value = max(self.low, min(self.high, value))
        if value != self._value:
            self._value = value
            self._render()
            self._command(value)
        else:
            self._render()

    @property
    def value(self) -> int:
        return self._value

    def set(self, value: int) -> None:
        self._value = max(self.low, min(self.high, int(value)))
        self._render()


class LogConsole(tk.Frame):
    """Scrolling console with per-level colouring."""

    LEVEL_TAGS = {
        "DEBUG": "dim",
        "INFO": "info",
        "WARNING": "warn",
        "ERROR": "error",
        "CRITICAL": "error",
    }

    def __init__(self, parent: tk.Misc, fonts: Fonts, max_lines: int = 600) -> None:
        super().__init__(parent, bg=COLORS["panel_deep"])
        self.max_lines = max_lines
        self.text = tk.Text(
            self,
            bg=COLORS["panel_deep"],
            fg=COLORS["text"],
            font=fonts.log,
            bd=0,
            highlightthickness=0,
            insertwidth=0,
            wrap="word",
            padx=10,
            pady=8,
            state="disabled",
            cursor="arrow",
        )
        scroll = tk.Scrollbar(
            self,
            command=self.text.yview,
            bg=COLORS["panel"],
            troughcolor=COLORS["panel_deep"],
            activebackground=COLORS["border_light"],
            bd=0,
            highlightthickness=0,
            width=10,
        )
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.text.tag_configure("dim", foreground=COLORS["text_dim"])
        self.text.tag_configure("info", foreground=COLORS["text"])
        self.text.tag_configure("warn", foreground=COLORS["amber"])
        self.text.tag_configure("error", foreground=COLORS["red"])
        self.text.tag_configure("ok", foreground=COLORS["green"])
        self.text.tag_configure("stamp", foreground=COLORS["text_dim"])

    def append(self, stamp: str, level: str, message: str) -> None:
        tag = self.LEVEL_TAGS.get(level.upper(), "info")
        self.text.configure(state="normal")
        self.text.insert("end", f"{stamp}  ", "stamp")
        self.text.insert("end", f"{message}\n", tag)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > self.max_lines:
            self.text.delete("1.0", f"{lines - self.max_lines}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class DiscordButton(tk.Frame):
    """Brand-coloured button: Discord mark on the left, white label."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, command: Callable[[], None]) -> None:
        super().__init__(
            parent,
            bg=COLORS["discord"],
            cursor="hand2",
            highlightthickness=0,
            bd=0,
        )
        self._command = command
        self._icon: tk.PhotoImage | None = None
        icon_path = ASSETS / "discord-mark-20.png"
        if icon_path.exists():
            try:
                self._icon = tk.PhotoImage(file=str(icon_path))
            except tk.TclError:
                self._icon = None

        self.icon_label = tk.Label(
            self,
            image=self._icon,
            bg=COLORS["discord"],
            bd=0,
            cursor="hand2",
        )
        if self._icon is None:
            self.icon_label.configure(text="●", fg="white", font=fonts.button)
        self.icon_label.pack(side="left", padx=(14, 9), pady=9)

        self.text_label = tk.Label(
            self,
            text="Join our Discord",
            font=fonts.button_big,
            bg=COLORS["discord"],
            fg="#FFFFFF",
            bd=0,
            cursor="hand2",
        )
        self.text_label.pack(side="left", padx=(0, 16))

        for widget in (self, self.icon_label, self.text_label):
            widget.bind("<Button-1>", lambda _e: self._command())
            widget.bind("<Enter>", lambda _e: self._paint(COLORS["discord_hover"]))
            widget.bind("<Leave>", lambda _e: self._paint(COLORS["discord"]))

    def _paint(self, color: str) -> None:
        for widget in (self, self.icon_label, self.text_label):
            widget.configure(bg=color)
