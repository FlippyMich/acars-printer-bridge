"""Main window: cockpit-style control panel for the ACARS bridge."""

from __future__ import annotations

import asyncio
import queue
import tkinter as tk
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

from .. import __version__, config, escpos, printers, raster, system, transport
from ..bridge import Bridge, print_calibration, resolve_protocol
from ..watcher import InstanceLock, another_instance_running, watch_simulator
from .runtime import AsyncRuntime, install_log_handler
from .theme import COLORS, Fonts, spaced
from .widgets import (
    CockpitButton,
    DataRow,
    DiscordButton,
    LogConsole,
    Panel,
    Slider,
    StatusRow,
    Toggle,
)

DISCORD_URL = "https://discord.gg/bFY5wCf6CK"
ENERGY_MIN, ENERGY_MAX = 20000, 65535


class AcarsApp:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.events: queue.Queue = queue.Queue()
        self.runtime = AsyncRuntime()
        install_log_handler(self.events)

        self.lock = InstanceLock(int(cfg.get("lock_port", 49321)))
        self.bridge: Bridge | None = None
        self.bridge_future: Future[Any] | None = None
        self.busy = False
        self._slow_ticks = 0
        self._save_job: str | None = None
        self._printer_installed = False
        self._jobs_seen = -1

        self.root = tk.Tk()
        self.root.title(f"ACARS Printer Bridge {__version__}")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("1080x850")
        self.root.minsize(1000, 780)
        icon = Path(__file__).resolve().parent / "assets" / "app.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.fonts = Fonts()

        # Order matters: the expanding body must be packed last, otherwise it
        # eats the space the footer needs.
        self._build_header()
        self._build_footer()
        self._build_body()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._drain_events)
        self.root.after(400, self._poll_slow)
        self._log("READY", "Welcome aboard. Switch the printer on and press BRIDGE START.")

    # ------------------------------------------------------------------ layout
    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["panel"], height=82)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=COLORS["panel"])
        left.pack(side="left", padx=18, fill="y")
        badge = tk.Canvas(
            left, width=34, height=34, bg=COLORS["panel"], highlightthickness=0, bd=0
        )
        # stylised aircraft silhouette
        badge.create_polygon(
            17, 3, 20, 15, 31, 21, 31, 24, 20, 21, 20, 27, 24, 31, 24, 33,
            17, 31, 10, 33, 10, 31, 14, 27, 14, 21, 3, 24, 3, 21, 14, 15,
            fill=COLORS["accent"],
            outline="",
        )
        badge.pack(side="left", pady=(22, 0), padx=(0, 12))
        titles = tk.Frame(left, bg=COLORS["panel"])
        titles.pack(side="left", pady=(16, 0))
        tk.Label(
            titles,
            text="ACARS PRINTER BRIDGE",
            font=self.fonts.title,
            bg=COLORS["panel"],
            fg=COLORS["text_bright"],
        ).pack(anchor="w")
        tk.Label(
            titles,
            text=spaced("FENIX A32X") + "   ·   MSFS 2024 / 2020   ·   BLUETOOTH THERMAL PRINTER",
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w")

        right = tk.Frame(header, bg=COLORS["panel"])
        right.pack(side="right", padx=18)
        tk.Label(
            right,
            text=f"v{__version__}",
            font=self.fonts.value,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
        ).pack(anchor="e", pady=(14, 0))
        tk.Label(
            right,
            text=Path(self.cfg["_path"]).name,
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(anchor="e")

        tk.Frame(self.root, bg=COLORS["accent"], height=2).pack(fill="x")

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=14, pady=14)

        left = tk.Frame(body, bg=COLORS["bg"], width=330)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(body, bg=COLORS["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        self._build_status_panel(left)
        self._build_printer_panel(left)
        self._build_operation_panel(right)
        self._build_setup_panel(right)
        self._build_settings_panel(right)
        self._build_log_panel(right)

    def _build_status_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "System Status")
        panel.pack(fill="x")
        self.rows: dict[str, StatusRow] = {}
        for key, label in (
            ("bridge", "BRIDGE"),
            ("printer", "PRINTER LINK"),
            ("simulator", "SIMULATOR"),
            ("queue", "WINDOWS QUEUE"),
            ("autostart", "AUTOSTART"),
        ):
            row = StatusRow(panel.body, self.fonts, label)
            row.pack(fill="x", pady=3)
            self.rows[key] = row
        self.rows["bridge"].set("off", "OFFLINE")
        self.rows["printer"].set("off", "STANDBY")
        self.rows["simulator"].set("off", "CHECKING")
        self.rows["queue"].set("off", "CHECKING")
        self.rows["autostart"].set("off", "CHECKING")

    def _build_printer_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "Printer")
        panel.pack(fill="x", pady=(10, 0))
        ble = self.cfg["ble"]
        self.printer_rows = {
            "name": DataRow(panel.body, self.fonts, "NAME", ble.get("name_filter") or "---"),
            "addr": DataRow(panel.body, self.fonts, "ADDR", ble.get("address") or "not paired"),
            "proto": DataRow(panel.body, self.fonts, "PROTO", resolve_protocol(self.cfg).upper()),
            "char": DataRow(
                panel.body,
                self.fonts,
                "CHAR",
                (ble.get("write_char_uuid") or "auto").split("-")[0],
            ),
            "paper": DataRow(panel.body, self.fonts, "PAPER", f"{self.cfg['format']['columns']} col"),
        }
        for row in self.printer_rows.values():
            row.pack(fill="x", pady=2)

        counters = Panel(parent, self.fonts, "Counters")
        counters.pack(fill="x", pady=(10, 0))
        self.counter_rows = {
            "jobs": DataRow(counters.body, self.fonts, "JOBS", "0"),
            "last": DataRow(counters.body, self.fonts, "LAST", "---"),
        }
        for row in self.counter_rows.values():
            row.pack(fill="x", pady=2)

        checklist = Panel(parent, self.fonts, "Preflight Checklist")
        checklist.pack(fill="x", pady=(10, 0))
        self.checklist_rows: list[tuple[str, tk.Label]] = []
        for step, (item, action) in enumerate(
            (
                ("THERMAL PRINTER", "ON"),
                ("WINDOWS PRINTER", "INSTALLED"),
                ("BRIDGE", "START"),
                ("FENIX EFB PRINTER", "SELECTED"),
            ),
            start=1,
        ):
            line = tk.Frame(checklist.body, bg=COLORS["panel"])
            line.pack(fill="x", pady=1)
            tk.Label(
                line,
                text=f"{step}.",
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text_dim"],
            ).pack(side="left")
            tk.Label(
                line,
                text=f"{item} ".ljust(20, "."),
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text_dim"],
                anchor="w",
            ).pack(side="left", padx=(4, 0))
            value = tk.Label(
                line,
                text=action,
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["green"],
                anchor="w",
            )
            value.pack(side="left", padx=(4, 0))
            self.checklist_rows.append((item, value))

    def _build_operation_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "Operation")
        panel.pack(fill="x")
        row = tk.Frame(panel.body, bg=COLORS["panel"])
        row.pack(fill="x")
        self.btn_bridge = CockpitButton(
            row, self.fonts, "BRIDGE  START", self.toggle_bridge, kind="go", big=True, width=16
        )
        self.btn_bridge.pack(side="left")
        self.btn_test = CockpitButton(
            row, self.fonts, "TEST PRINT", self.test_print, kind="primary", big=True
        )
        self.btn_test.pack(side="left", padx=(10, 0))
        self.btn_preview = CockpitButton(
            row, self.fonts, "PREVIEW", self.preview, big=True
        )
        self.btn_preview.pack(side="left", padx=(10, 0))
        self.btn_file = CockpitButton(
            row, self.fonts, "PRINT FILE", self.print_file, big=True
        )
        self.btn_file.pack(side="left", padx=(10, 0))

    def _build_setup_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "Setup")
        panel.pack(fill="x", pady=(14, 0))
        # Two rows: five buttons on one line get clipped on smaller windows.
        top = tk.Frame(panel.body, bg=COLORS["panel"])
        top.pack(fill="x")
        self.btn_scan = CockpitButton(top, self.fonts, "SCAN FOR PRINTER", self.scan_printer)
        self.btn_scan.pack(side="left")
        self.btn_reconfigure = CockpitButton(
            top, self.fonts, "RECONFIGURE PRINTER", self.reconfigure_printer
        )
        self.btn_reconfigure.pack(side="left", padx=(10, 0))
        self.btn_calibrate = CockpitButton(top, self.fonts, "CALIBRATE DARKNESS", self.calibrate)
        self.btn_calibrate.pack(side="left", padx=(10, 0))

        bottom = tk.Frame(panel.body, bg=COLORS["panel"])
        bottom.pack(fill="x", pady=(8, 0))
        self.btn_install = CockpitButton(
            bottom, self.fonts, "INSTALL WINDOWS PRINTER", self.install_printer
        )
        self.btn_install.pack(side="left")
        self.btn_autostart = CockpitButton(
            bottom, self.fonts, "ARM AUTOSTART", self.toggle_autostart
        )
        self.btn_autostart.pack(side="left", padx=(10, 0))

    def _build_settings_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "Print Settings")
        panel.pack(fill="x", pady=(14, 0))
        cat = self.cfg["catprinter"]
        fmt = self.cfg["format"]

        darkness = tk.Frame(panel.body, bg=COLORS["panel"])
        darkness.pack(fill="x")
        tk.Label(
            darkness,
            text="DARKNESS",
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            width=10,
            anchor="w",
        ).pack(side="left")
        self.energy_slider = Slider(
            darkness,
            ENERGY_MIN,
            ENERGY_MAX,
            int(cat.get("energy", 58000)),
            self._on_energy_change,
            width=270,
            step=500,
        )
        self.energy_slider.pack(side="left", padx=(0, 14))
        self.energy_label = tk.Label(
            darkness,
            text=str(self.energy_slider.value),
            font=self.fonts.value,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            width=6,
            anchor="w",
        )
        self.energy_label.pack(side="left")
        tk.Label(
            darkness,
            text="raise if faint · lower if it smudges",
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(side="left", padx=(6, 0))

        numbers = tk.Frame(panel.body, bg=COLORS["panel"])
        numbers.pack(fill="x", pady=(8, 0))
        self.columns_var = tk.IntVar(value=int(fmt.get("columns", 32)))
        self.feed_var = tk.IntVar(value=int(cat.get("feed_steps", 120)))
        self._spin(numbers, "COLUMNS", self.columns_var, 24, 64, 1).pack(side="left")
        self._spin(numbers, "PAPER FEED", self.feed_var, 0, 400, 20).pack(side="left", padx=(24, 0))

        toggles = tk.Frame(panel.body, bg=COLORS["panel"])
        toggles.pack(fill="x", pady=(10, 0))
        self.toggle_upper = Toggle(
            toggles,
            self.fonts,
            "UPPERCASE",
            bool(fmt.get("uppercase")),
            lambda value: self._set_format("uppercase", value),
        )
        self.toggle_upper.pack(side="left")
        self.toggle_header = Toggle(
            toggles,
            self.fonts,
            "TIMESTAMP HEADER",
            bool(fmt.get("header")),
            lambda value: self._set_format("header", value),
        )
        self.toggle_header.pack(side="left", padx=(24, 0))
        self.toggle_follow = Toggle(
            toggles,
            self.fonts,
            "FOLLOW SIMULATOR",
            bool(self.cfg["ui"].get("follow_simulator", True)),
            self._set_follow,
        )
        self.toggle_follow.pack(side="left", padx=(24, 0))

    def _spin(
        self, parent: tk.Misc, label: str, var: tk.IntVar, low: int, high: int, step: int
    ) -> tk.Frame:
        frame = tk.Frame(parent, bg=COLORS["panel"])
        tk.Label(
            frame,
            text=label,
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(side="left", padx=(0, 8))
        spin = tk.Spinbox(
            frame,
            from_=low,
            to=high,
            increment=step,
            textvariable=var,
            width=5,
            font=self.fonts.value,
            bg=COLORS["panel_deep"],
            fg=COLORS["text"],
            buttonbackground=COLORS["panel_alt"],
            insertbackground=COLORS["accent"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            bd=0,
            justify="center",
            command=self._on_setting_change,
        )
        spin.bind("<FocusOut>", lambda _e: self._on_setting_change())
        spin.bind("<Return>", lambda _e: self._on_setting_change())
        spin.pack(side="left")
        return frame

    def _build_log_panel(self, parent: tk.Misc) -> None:
        panel = Panel(parent, self.fonts, "System Log")
        panel.pack(fill="both", expand=True, pady=(14, 0))
        CockpitButton(panel.head, self.fonts, "CLEAR", self._clear_log, kind="ghost").pack(
            side="right"
        )
        CockpitButton(
            panel.head, self.fonts, "OPEN LOGS", self._open_logs, kind="ghost"
        ).pack(side="right", padx=(0, 8))
        CockpitButton(
            panel.head, self.fonts, "SPOOL FOLDER", self._open_spool, kind="ghost"
        ).pack(side="right", padx=(0, 8))
        self.console = LogConsole(panel.body, self.fonts)
        self.console.pack(fill="both", expand=True)

    def _build_footer(self) -> None:
        footer = tk.Frame(self.root, bg=COLORS["panel"], height=58)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Frame(self.root, bg=COLORS["border"], height=1).pack(fill="x", side="bottom")

        self.hint = tk.Label(
            footer,
            text="EFB → SETTINGS → select 'ACARS Printer', then arm auto-print for ACARS/TELEX.",
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        )
        self.hint.pack(side="left", padx=18)
        DiscordButton(footer, self.fonts, lambda: system.open_url(DISCORD_URL)).pack(
            side="right", padx=18, pady=9
        )

    # ------------------------------------------------------------------ actions
    def toggle_bridge(self) -> None:
        if self.bridge_future is not None:
            self.stop_bridge()
        else:
            self.start_bridge()

    def start_bridge(self) -> None:
        if not self.lock.acquire():
            if messagebox.askyesno(
                "Bridge already running",
                "Another bridge instance is already running - most likely the background "
                "watcher installed by the autostart option.\n\nStop it and take control here?",
            ):
                self._run_thread(
                    lambda: (
                        True,
                        f"stopped {system.stop_background_watchers()} background process(es)",
                    ),
                    "Background watcher",
                )
            return
        follow = bool(self.cfg["ui"].get("follow_simulator", True))
        self._log(
            "BRIDGE",
            "Following the simulator: the bridge goes online when MSFS starts."
            if follow
            else "Bridge online, listening for ACARS jobs.",
        )
        coro = (
            watch_simulator(self.cfg, on_bridge=self._on_bridge_changed)
            if follow
            else self._run_bridge_directly()
        )
        self.bridge_future = self.runtime.submit(coro, self._on_bridge_finished)
        self.btn_bridge.set_kind("stop", "BRIDGE  STOP")
        self.rows["bridge"].set(
            "caution" if follow else "on", "ARMED" if follow else "ONLINE"
        )

    async def _run_bridge_directly(self) -> None:
        bridge = Bridge(self.cfg)
        self._on_bridge_changed(bridge)
        try:
            await bridge.run()
        finally:
            self._on_bridge_changed(None)

    def stop_bridge(self) -> None:
        future = self.bridge_future
        if future is None:
            return
        self._log("BRIDGE", "Stopping the bridge.")
        self.runtime.call_soon(future.cancel)
        self.bridge_future = None
        self.bridge = None
        self.lock.release()
        self.btn_bridge.set_kind("go", "BRIDGE  START")
        self.rows["bridge"].set("off", "OFFLINE")
        self.rows["printer"].set("off", "STANDBY")

    def _on_bridge_finished(self, future: Future[Any]) -> None:
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            self.events.put(("log", _now(), "ERROR", f"Bridge stopped: {error}"))
        self.events.put(("bridge_stopped",))

    def _on_bridge_changed(self, bridge: Bridge | None) -> None:
        """Called from the async thread by the simulator watcher."""
        self.bridge = bridge
        self.events.put(("bridge_state", bridge is not None))

    def test_print(self) -> None:
        self._print_text(escpos.TEST_PAGE, title="TEST", what="Test page")

    def print_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Print a text file",
            filetypes=[("Text files", "*.txt *.prn *.acars"), ("All files", "*.*")],
        )
        if not path:
            return
        text = escpos.decode_raw(Path(path).read_bytes())
        self._print_text(text, what=Path(path).name)

    def calibrate(self) -> None:
        if resolve_protocol(self.cfg) != "catprinter":
            messagebox.showinfo(
                "Not applicable",
                "Darkness calibration only applies to cat-printer devices (X6/X6h, GB01...).",
            )
            return
        levels = [40000, 50000, 58000, 65535]
        self._log("CALIBRATE", f"Printing samples at {', '.join(str(v) for v in levels)}.")
        self._busy(True)
        self.runtime.submit(
            print_calibration(self.cfg, levels),
            lambda future: self.events.put(("done", "Calibration", _exc(future))),
        )

    def preview(self) -> None:
        try:
            bridge = Bridge(self.cfg)
            fmt = self.cfg["format"]
            page = escpos.compose_text(escpos.TEST_PAGE, fmt, title="TEST")
            if bridge.protocol != "catprinter":
                messagebox.showinfo(
                    "ESC/POS device",
                    "This printer uses its own fonts, so there is nothing to render.\n\n"
                    + page,
                )
                return
            cat = dict(self.cfg["catprinter"])
            rows = raster.render_text(page, {**cat, "columns": int(fmt.get("columns", 32))})
            out = config.resolve_path("logs/preview.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            raster.rows_to_image(rows).save(out)
            self._log("PREVIEW", f"{len(rows)} dot rows rendered -> {out}")
            system.open_path(out.parent)
        except Exception as exc:
            self._log("PREVIEW", f"Failed: {exc}", "ERROR")

    def reconfigure_printer(self) -> None:
        """Forget the stored printer and pair a new one from scratch."""
        if not messagebox.askyesno(
            "Reconfigure printer",
            "Forget the printer stored in config.json and scan again?\n\n"
            "Use this when you change printer, or if pairing went wrong.",
        ):
            return
        if self.bridge_future is not None:
            self.stop_bridge()
        self.cfg["ble"]["address"] = None
        self.cfg["ble"]["write_char_uuid"] = None
        self.cfg["protocol"] = "auto"
        config.save(self.cfg)
        self.printer_rows["addr"].set("not paired", COLORS["amber"])
        self.printer_rows["char"].set("auto", COLORS["amber"])
        self.printer_rows["proto"].set(resolve_protocol(self.cfg).upper())
        self.printer_rows["name"].set(self.cfg["ble"].get("name_filter") or "---")
        self._log("SETUP", "Stored printer cleared. Switch your printer on - scanning now...")
        self.scan_printer()

    def scan_printer(self) -> None:
        self._log("SCAN", "Scanning for thermal printers (10 s)...")
        self._busy(True)
        self.runtime.submit(
            self._scan_coro(), lambda future: self.events.put(("done", "Scan", _exc(future)))
        )

    async def _scan_coro(self) -> None:
        items = await transport.scan_devices(10.0)
        candidates = printers.scan_results_to_candidates(items)
        found = printers.printers_only(candidates)
        self.events.put(("scan_result", found or candidates, bool(found)))

    def _choose_device(self, devices: list[Any], any_printer: bool = True) -> None:
        if not devices:
            messagebox.showwarning("Scan", "No Bluetooth LE device found.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Select your printer")
        dialog.configure(bg=COLORS["panel"])
        dialog.geometry("520x420")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(
            dialog,
            text=spaced("SELECT PRINTER"),
            font=self.fonts.section,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            dialog,
            text=(
                "Detected thermal printers, best match first."
                if any_printer
                else "No thermal printer recognised - every device found is listed instead."
            ),
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"] if any_printer else COLORS["amber"],
        ).pack(anchor="w", padx=16)

        listbox = tk.Listbox(
            dialog,
            bg=COLORS["panel_deep"],
            fg=COLORS["text"],
            font=self.fonts.log,
            selectbackground=COLORS["accent"],
            selectforeground="#000000",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            bd=0,
            activestyle="none",
        )
        listbox.pack(fill="both", expand=True, padx=16, pady=12)
        for device in devices:
            listbox.insert(
                "end",
                f"{device.name[:26]:<28}{device.address:<19}{device.rssi:>4} dBm  "
                f"{device.label if device.is_printer else ''}",
            )
        listbox.selection_set(0)

        buttons = tk.Frame(dialog, bg=COLORS["panel"])
        buttons.pack(fill="x", padx=16, pady=(0, 14))

        def confirm() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            device = devices[selection[0]]
            dialog.destroy()
            self._log("SCAN", f"Interrogating {device.name} ({device.address})...")
            self._busy(True)
            self.runtime.submit(
                self._probe_coro(device),
                lambda future: self.events.put(("done", "Pairing", _exc(future))),
            )

        CockpitButton(buttons, self.fonts, "USE THIS PRINTER", confirm, kind="primary").pack(
            side="right"
        )
        CockpitButton(buttons, self.fonts, "CANCEL", dialog.destroy, kind="ghost").pack(
            side="right", padx=(0, 8)
        )

    async def _probe_coro(self, device: Any) -> None:
        info = await transport.probe_device(device.address)
        chosen = transport.pick_write_characteristic(info)
        if chosen is None:
            self.events.put(
                ("log", _now(), "ERROR", "This device has no writable characteristic.")
            )
            return
        self.cfg["ble"]["address"] = info["address"]
        self.cfg["ble"]["write_char_uuid"] = chosen[0]
        if device.name and device.name != "(unnamed)":
            self.cfg["ble"]["name_filter"] = device.name.split("-")[0][:12]
        config.save(self.cfg)
        self.events.put(("printer_found", device, chosen[0]))

    def install_printer(self) -> None:
        ui = self.cfg["ui"]
        tcp = self.cfg["sources"]["tcp"]
        self._log("WINDOWS", "Creating the virtual printer (a UAC prompt will appear)...")
        self._busy(True)

        def work() -> tuple[bool, str]:
            return system.install_windows_printer(
                ui.get("windows_printer_name", "ACARS Printer"),
                ui.get("windows_port_name", "ACARS_RAW_9100"),
                tcp.get("host", "127.0.0.1"),
                int(tcp.get("port", 9100)),
            )

        self._run_thread(work, "Windows printer")

    def toggle_autostart(self) -> None:
        if system.autostart_installed():
            self._run_thread(system.remove_autostart, "Autostart")
        else:
            self._run_thread(system.install_autostart, "Autostart")

    # ------------------------------------------------------------------ helpers
    def _print_text(self, text: str, *, title: str | None = None, what: str = "Job") -> None:
        self._log("PRINT", f"Sending {what.lower()} to the printer...")
        self._busy(True)

        async def job() -> None:
            if self.bridge is not None:
                await self.bridge.print_text(text, title=title)
            else:
                bridge = Bridge(self.cfg)
                try:
                    await bridge.print_text(text, title=title)
                finally:
                    await bridge.transport.close()

        self.runtime.submit(job(), lambda future: self.events.put(("done", what, _exc(future))))

    def _run_thread(self, func: Callable[[], tuple[bool, str]], what: str) -> None:
        """Run a blocking Windows call off the UI thread; func returns (ok, message)."""
        self._busy(True)

        async def job() -> None:
            ok, message = await asyncio.to_thread(func)
            self.events.put(("sys_result", what, bool(ok), str(message)))

        self.runtime.submit(
            job(), lambda future: self.events.put(("done", what, _exc(future)))
        )

    def _busy(self, value: bool) -> None:
        self.busy = value
        for button in (
            self.btn_test,
            self.btn_preview,
            self.btn_file,
            self.btn_scan,
            self.btn_reconfigure,
            self.btn_install,
            self.btn_autostart,
            self.btn_calibrate,
        ):
            button.set_enabled(not value)

    def _log(self, tag: str, message: str, level: str = "INFO") -> None:
        self.console.append(_now(), level, f"[{tag}] {message}")

    def _clear_log(self) -> None:
        self.console.clear()

    def _open_logs(self) -> None:
        system.open_path(config.resolve_path("logs"))

    def _open_spool(self) -> None:
        system.open_path(config.resolve_path(self.cfg["sources"]["folder"].get("path", "spool")))

    # ----------------------------------------------------------------- settings
    def _set_format(self, key: str, value: bool) -> None:
        self.cfg["format"][key] = bool(value)
        self._schedule_save()

    def _set_follow(self, value: bool) -> None:
        self.cfg["ui"]["follow_simulator"] = bool(value)
        self._schedule_save()
        if self.bridge_future is not None:
            self._log("BRIDGE", "Restart the bridge to apply the new mode.", "WARNING")

    def _on_energy_change(self, value: int) -> None:
        self.energy_label.configure(text=str(value))
        self.cfg["catprinter"]["energy"] = int(value)
        self._schedule_save()

    def _on_setting_change(self) -> None:
        try:
            self.cfg["catprinter"]["feed_steps"] = int(self.feed_var.get())
            self.cfg["format"]["columns"] = int(self.columns_var.get())
        except tk.TclError:
            return
        self.printer_rows["paper"].set(f"{self.cfg['format']['columns']} col")
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(700, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._log("CONFIG", f"Cannot save config.json: {exc}", "ERROR")

    # -------------------------------------------------------------------- loops
    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "log":
            _, stamp, level, message = event
            self.console.append(stamp, level, message)
        elif kind == "status":
            _, key, state, text = event
            if key in self.rows:
                self.rows[key].set(state, text)
        elif kind == "bridge_state":
            online = event[1]
            self.rows["bridge"].set("on" if online else "caution", "ONLINE" if online else "ARMED")
        elif kind == "bridge_stopped":
            self.bridge_future = None
            self.bridge = None
            self.lock.release()
            self.btn_bridge.set_kind("go", "BRIDGE  START")
            self.rows["bridge"].set("off", "OFFLINE")
        elif kind == "scan_result":
            self._busy(False)
            self._choose_device(event[1], event[2] if len(event) > 2 else True)
        elif kind == "printer_found":
            _, device, char_uuid = event
            self.printer_rows["name"].set(device.name)
            self.printer_rows["addr"].set(device.address)
            self.printer_rows["char"].set(char_uuid.split("-")[0])
            self.printer_rows["proto"].set(resolve_protocol(self.cfg).upper())
            self._log("SCAN", f"Saved {device.name} ({device.label}) to config.json.")
        elif kind == "sys_result":
            _, what, ok, message = event
            for line in [ln for ln in message.splitlines() if ln.strip()][-6:]:
                self._log(what.upper(), line.strip(), "INFO" if ok else "ERROR")
            self._log(what.upper(), "done" if ok else "failed", "INFO" if ok else "ERROR")
        elif kind == "autostart_button":
            armed = event[1]
            self.btn_autostart.set_text("DISARM AUTOSTART" if armed else "ARM AUTOSTART")
        elif kind == "done":
            _, what, error = event
            self._busy(False)
            if error:
                self._log(what.upper(), f"failed: {error}", "ERROR")
            self._refresh_counters()
        elif kind == "job":
            self._refresh_counters()

    def _refresh_counters(self) -> None:
        if self.bridge is None:
            return
        printed = self.bridge.jobs_printed
        if printed != self._jobs_seen:
            self._jobs_seen = printed
            self.counter_rows["jobs"].set(str(printed))
            if printed:
                self.counter_rows["last"].set(_now(), COLORS["green"])

    def _poll_slow(self) -> None:
        self._slow_ticks += 1
        deep = self._slow_ticks % 5 == 1
        self.runtime.submit(self._collect_status(deep))

        # printer link state is a plain attribute read
        if self.bridge is not None:
            connected = self.bridge.transport.is_connected
            self.rows["printer"].set(
                "on" if connected else "caution", "CONNECTED" if connected else "WAITING"
            )
            name = getattr(self.bridge.transport, "device_name", None)
            if name:
                self.printer_rows["name"].set(name)
            self._refresh_counters()
        self.root.after(3000, self._poll_slow)

    async def _collect_status(self, deep: bool) -> None:
        names = self.cfg.get("autostart", {}).get("processes", [])
        running = await asyncio.to_thread(system.sim_is_running, names)
        self.events.put(
            ("status", "simulator", "on" if running else "off", "RUNNING" if running else "CLOSED")
        )
        if not deep:
            return

        info = await asyncio.to_thread(
            system.printer_info, self.cfg["ui"].get("windows_printer_name", "ACARS Printer")
        )
        self._printer_installed = info is not None
        self.events.put(
            ("status", "queue", "on" if info else "fault", "READY" if info else "NOT INSTALLED")
        )
        armed = system.autostart_installed()
        background = await asyncio.to_thread(system.background_watcher_running)
        text = "ARMED" if armed else "DISARMED"
        if background:
            text += " · RUNNING"
        self.events.put(("status", "autostart", "on" if armed else "off", text))
        self.events.put(("autostart_button", armed))

    # -------------------------------------------------------------------- close
    def on_close(self) -> None:
        try:
            if self.bridge_future is not None:
                self.runtime.call_soon(self.bridge_future.cancel)
            self.lock.release()
            self.runtime.shutdown()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _exc(future: Future[Any]) -> str | None:
    if future.cancelled():
        return None
    error = future.exception()
    return str(error) if error else None


def launch(cfg: dict[str, Any] | None = None) -> None:
    AcarsApp(cfg or config.load()).run()
