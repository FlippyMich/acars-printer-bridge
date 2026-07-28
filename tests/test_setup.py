"""Thermal printer detection and installer helper tests.

No hardware, no network: the download test serves a fake exe from localhost.

Usage:  .venv\\Scripts\\python.exe tests\\test_setup.py
"""

from __future__ import annotations

import http.server
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acars_bridge import installer, printers  # noqa: E402

TMP = ROOT / "logs" / "setup_test"


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def test_detection() -> bool:
    print("Thermal printer detection:")
    ok = True

    # The real X6h: advertises AF30, serves AE30.
    x6h = printers.classify("X6h-E967", ["0000af30-0000-1000-8000-00805f9b34fb"], -64, "AA:BB")
    ok &= check("X6h recognised as a printer", x6h.is_printer)
    ok &= check("X6h mapped to the cat-printer family", x6h.family == printers.CAT_PRINTER)
    ok &= check("X6h protocol is catprinter", x6h.protocol == "catprinter")
    ok &= check(f"X6h confidence {x6h.confidence}% (service + name)", x6h.confidence >= 96)

    escpos = printers.classify("MTP-II", ["000018f0-0000-1000-8000-00805f9b34fb"], -70)
    ok &= check("18F0 device recognised as ESC/POS", escpos.family == printers.ESCPOS_BLE)
    ok &= check("ESC/POS protocol selected", escpos.protocol == "escpos")

    by_name_only = printers.classify("GB01", [], -80)
    ok &= check("GB01 recognised by name alone", by_name_only.is_printer)
    generic = printers.classify("BlueTooth Printer", [], -80)
    ok &= check("generic 'Printer' name recognised", generic.is_printer)
    paper = printers.classify("POS58mm", [], -80)
    ok &= check("'58mm' name recognised", paper.is_printer)

    print("  -- devices that must NOT be offered --")
    for name in (
        "Galaxy Buds3 Pro (63AF) LE",
        "[LG] webOS TV OLED65A19LA",
        "DualSense Wireless Controller",
        "Samsung QN85BA 55",
        "BJ_LED",
        "Z Flip7 di the",
    ):
        candidate = printers.classify(name, [], -70)
        ok &= check(f"{name[:28]!r} rejected", not candidate.is_printer)

    unnamed = printers.classify(None, [], -90)
    ok &= check("unnamed device is not a printer", not unnamed.is_printer)
    ok &= check("unnamed device gets a readable label", unnamed.name == "(unnamed)")

    class FakeDevice:
        def __init__(self, name, address):
            self.name, self.address = name, address

    class FakeAdv:
        def __init__(self, name, uuids, rssi):
            self.local_name, self.service_uuids, self.rssi = name, uuids, rssi

    items = [
        (FakeDevice("Buds", "11"), FakeAdv("Buds", [], -50)),
        (FakeDevice("X6h-E967", "22"), FakeAdv("X6h-E967", ["0000af30-0000-1000-8000-00805f9b34fb"], -70)),
        (FakeDevice("GB02", "33"), FakeAdv("GB02", [], -60)),
    ]
    candidates = printers.scan_results_to_candidates(items)
    ok &= check("scan results sorted by confidence", candidates[0].name == "X6h-E967")
    only = printers.printers_only(candidates)
    ok &= check("filter keeps the two printers only", [c.name for c in only] == ["X6h-E967", "GB02"])
    return ok


def test_installer_paths() -> bool:
    print("\nInstaller paths and shortcuts:")
    ok = True
    ok &= check(
        "install dir under LOCALAPPDATA\\Programs",
        "Programs" in str(installer.default_install_dir()),
    )
    ok &= check("desktop folder exists", installer.desktop_dir().exists())
    ok &= check("start menu folder exists", installer.start_menu_dir().exists())

    TMP.mkdir(parents=True, exist_ok=True)
    fake_exe = TMP / "FakeApp.exe"
    fake_exe.write_bytes(b"MZ" + b"\x00" * 1_200_000)
    ok &= check("PE header accepted", installer.looks_like_executable(fake_exe))
    html = TMP / "notfound.exe"
    html.write_bytes(b"<html>404</html>")
    ok &= check("HTML error page rejected", not installer.looks_like_executable(html))

    # Windows refuses to save a .lnk whose target is not a real PE image, so the
    # shortcut test needs an actual executable.
    link = TMP / "shortcut.lnk"
    real_exe = Path("C:/Windows/System32/notepad.exe")
    created, message = installer.create_shortcut(
        link, real_exe, arguments="watch-sim", description="test shortcut"
    )
    ok &= check(f"shortcut created ({message[:44]})", created and link.exists())
    ok &= check("shortcut is a real .lnk", link.stat().st_size > 300)
    link.unlink(missing_ok=True)

    note = installer.write_uninstall_note(TMP)
    ok &= check("uninstall note written", note.exists() and "DISARM AUTOSTART" in note.read_text())
    return ok


def test_download() -> bool:
    print("\nDownload with progress:")
    ok = True
    TMP.mkdir(parents=True, exist_ok=True)
    payload = b"MZ" + b"\x00" * 1_500_000
    served = TMP / "served"
    served.mkdir(exist_ok=True)
    (served / "APB.exe").write_bytes(payload)
    (served / "broken.exe").write_bytes(b"<html>nope</html>")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def log_message(self, *args):  # keep the test output clean
            pass

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        seen: list[tuple[int, int]] = []
        target = TMP / "downloaded.exe"
        installer.download_app(
            f"http://127.0.0.1:{port}/APB.exe", target, lambda done, total: seen.append((done, total))
        )
        ok &= check("file downloaded", target.exists() and target.read_bytes() == payload)
        ok &= check(f"progress reported {len(seen)} times", len(seen) >= 2)
        ok &= check("progress reaches 100%", seen[-1][0] == len(payload))
        ok &= check("no leftover .part file", not target.with_suffix(".exe.part").exists())

        try:
            installer.download_app(f"http://127.0.0.1:{port}/broken.exe", TMP / "broken_out.exe")
            ok &= check("HTML payload rejected", False)
        except RuntimeError as exc:
            ok &= check(f"HTML payload rejected ({str(exc)[:38]}...)", "not a Windows program" in str(exc))

        try:
            installer.download_app(f"http://127.0.0.1:{port}/missing.exe", TMP / "missing.exe")
            ok &= check("404 raises", False)
        except RuntimeError as exc:
            ok &= check("404 reported clearly", "404" in str(exc))
    finally:
        server.shutdown()
        server.server_close()
    return ok


def test_local_copy() -> bool:
    print("\nLocal APB.exe instead of a download:")
    ok = True
    install_dir = TMP / "install"
    source = TMP / "cwd"
    source.mkdir(parents=True, exist_ok=True)
    (source / "APB.exe").write_bytes(b"MZ" + b"\x00" * 1_100_000)

    original = installer.installer_dir
    installer.installer_dir = lambda: source  # type: ignore[assignment]
    try:
        target, message = installer.place_app(install_dir, "http://127.0.0.1:1/never")
        ok &= check(f"local copy used ({message[:32]}...)", target.exists() and "copied" in message)
        ok &= check("no network needed", target.stat().st_size > 1_000_000)
    finally:
        installer.installer_dir = original  # type: ignore[assignment]
    return ok


if __name__ == "__main__":
    results = [test_detection(), test_installer_paths(), test_download(), test_local_copy()]
    print("\nRESULT:", "ALL GOOD" if all(results) else "FAILURES PRESENT")
    sys.exit(0 if all(results) else 1)
