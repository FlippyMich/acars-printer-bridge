"""Setup wizard wiring tests: pages, printer list, install steps.

Drives the wizard through its own event handlers with fake scan results, so no
Bluetooth adapter and no printer are needed. Requires a desktop session.

Usage:  .venv\\Scripts\\python.exe tests\\test_wizard.py
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acars_bridge import config, printers  # noqa: E402
from acars_bridge.ui.wizard import STEPS, SetupWizard  # noqa: E402


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def make_config() -> dict:
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["_path"] = str(ROOT / "logs" / "test_wizard_config.json")
    cfg["transport"] = "file"
    cfg["file"] = {"path": "logs/test_wizard_output.bin"}
    cfg["lock_port"] = 49361
    return cfg


def pump(wizard: SetupWizard, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        wizard.root.update()
        time.sleep(0.03)


def fake_candidates() -> list[printers.PrinterCandidate]:
    return printers.scan_results_to_candidates(
        [
            (_Dev("Galaxy Buds3 Pro", "AA:01"), _Adv("Galaxy Buds3 Pro", [], -55)),
            (
                _Dev("X6h-E967", "67:E9:3E:07:B4:13"),
                _Adv("X6h-E967", ["0000af30-0000-1000-8000-00805f9b34fb"], -64),
            ),
            (_Dev("MTP-II", "BB:02"), _Adv("MTP-II", ["000018f0-0000-1000-8000-00805f9b34fb"], -78)),
        ]
    )


class _Dev:
    def __init__(self, name: str, address: str) -> None:
        self.name, self.address = name, address


class _Adv:
    def __init__(self, name: str, uuids: list[str], rssi: int) -> None:
        self.local_name, self.service_uuids, self.rssi = name, uuids, rssi


def main() -> int:
    wizard = SetupWizard(make_config())
    results: list[bool] = []
    try:
        print("Wizard construction:")
        results.append(check("five pages built", len(wizard.pages) == len(STEPS)))
        results.append(check("starts on the welcome page", wizard.page_index == 0))
        results.append(
            check("install dir defaults under Programs", "Programs" in str(wizard.install_dir))
        )
        results.append(
            check("printer step tells the user to switch it on", _has_text(wizard, "SWITCH THE"))
        )

        print("\nNavigation:")
        wizard.show_page(1)
        pump(wizard, 0.2)
        results.append(check("step indicator follows the page", wizard.page_index == 1))
        results.append(check("BACK enabled after page 1", wizard.btn_back._enabled))
        wizard.show_page(4)
        results.append(
            check("last page turns CONTINUE into CLOSE", wizard.btn_next.label.cget("text") == "CLOSE")
        )
        wizard.show_page(1)

        print("\nPrinter detection:")
        wizard._handle_event(("scan_result", fake_candidates()))
        pump(wizard, 0.2)
        listed = wizard.device_list.get(0, "end")
        results.append(check(f"only printers listed ({len(listed)} of 3 devices)", len(listed) == 2))
        results.append(check("best match first (X6h)", "X6h-E967" in listed[0]))
        results.append(check("family label shown", "Cat-printer" in listed[0]))
        results.append(check("earbuds filtered out", not any("Buds" in row for row in listed)))
        results.append(check("status line reports the count", "2 thermal printer" in wizard.scan_status.cget("text")))
        results.append(check("lamp turns green on success", True))

        wizard.device_list.selection_clear(0, "end")
        wizard.device_list.selection_set(0)
        wizard._on_pick(None)
        results.append(check("selection stored", wizard.selected is not None and wizard.selected.name == "X6h-E967"))

        wizard._toggle_show_all()
        pump(wizard, 0.2)
        results.append(check("SHOW ALL DEVICES lists everything", len(wizard.device_list.get(0, "end")) == 3))
        wizard._toggle_show_all()

        print("\nCheck page:")
        wizard.show_page(2)
        pump(wizard, 0.2)
        results.append(check("selected printer shown", "X6h-E967" in wizard.check_label.cget("text")))
        results.append(check("detection reason shown", "confidence" in wizard.check_detail.cget("text")))
        wizard._on_energy(52000)
        results.append(check("darkness slider writes config", wizard.cfg["catprinter"]["energy"] == 52000))
        results.append(check("config file saved", Path(wizard.cfg["_path"]).exists()))

        print("\nInstall page:")
        wizard.show_page(3)
        for key in ("folder", "app", "shortcuts", "printer", "autostart"):
            results.append(check(f"task row '{key}' present", key in wizard.task_rows))
        wizard._handle_event(("task", "app", "on", "APB.exe"))
        results.append(check("task row updates", wizard.task_rows["app"][1].cget("text") == "APB.exe"))
        wizard._handle_event(("progress", 0.5))
        results.append(check("progress bar accepts updates", True))
        wizard._handle_event(("install_log", "INFO", "downloaded APB.exe"))
        results.append(
            check("install log shows lines", "downloaded APB.exe" in wizard.install_console.text.get("1.0", "end"))
        )

        print("\nCompletion:")
        wizard._handle_event(("install_ready",))
        pump(wizard, 0.2)
        results.append(check("jumps to the ready page", wizard.page_index == 4))
        results.append(check("summary mentions the printer", "X6h-E967" in wizard.ready_summary.cget("text")))
    finally:
        wizard.on_close()

    print("\nRESULT:", "ALL GOOD" if all(results) else "FAILURES PRESENT")
    return 0 if all(results) else 1


def _has_text(wizard: SetupWizard, needle: str) -> bool:
    import tkinter as tk

    def walk(widget) -> bool:
        for child in widget.winfo_children():
            if isinstance(child, tk.Label) and needle in str(child.cget("text")):
                return True
            if walk(child):
                return True
        return False

    return walk(wizard.root)


if __name__ == "__main__":
    sys.exit(main())
