"""Command line interface."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path

from . import __version__, config, system, transport
from .bridge import Bridge, print_calibration, print_file, print_test_page
from .watcher import InstanceLock, watch_simulator

DISCORD_URL = "https://discord.gg/bFY5wCf6CK"


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("bleak").setLevel(logging.DEBUG if verbose else logging.WARNING)


def add_file_logging(path: Path, max_bytes: int = 2_000_000) -> None:
    """Log to a file - needed when the bridge runs without a console."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_bytes:
        path.replace(path.with_suffix(path.suffix + ".old"))
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s"))
    logging.getLogger().addHandler(handler)


def _hold_lock(cfg: dict) -> bool:
    lock = InstanceLock(int(cfg.get("lock_port", 49321)))
    if lock.acquire():
        cfg["_lock"] = lock  # kept for the process lifetime
        return True
    logging.getLogger("acars").error(
        "Another bridge instance is already running - most likely the background watcher "
        "installed by the autostart option. You do not need to start it twice."
    )
    return False


# ------------------------------------------------------------------- commands
async def cmd_scan(args: argparse.Namespace, cfg: dict) -> int:
    print(f"Scanning for {args.timeout:.0f}s (switch the printer on)...\n")
    items = await transport.scan_devices(args.timeout)
    if not items:
        print("No BLE device found.")
        return 1
    print(f"{'NAME':<28} {'ADDRESS':<19} {'RSSI':>5}  SERVICES")
    print("-" * 88)
    for device, adv in items:
        name = (adv.local_name or device.name or "(unnamed)")[:27]
        services = ", ".join(uuid.split("-")[0] for uuid in (adv.service_uuids or [])) or "-"
        print(f"{name:<28} {device.address:<19} {adv.rssi or 0:>5}  {services[:34]}")
    print("\nThen run:  acars-bridge probe --address <ADDRESS> --save")
    return 0


async def cmd_probe(args: argparse.Namespace, cfg: dict) -> int:
    address = args.address or cfg["ble"].get("address")
    if not address:
        address = (await transport.BleTransport(cfg["ble"]).find_device()).address
    print(f"Connecting to {address}...\n")
    info = await transport.probe_device(address, timeout=cfg["ble"].get("connect_timeout", 20.0))
    print(f"Address : {info['address']}")
    print(f"MTU     : {info['mtu']}\n")
    for service in info["services"]:
        print(f"SERVICE {service['uuid']}  ({service['description']})")
        for char in service["characteristics"]:
            props = ",".join(char["properties"])
            print(f"    CHAR {char['uuid']}  [{props}]  {char['description']}")

    chosen = transport.pick_write_characteristic(info)
    if chosen is None:
        print("\nWARNING: no writable characteristic - this is not a printer we can drive.")
        return 2
    print(f"\nSuggested write characteristic: {chosen[0]}  (service {chosen[1]})")
    if chosen[0].lower().startswith("0000ae01"):
        print("Detected a cat-printer device: raster protocol, no ESC/POS.")
    if args.save:
        cfg["ble"]["address"] = info["address"]
        cfg["ble"]["write_char_uuid"] = chosen[0]
        print(f"\nSaved to {config.save(cfg)}")
    else:
        print("\nRe-run with --save to store these values in config.json.")
    return 0


async def cmd_test(args: argparse.Namespace, cfg: dict) -> int:
    if args.columns:
        cfg["format"]["columns"] = args.columns
    print("Sending test page...")
    await print_test_page(cfg)
    print("Done. If nothing came out, see the Troubleshooting section of the README.")
    return 0


async def cmd_print(args: argparse.Namespace, cfg: dict) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        return 1
    await print_file(cfg, path)
    return 0


async def cmd_calibrate(args: argparse.Namespace, cfg: dict) -> int:
    levels = args.levels or [40000, 50000, 58000, 65535]
    print(f"Printing {len(levels)} samples: {', '.join(str(v) for v in levels)}")
    await print_calibration(cfg, levels)
    print("\nPick the crispest one and set catprinter.energy in config.json.")
    return 0


async def cmd_preview(args: argparse.Namespace, cfg: dict) -> int:
    from . import escpos, raster

    if args.path:
        text = escpos.decode_raw(Path(args.path).read_bytes())
        title = None
    else:
        text, title = escpos.TEST_PAGE, "TEST"

    bridge = Bridge(cfg)
    page = escpos.compose_text(text, cfg["format"], title=title)
    if bridge.protocol != "catprinter":
        print("ESC/POS device: the printer uses its own fonts. Text that would be sent:\n")
        print(page)
        return 0

    cat = dict(cfg.get("catprinter", {}))
    rows = raster.render_text(page, {**cat, "columns": int(cfg["format"].get("columns", 32))})
    out = config.resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raster.rows_to_image(rows).save(out)
    payload = bridge.build_payload(text, title=title)
    print(raster.rows_to_text_preview(rows))
    print(f"\n{len(rows)} dot rows, {len(payload)} bytes to send.")
    print(f"Preview written to {out}")
    return 0


