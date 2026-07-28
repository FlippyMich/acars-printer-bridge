"""Setup wizard (APBinstaller): find the printer, fetch APB.exe, wire it all up."""

from __future__ import annotations

import asyncio
import queue
import tkinter as tk
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from .. import __version__, config, installer, printers, system, transport
from ..bridge import Bridge
from ..printers import PrinterCandidate
from .runtime import AsyncRuntime, install_log_handler
from .theme import COLORS, Fonts, spaced
from .widgets import CockpitButton, DiscordButton, Lamp, LogConsole, Panel, Slider

DISCORD_URL = "https://discord.gg/bFY5wCf6CK"
ASSETS = Path(__file__).resolve().parent / "assets"

STEPS = ("WELCOME", "PRINTER", "CHECK", "INSTALL", "READY")


class SetupWizard:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or config.load()
        self.events: queue.Queue = queue.Queue()
        self.runtime = AsyncRuntime()
        install_log_handler(self.events)

        self.candidates: list[PrinterCandidate] = []
        self.selected: PrinterCandidate | None = None
        self.show_all = False
        self.install_dir = installer.default_install_dir()
        self.app_exe: Path | None = None
        self.page_index = 0
        self.scanning = False

        self.root = tk.Tk()
        self.root.title(f"ACARS Printer Bridge - Setup {__version__}")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("900x700")
        self.root.minsize(880, 680)
        icon = ASSETS / "app.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.fonts = Fonts()
        self._logo: tk.PhotoImage | None = None

        self._build_header()
        self._build_footer()
        self.container = tk.Frame(self.root, bg=COLORS["bg"])
        self.container.pack(fill="both", expand=True, padx=18, pady=14)

        self.pages = [
            self._page_welcome(),
            self._page_printer(),
            self._page_check(),
            self._page_install(),
            self._page_ready(),
        ]
        self.show_page(0)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._drain_events)

    # ------------------------------------------------------------------ chrome
    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["panel"], height=88)
        header.pack(fill="x")
        header.pack_propagate(False)

        logo_path = ASSETS / "logo-48.png"
        if logo_path.exists():
            try:
                self._logo = tk.PhotoImage(file=str(logo_path))
            except tk.TclError:
                self._logo = None
        if self._logo is not None:
            tk.Label(header, image=self._logo, bg=COLORS["panel"], bd=0).pack(
                side="left", padx=(20, 14), pady=20
            )

        titles = tk.Frame(header, bg=COLORS["panel"])
        titles.pack(side="left", pady=20)
        tk.Label(
            titles,
            text="ACARS PRINTER BRIDGE",
            font=self.fonts.title,
            bg=COLORS["panel"],
            fg=COLORS["text_bright"],
        ).pack(anchor="w")
        tk.Label(
            titles,
            text=spaced("SETUP") + "   ·   FENIX A32X   ·   MSFS 2024 / 2020",
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w")

        self.step_frame = tk.Frame(header, bg=COLORS["panel"])
        self.step_frame.pack(side="right", padx=20)
        self.step_labels: list[tk.Label] = []
        for index, name in enumerate(STEPS):
            label = tk.Label(
                self.step_frame,
                text=f"{index + 1} {name}",
                font=self.fonts.tiny,
                bg=COLORS["panel"],
                fg=COLORS["text_dim"],
            )
            label.pack(anchor="e")
            self.step_labels.append(label)

        tk.Frame(self.root, bg=COLORS["accent"], height=2).pack(fill="x")

    def _build_footer(self) -> None:
        footer = tk.Frame(self.root, bg=COLORS["panel"], height=58)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Frame(self.root, bg=COLORS["border"], height=1).pack(fill="x", side="bottom")

        self.nav = tk.Frame(footer, bg=COLORS["panel"])
        self.nav.pack(side="left", padx=18)
        self.btn_back = CockpitButton(self.nav, self.fonts, "BACK", self.go_back, kind="ghost")
        self.btn_back.pack(side="left")
        self.btn_next = CockpitButton(
            self.nav, self.fonts, "CONTINUE", self.go_next, kind="primary", big=True
        )
        self.btn_next.pack(side="left", padx=(10, 0))

        DiscordButton(footer, self.fonts, lambda: system.open_url(DISCORD_URL)).pack(
            side="right", padx=18, pady=9
        )

    # ------------------------------------------------------------------- pages
    def _page_welcome(self) -> tk.Frame:
        page = tk.Frame(self.container, bg=COLORS["bg"])
        panel = Panel(page, self.fonts, "Welcome")
        panel.pack(fill="x")
        tk.Label(
            panel.body,
            text="This wizard sets up paper ACARS for your Fenix A32X.",
            font=self.fonts.value,
            bg=COLORS["panel"],
            fg=COLORS["text_bright"],
            anchor="w",
            justify="left",
        ).pack(fill="x")
        for line in (
            "1.  Find your Bluetooth thermal printer and learn how to talk to it",
            "2.  Download and install the APB app",
            "3.  Create the Windows printer the Fenix EFB can see",
            "4.  Start the app with Windows, so it is ready whenever you fly",
        ):
            tk.Label(
                panel.body,
                text=line,
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                anchor="w",
            ).pack(fill="x", pady=2)

        folder = Panel(page, self.fonts, "Install location")
        folder.pack(fill="x", pady=(14, 0))
        row = tk.Frame(folder.body, bg=COLORS["panel"])
        row.pack(fill="x")
        self.dir_label = tk.Label(
            row,
            text=str(self.install_dir),
            font=self.fonts.label,
            bg=COLORS["panel_deep"],
            fg=COLORS["text"],
            anchor="w",
            padx=10,
            pady=7,
        )
        self.dir_label.pack(side="left", fill="x", expand=True)
        CockpitButton(row, self.fonts, "CHANGE", self._choose_dir, kind="ghost").pack(
            side="left", padx=(10, 0)
        )
        tk.Label(
            folder.body,
            text="Nothing is written outside this folder, your Startup folder and "
            "%LOCALAPPDATA%. No administrator rights are needed except for the Windows printer.",
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            anchor="w",
            wraplength=780,
            justify="left",
        ).pack(fill="x", pady=(8, 0))
        return page

    def _page_printer(self) -> tk.Frame:
        page = tk.Frame(self.container, bg=COLORS["bg"])
        panel = Panel(page, self.fonts, "Switch your printer on")
        panel.pack(fill="x")

        banner = tk.Frame(panel.body, bg=COLORS["panel"])
        banner.pack(fill="x")
        self.printer_lamp = Lamp(banner, 22)
        self.printer_lamp.pack(side="left", padx=(0, 12))
        self.printer_lamp.set("caution")
        tk.Label(
            banner,
            text="SWITCH THE THERMAL PRINTER ON NOW",
            font=self.fonts.button_big,
            bg=COLORS["panel"],
            fg=COLORS["amber"],
        ).pack(side="left")

        for line in (
            "· Load the paper roll and close the cover",
            "· Disconnect it from any phone app - a BLE printer accepts one connection at a time",
            "· Keep it within a couple of metres of this PC for the first scan",
        ):
            tk.Label(
                panel.body,
                text=line,
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                anchor="w",
            ).pack(fill="x", pady=1)

        results = Panel(page, self.fonts, "Detected thermal printers")
        results.pack(fill="both", expand=True, pady=(14, 0))
        CockpitButton(results.head, self.fonts, "SCAN AGAIN", self.start_scan, kind="ghost").pack(
            side="right"
        )
        self.btn_show_all = CockpitButton(
            results.head, self.fonts, "SHOW ALL DEVICES", self._toggle_show_all, kind="ghost"
        )
        self.btn_show_all.pack(side="right", padx=(0, 8))

        self.scan_status = tk.Label(
            results.body,
            text="Press SCAN AGAIN once the printer is on.",
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            anchor="w",
        )
        self.scan_status.pack(fill="x", pady=(0, 8))

        self.device_list = tk.Listbox(
            results.body,
            bg=COLORS["panel_deep"],
            fg=COLORS["text"],
            font=self.fonts.log,
            selectbackground=COLORS["accent"],
            selectforeground="#000000",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            bd=0,
            activestyle="none",
            height=9,
        )
        self.device_list.pack(fill="both", expand=True)
        self.device_list.bind("<<ListboxSelect>>", self._on_pick)
        return page

    def _page_check(self) -> tk.Frame:
        page = tk.Frame(self.container, bg=COLORS["bg"])
        panel = Panel(page, self.fonts, "Printer check")
        panel.pack(fill="x")
        self.check_label = tk.Label(
            panel.body,
            text="No printer selected yet.",
            font=self.fonts.value,
            bg=COLORS["panel"],
            fg=COLORS["text_bright"],
            anchor="w",
            justify="left",
        )
        self.check_label.pack(fill="x")
        self.check_detail = tk.Label(
            panel.body,
            text="",
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
            anchor="w",
            justify="left",
        )
        self.check_detail.pack(fill="x", pady=(4, 10))

        row = tk.Frame(panel.body, bg=COLORS["panel"])
        row.pack(fill="x")
        self.btn_verify = CockpitButton(
            row, self.fonts, "VERIFY CONNECTION", self.verify_printer, kind="primary"
        )
        self.btn_verify.pack(side="left")
        self.btn_test = CockpitButton(row, self.fonts, "TEST PRINT", self.test_print)
        self.btn_test.pack(side="left", padx=(10, 0))

        darkness = tk.Frame(panel.body, bg=COLORS["panel"])
        darkness.pack(fill="x", pady=(12, 0))
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
            20000,
            65535,
            int(self.cfg["catprinter"].get("energy", 58000)),
            self._on_energy,
            width=250,
        )
        self.energy_slider.pack(side="left", padx=(0, 12))
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
            text="print the test page, then adjust if it is faint or smudged",
            font=self.fonts.tiny,
            bg=COLORS["panel"],
            fg=COLORS["text_dim"],
        ).pack(side="left")

        log = Panel(page, self.fonts, "Log")
        log.pack(fill="both", expand=True, pady=(14, 0))
        self.check_console = LogConsole(log.body, self.fonts, max_lines=200)
        self.check_console.pack(fill="both", expand=True)
        return page

    def _page_install(self) -> tk.Frame:
        page = tk.Frame(self.container, bg=COLORS["bg"])
        panel = Panel(page, self.fonts, "Install")
        panel.pack(fill="x")
        self.task_rows: dict[str, tuple[Lamp, tk.Label]] = {}
        for key, label in (
            ("folder", "INSTALL FOLDER"),
            ("app", "APB.EXE"),
            ("shortcuts", "SHORTCUTS"),
            ("printer", "WINDOWS PRINTER"),
            ("autostart", "START WITH WINDOWS"),
        ):
            row = tk.Frame(panel.body, bg=COLORS["panel"])
            row.pack(fill="x", pady=3)
            lamp = Lamp(row, 13)
            lamp.pack(side="left", padx=(0, 8))
            tk.Label(
                row,
                text=label,
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text_dim"],
                width=18,
                anchor="w",
            ).pack(side="left")
            value = tk.Label(
                row,
                text="pending",
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text_dim"],
                anchor="w",
            )
            value.pack(side="left", fill="x", expand=True)
            self.task_rows[key] = (lamp, value)

        self.progress = tk.Canvas(
            panel.body, height=8, bg=COLORS["panel_deep"], highlightthickness=0, bd=0
        )
        self.progress.pack(fill="x", pady=(12, 0))
        self._progress_bar = self.progress.create_rectangle(
            0, 0, 0, 8, outline="", fill=COLORS["accent"]
        )

        self.btn_install = CockpitButton(
            panel.body, self.fonts, "START INSTALL", self.run_install, kind="go", big=True
        )
        self.btn_install.pack(anchor="w", pady=(12, 0))

        log = Panel(page, self.fonts, "Install log")
        log.pack(fill="both", expand=True, pady=(14, 0))
        self.install_console = LogConsole(log.body, self.fonts, max_lines=300)
        self.install_console.pack(fill="both", expand=True)
        return page

    def _page_ready(self) -> tk.Frame:
        page = tk.Frame(self.container, bg=COLORS["bg"])
        panel = Panel(page, self.fonts, "Ready to fly")
        panel.pack(fill="x")
        tk.Label(
            panel.body,
            text="Setup complete.",
            font=self.fonts.title,
            bg=COLORS["panel"],
            fg=COLORS["green"],
            anchor="w",
        ).pack(fill="x")
        self.ready_summary = tk.Label(
            panel.body,
            text="",
            font=self.fonts.label,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            anchor="w",
            justify="left",
        )
        self.ready_summary.pack(fill="x", pady=(6, 12))

        steps = Panel(page, self.fonts, "Last step, inside the aircraft")
        steps.pack(fill="x", pady=(14, 0))
        for line in (
            "1.  Start MSFS and load the Fenix A32X",
            "2.  EFB  ->  Settings  ->  printer  ->  select 'ACARS Printer'",
            "3.  Enable auto-print for ACARS and/or TELEX",
            "4.  Switch the thermal printer on before each flight - APB does the rest",
        ):
            tk.Label(
                steps.body,
                text=line,
                font=self.fonts.label,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                anchor="w",
            ).pack(fill="x", pady=2)

        row = tk.Frame(page, bg=COLORS["bg"])
        row.pack(fill="x", pady=(16, 0))
        CockpitButton(
            row, self.fonts, "LAUNCH APB NOW", self.launch_app, kind="go", big=True
        ).pack(side="left")
        CockpitButton(
            row, self.fonts, "OPEN INSTALL FOLDER", self._open_install_dir, kind="ghost"
        ).pack(side="left", padx=(10, 0))
        return page

    # -------------------------------------------------------------- navigation
    def show_page(self, index: int) -> None:
        self.page_index = max(0, min(len(self.pages) - 1, index))
        for page in self.pages:
            page.pack_forget()
        self.pages[self.page_index].pack(fill="both", expand=True)
        for step, label in enumerate(self.step_labels):
            if step == self.page_index:
                label.configure(fg=COLORS["accent"], font=self.fonts.section)
            elif step < self.page_index:
                label.configure(fg=COLORS["green"], font=self.fonts.tiny)
            else:
                label.configure(fg=COLORS["text_dim"], font=self.fonts.tiny)

        self.btn_back.set_enabled(self.page_index > 0)
        last = self.page_index == len(self.pages) - 1
        self.btn_next.set_text("CLOSE" if last else "CONTINUE")
        if self.page_index == 1 and not self.candidates and not self.scanning:
            self.start_scan()
        if self.page_index == 2:
            self._refresh_check_page()

    def go_back(self) -> None:
        self.show_page(self.page_index - 1)

    def go_next(self) -> None:
        if self.page_index == len(self.pages) - 1:
            self.on_close()
            return
        if self.page_index == 1 and self.selected is None:
            if not messagebox.askyesno(
                "No printer selected",
                "No printer selected yet.\n\nYou can configure it later from the app. "
                "Continue anyway?",
            ):
                return
        self.show_page(self.page_index + 1)

    # -------------------------------------------------------------- page 1: scan
    def _toggle_show_all(self) -> None:
        self.show_all = not self.show_all
        self.btn_show_all.set_text("PRINTERS ONLY" if self.show_all else "SHOW ALL DEVICES")
        self._render_devices()

    def start_scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.printer_lamp.set("info")
        self.scan_status.configure(text="Scanning for 10 seconds...", fg=COLORS["accent"])
        self.device_list.delete(0, "end")
        self.runtime.submit(self._scan_coro(), lambda f: self.events.put(("scan_done", _exc(f))))

    async def _scan_coro(self) -> None:
        items = await transport.scan_devices(10.0)
        self.events.put(("scan_result", printers.scan_results_to_candidates(items)))

    def _render_devices(self) -> None:
        self.device_list.delete(0, "end")
        shown = self.candidates if self.show_all else printers.printers_only(self.candidates)
        self._shown = shown
        for candidate in shown:
            mark = "»" if candidate.is_printer else " "
            self.device_list.insert(
                "end",
                f"{mark} {candidate.name[:26]:<28}{candidate.address:<19}"
                f"{candidate.rssi:>4} dBm  {candidate.label if candidate.is_printer else ''}",
            )
        if shown:
            self.device_list.selection_set(0)
            self._on_pick(None)

    def _on_pick(self, _event: object) -> None:
        selection = self.device_list.curselection()
        if not selection or not getattr(self, "_shown", None):
            return
        self.selected = self._shown[selection[0]]

    # ------------------------------------------------------------- page 2: check
    def _refresh_check_page(self) -> None:
        if self.selected is None:
            self.check_label.configure(text="No printer selected.", fg=COLORS["amber"])
            self.check_detail.configure(text="Go back and run a scan, or configure it later.")
            return
        candidate = self.selected
        self.check_label.configure(
            text=f"{candidate.name}   ({candidate.address})", fg=COLORS["text_bright"]
        )
        self.check_detail.configure(
            text=f"{candidate.label} · confidence {candidate.confidence}% · "
            f"{', '.join(candidate.reasons) or 'no strong signal, verify below'}"
        )

    def verify_printer(self) -> None:
        if self.selected is None:
            return
        self._log_check(f"Connecting to {self.selected.name}...")
        self.btn_verify.set_enabled(False)
        self.runtime.submit(
            self._verify_coro(self.selected),
            lambda f: self.events.put(("verify_done", _exc(f))),
        )

    async def _verify_coro(self, candidate: PrinterCandidate) -> None:
        info = await transport.probe_device(candidate.address)
        chosen = transport.pick_write_characteristic(info)
        if chosen is None:
            self.events.put(("check_log", "ERROR", "No writable characteristic - not a printer."))
            return
        self.cfg["ble"]["address"] = info["address"]
        self.cfg["ble"]["write_char_uuid"] = chosen[0]
        if candidate.name and candidate.name != "(unnamed)":
            self.cfg["ble"]["name_filter"] = candidate.name.split("-")[0][:12]
        config.save(self.cfg)
        self.events.put(
            (
                "check_log",
                "INFO",
                f"Verified. Write characteristic {chosen[0].split('-')[0]}, "
                f"protocol {Bridge(self.cfg).protocol}. Saved to config.json.",
            )
        )

    def test_print(self) -> None:
        from .. import escpos

        self._log_check("Sending the test page...")
        self.btn_test.set_enabled(False)

        async def job() -> None:
            bridge = Bridge(self.cfg)
            try:
                await bridge.print_text(escpos.TEST_PAGE, title="TEST")
            finally:
                await bridge.transport.close()

        self.runtime.submit(job(), lambda f: self.events.put(("test_done", _exc(f))))

    def _on_energy(self, value: int) -> None:
        self.energy_label.configure(text=str(value))
        self.cfg["catprinter"]["energy"] = int(value)
        config.save(self.cfg)

    def _log_check(self, message: str, level: str = "INFO") -> None:
        self.check_console.append(_now(), level, message)

    # ----------------------------------------------------------- page 3: install
    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.install_dir.parent))
        if chosen:
            self.install_dir = Path(chosen) / config.APP_DIR_NAME
            self.dir_label.configure(text=str(self.install_dir))

    def _set_task(self, key: str, state: str, text: str) -> None:
        lamp, label = self.task_rows[key]
        lamp.set(state)
        color = {
            "on": COLORS["green"],
            "caution": COLORS["amber"],
            "fault": COLORS["red"],
            "info": COLORS["accent"],
        }.get(state, COLORS["text_dim"])
        label.configure(text=text, fg=color)

    def _set_progress(self, ratio: float) -> None:
        width = self.progress.winfo_width() or 1
        self.progress.coords(self._progress_bar, 0, 0, max(0, min(1.0, ratio)) * width, 8)

    def run_install(self) -> None:
        self.btn_install.set_enabled(False)
        self.runtime.submit(
            self._install_coro(), lambda f: self.events.put(("install_done", _exc(f)))
        )

    async def _install_coro(self) -> None:
        put = self.events.put
        install_dir = self.install_dir

        put(("task", "folder", "info", "creating..."))
        await asyncio.to_thread(install_dir.mkdir, parents=True, exist_ok=True)
        put(("task", "folder", "on", str(install_dir)))
        put(("install_log", "INFO", f"Install folder ready: {install_dir}"))

        put(("task", "app", "info", "fetching APB.exe..."))

        def progress(done: int, total: int) -> None:
            put(("progress", done / total if total else 0.0))

        try:
            app_exe, message = await asyncio.to_thread(
                installer.place_app, install_dir, installer.DEFAULT_DOWNLOAD_URL, progress
            )
            self.app_exe = app_exe
            put(("progress", 1.0))
            put(("task", "app", "on", app_exe.name))
            put(("install_log", "INFO", message))
        except Exception as exc:
            put(("task", "app", "fault", "failed"))
            put(("install_log", "ERROR", str(exc)))
            put(("install_log", "WARNING", "Put APB.exe next to this installer and try again."))
            return

        put(("task", "shortcuts", "info", "creating..."))
        results = await asyncio.to_thread(installer.create_shortcuts, app_exe)
        await asyncio.to_thread(installer.write_uninstall_note, install_dir)
        good = sum(1 for ok, _ in results if ok)
        put(("task", "shortcuts", "on" if good else "fault", f"{good}/2 created"))
        for ok, message in results:
            put(("install_log", "INFO" if ok else "ERROR", message))

        put(("task", "printer", "info", "UAC prompt..."))
        ui_cfg = self.cfg["ui"]
        tcp = self.cfg["sources"]["tcp"]
        ok, transcript = await asyncio.to_thread(
            system.install_windows_printer,
            ui_cfg.get("windows_printer_name", "ACARS Printer"),
            ui_cfg.get("windows_port_name", "ACARS_RAW_9100"),
            tcp.get("host", "127.0.0.1"),
            int(tcp.get("port", 9100)),
        )
        put(("task", "printer", "on" if ok else "caution", "installed" if ok else "skipped"))
        for line in [ln.strip() for ln in transcript.splitlines() if ln.strip()][-4:]:
            put(("install_log", "INFO" if ok else "WARNING", line))

        put(("task", "autostart", "info", "arming..."))
        ok, message = await asyncio.to_thread(_arm_autostart_for, app_exe)
        put(("task", "autostart", "on" if ok else "caution", "armed" if ok else "skipped"))
        put(("install_log", "INFO" if ok else "WARNING", message))
        put(("install_ready",))

    def launch_app(self) -> None:
        if self.app_exe is None or not self.app_exe.exists():
            messagebox.showwarning("Not installed", "APB.exe is not in place yet.")
            return
        ok, message = installer.launch_app(self.app_exe)
        self.install_console.append(_now(), "INFO" if ok else "ERROR", message)
        if ok:
            self.root.after(1200, self.on_close)

    def _open_install_dir(self) -> None:
        system.open_path(self.install_dir)

    # -------------------------------------------------------------------- loops
    def _drain_events(self) -> None:
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "log":
            _, stamp, level, message = event
            if self.page_index >= 3:
                self.install_console.append(stamp, level, message)
            else:
                self.check_console.append(stamp, level, message)
        elif kind == "scan_result":
            self.candidates = event[1]
            found = printers.printers_only(self.candidates)
            self.printer_lamp.set("on" if found else "fault")
            self.scan_status.configure(
                text=(
                    f"{len(found)} thermal printer(s) found out of {len(self.candidates)} devices."
                    if found
                    else "No thermal printer found. Switch it on, then press SCAN AGAIN."
                ),
                fg=COLORS["green"] if found else COLORS["amber"],
            )
            self._render_devices()
        elif kind == "scan_done":
            self.scanning = False
            if event[1]:
                self.scan_status.configure(text=f"Scan failed: {event[1]}", fg=COLORS["red"])
                self.printer_lamp.set("fault")
        elif kind == "check_log":
            self._log_check(event[2], event[1])
        elif kind == "verify_done":
            self.btn_verify.set_enabled(True)
            if event[1]:
                self._log_check(f"Verification failed: {event[1]}", "ERROR")
        elif kind == "test_done":
            self.btn_test.set_enabled(True)
            self._log_check(
                "Test page sent." if not event[1] else f"Test print failed: {event[1]}",
                "INFO" if not event[1] else "ERROR",
            )
        elif kind == "task":
            self._set_task(event[1], event[2], event[3])
        elif kind == "progress":
            self._set_progress(event[1])
        elif kind == "install_log":
            self.install_console.append(_now(), event[1], event[2])
        elif kind == "install_ready":
            summary = [f"App installed in {self.install_dir}"]
            if self.selected is not None:
                summary.append(f"Printer: {self.selected.name} ({self.selected.label})")
            summary.append("APB will start with Windows and follow MSFS.")
            self.ready_summary.configure(text="\n".join(summary))
            self.show_page(4)
        elif kind == "install_done":
            self.btn_install.set_enabled(True)
            if event[1]:
                self.install_console.append(_now(), "ERROR", f"Install failed: {event[1]}")

    def on_close(self) -> None:
        try:
            self.runtime.shutdown()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _arm_autostart_for(app_exe: Path) -> tuple[bool, str]:
    """Startup entry that launches the installed exe in watcher mode."""
    return installer.create_shortcut(
        system.autostart_shortcut(),
        app_exe,
        arguments="watch-sim",
        workdir=app_exe.parent,
        description="Start the ACARS bridge together with MSFS",
    )


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _exc(future: Future[Any]) -> str | None:
    if future.cancelled():
        return None
    error = future.exception()
    return str(error) if error else None


def launch(cfg: dict[str, Any] | None = None) -> None:
    SetupWizard(cfg).run()
