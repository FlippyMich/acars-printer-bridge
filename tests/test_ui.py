"""UI wiring tests: build the window, drive the handlers, check what happens.

Uses transport=file so no printer (and no paper) is needed. Needs a desktop
session - Tkinter cannot start headless.

Usage:  .venv\\Scripts\\python.exe tests\\test_ui.py
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acars_bridge import config  # noqa: E402
from acars_bridge.ui.app import AcarsApp  # noqa: E402

OUT = ROOT / "logs" / "test_ui_output.bin"


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def make_config() -> dict:
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["_path"] = str(ROOT / "logs" / "test_ui_config.json")
    cfg["transport"] = "file"
    cfg["protocol"] = "catprinter"  # exercise the raster path
    cfg["file"] = {"path": "logs/test_ui_output.bin"}
    cfg["lock_port"] = 49341
    cfg["sources"]["tcp"] = {"enabled": True, "host": "127.0.0.1", "port": 19110}
    cfg["sources"]["folder"] = {"enabled": False}
    cfg["ui"]["follow_simulator"] = False
    return cfg


def pump(app: AcarsApp, seconds: float) -> None:
    """Run the Tk event loop for a while without blocking on mainloop()."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.root.update()
        time.sleep(0.03)


def console_text(app: AcarsApp) -> str:
    return app.console.text.get("1.0", "end")


def main() -> int:
    if OUT.exists():
        OUT.unlink()
    app = AcarsApp(make_config())
    results: list[bool] = []
    try:
        print("Window construction:")
        results.append(check("window title set", "ACARS" in app.root.title()))
        results.append(check("five status rows", len(app.rows) == 5))
        results.append(
            check("discord button present", _find_discord(app) is not None)
        )
        results.append(check("checklist rendered", len(app.checklist_rows) == 4))
        results.append(check("welcome line logged", "Welcome aboard" in console_text(app)))

        print("\nStatus events:")
        app._handle_event(("status", "simulator", "on", "RUNNING"))
        results.append(
            check("simulator row updates", app.rows["simulator"].value.cget("text") == "RUNNING")
        )
        app._handle_event(("bridge_state", True))
        results.append(
            check("bridge lamp goes online", app.rows["bridge"].value.cget("text") == "ONLINE")
        )
        app._handle_event(("log", "12:00:00", "ERROR", "synthetic failure"))
        results.append(check("errors reach the console", "synthetic failure" in console_text(app)))

        print("\nSettings:")
        app.energy_slider.set(45000)
        app._on_energy_change(45000)
        results.append(check("darkness writes to config", app.cfg["catprinter"]["energy"] == 45000))
        results.append(check("darkness label follows", app.energy_label.cget("text") == "45000"))
        app.toggle_upper.set(True)
        app._set_format("uppercase", True)
        results.append(check("uppercase toggle writes config", app.cfg["format"]["uppercase"]))
        app._save_now()
        results.append(check("config file written", Path(app.cfg["_path"]).exists()))

        print("\nTest print through the UI:")
        app.test_print()
        deadline = time.time() + 25
        printed = False
        while time.time() < deadline:
            pump(app, 0.3)
            if OUT.exists() and OUT.stat().st_size > 0:
                printed = True
                break
        results.append(check("payload produced by TEST PRINT", printed))
        data = OUT.read_bytes() if OUT.exists() else b""
        results.append(check("cat-printer packets sent", data.startswith(b"\x51\x78")))
        results.append(check("buttons re-enabled after the job", not app.busy))

        print("\nBridge start/stop:")
        app.start_bridge()
        pump(app, 3.0)
        results.append(check("bridge future created", app.bridge_future is not None))
        results.append(check("instance lock held", app.lock.held))
        results.append(check("RAW listener announced", "Bridge online" in console_text(app)))
        app.stop_bridge()
        pump(app, 2.0)
        results.append(check("bridge future cleared", app.bridge_future is None))
        results.append(check("instance lock released", not app.lock.held))
        results.append(
            check("button back to START", "START" in app.btn_bridge.label.cget("text"))
        )
    finally:
        app.on_close()

    print("\nRESULT:", "ALL GOOD" if all(results) else "FAILURES PRESENT")
    return 0 if all(results) else 1


def _find_discord(app: AcarsApp):
    from acars_bridge.ui.widgets import DiscordButton

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, DiscordButton):
                return child
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(app.root)


if __name__ == "__main__":
    sys.exit(main())