async def cmd_run(args: argparse.Namespace, cfg: dict) -> int:
    if not _hold_lock(cfg):
        return 1
    bridge = Bridge(cfg)
    try:
        await bridge.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


async def cmd_watch_sim(args: argparse.Namespace, cfg: dict) -> int:
    if not _hold_lock(cfg):
        return 1
    try:
        await watch_simulator(cfg)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


async def cmd_ui(args: argparse.Namespace, cfg: dict) -> int:
    from .ui.app import launch

    launch(cfg)
    return 0


async def cmd_setup(args: argparse.Namespace, cfg: dict) -> int:
    """Re-run the setup wizard (printer detection, shortcuts, autostart)."""
    from .ui.wizard import launch

    launch(cfg)
    return 0


async def cmd_doctor(args: argparse.Namespace, cfg: dict) -> int:
    ok = True
    print(f"acars-bridge {__version__}   config: {cfg['_path']}\n")
    print(f"[ ] transport = {cfg['transport']}")

    if cfg["transport"] == "ble":
        ble = cfg["ble"]
        print(f"    address         : {ble.get('address') or '(lookup by name)'}")
        print(f"    write_char_uuid : {ble.get('write_char_uuid') or '(auto-detect)'}")
        try:
            printer = transport.BleTransport(ble)
            await printer.connect()
            print("[OK] printer reachable, write characteristic found")
            await printer.close()
        except Exception as exc:
            ok = False
            print(f"[!!] printer NOT reachable: {exc}")

    tcp = cfg["sources"]["tcp"]
    if tcp.get("enabled", True):
        port = int(tcp.get("port", 9100))
        with socket.socket() as sock:
            sock.settimeout(0.5)
            busy = sock.connect_ex((tcp.get("host", "127.0.0.1"), port)) == 0
        print(f"[{'!!' if busy else 'OK'}] RAW port {port} {'IN USE' if busy else 'free'}")

    printer_name = cfg["ui"]["windows_printer_name"]
    info = await asyncio.to_thread(system.printer_info, printer_name)
    if info:
        print(f"[OK] Windows printer '{info['name']}' -> {info['driver']} on {info['port']}")
    else:
        ok = False
        print(f"[!!] Windows printer '{printer_name}' missing - install it from the app")

    armed = system.autostart_installed()
    running = await asyncio.to_thread(system.background_watcher_running)
    print(
        f"[{'OK' if armed else ' '}] autostart {'armed' if armed else 'not armed'}"
        f"{' (background watcher running)' if running else ''}"
    )

    print("\nResult:", "ready to fly" if ok else "issues need fixing")
    return 0 if ok else 1


COMMANDS = {
    "scan": cmd_scan,
    "probe": cmd_probe,
    "test": cmd_test,
    "print": cmd_print,
    "preview": cmd_preview,
    "calibrate": cmd_calibrate,
    "run": cmd_run,
    "watch-sim": cmd_watch_sim,
    "doctor": cmd_doctor,
    "ui": cmd_ui,
    "setup": cmd_setup,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acars-bridge",
        description="Bridge between the Fenix A32X ACARS printer (MSFS) and a Bluetooth "
        "thermal printer.",
        epilog=f"Community and support: {DISCORD_URL}",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", type=Path, default=None, help="path to config.json")
    parser.add_argument("--version", action="version", version=f"acars-bridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="list nearby Bluetooth LE devices")
    scan.add_argument("--timeout", type=float, default=10.0)

    probe = sub.add_parser("probe", help="show services/characteristics of a printer")
    probe.add_argument("--address", help="BLE address, e.g. AA:BB:CC:DD:EE:FF")
    probe.add_argument("--save", action="store_true", help="store address and UUID in config.json")

    test = sub.add_parser("test", help="print a test page")
    test.add_argument("--columns", type=int, help="columns (32 = 58 mm, 48 = 80 mm)")

    printer = sub.add_parser("print", help="print a text file")
    printer.add_argument("path")

    preview = sub.add_parser("preview", help="render a PNG preview instead of printing")
    preview.add_argument("path", nargs="?", help="text file (default: test page)")
    preview.add_argument("--out", default="logs/preview.png")

    calibrate = sub.add_parser("calibrate", help="print samples at several darkness levels")
    calibrate.add_argument("levels", nargs="*", type=int, help="energy values (0-65535)")

    sub.add_parser("run", help="run the bridge in the foreground")
    sub.add_parser("watch-sim", help="run the bridge only while MSFS is open")
    sub.add_parser("ui", help="open the desktop app")
    sub.add_parser("setup", help="re-run the setup wizard (re-detect the printer)")
    sub.add_parser("doctor", help="check the whole setup")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    cfg = config.load(args.config)
    if args.command == "watch-sim":
        log_file = cfg.get("autostart", {}).get("log_file")
        if log_file:
            add_file_logging(config.resolve_path(log_file))
    try:
        return asyncio.run(COMMANDS[args.command](args, cfg))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except transport.PrinterError as exc:
        print(f"\nPRINTER ERROR: {exc}", file=sys.stderr)
        return 1
