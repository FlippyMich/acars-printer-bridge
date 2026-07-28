"""Persistent configuration (config.json) with defaults and deep merge."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

CONFIG_NAME = "config.json"

DEFAULTS: dict[str, Any] = {
    # How we talk to the printer: "ble" | "serial" | "file" (file = debug sink)
    "transport": "ble",
    # Printer language: "auto" picks catprinter for AE01 devices, else ESC/POS
    "protocol": "auto",
    "ble": {
        # When address is null the printer is looked up by name on every run.
        "address": None,
        "name_filter": "X6",
        # Characteristic we write to. null = auto-detect.
        "write_char_uuid": None,
        # Characteristic the printer notifies on (flow control). null = auto-detect.
        "notify_char_uuid": None,
        "chunk_size": 180,
        "chunk_delay_ms": 20,
        "write_with_response": None,
        "keep_connected": True,
        "connect_timeout": 20.0,
        "scan_timeout": 8.0,
    },
    "serial": {
        "port": "COM5",
        "baudrate": 9600,
        "chunk_size": 256,
        "chunk_delay_ms": 10,
    },
    "file": {
        "path": "logs/raw_output.bin",
    },
    # Cat-printer family only (X6/X6h, GB01, MX05...): text is drawn as a bitmap.
    "catprinter": {
        "energy": 58000,  # darkness: raise if faint, lower if it smudges (0-65535)
        "quality": 51,
        "drawing_mode": "text",  # "text" | "image"
        "feed_steps": 120,  # paper advance after each printout
        "compress": False,  # RLE transfer: faster, not supported by every model
        "font": None,  # null = Consolas / Lucida Console
        "line_spacing": 2,
        "threshold": 160,
        "margin_top": 4,
        "margin_bottom": 4,
    },
    "format": {
        "columns": 32,  # 32 = 58 mm paper, 48 = 80 mm
        "codepage": "cp437",  # ESC/POS only
        "uppercase": False,
        "header": False,  # timestamp header above each printout
        "wrap": True,
        "feed_lines": 4,  # ESC/POS only
        "cut": False,  # ESC/POS only
        "strip_form_feed": True,
    },
    "sources": {
        # RAW port the Windows virtual printer spools jobs to.
        "tcp": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 9100,
            "idle_timeout": 4.0,
            "first_byte_timeout": 15.0,
        },
        # Watched folder: any text file dropped here gets printed.
        "folder": {"enabled": True, "path": "spool", "poll_seconds": 1.0},
    },
    # Follow the simulator: start the bridge when MSFS runs, stop when it quits.
    "autostart": {
        "processes": ["FlightSimulator2024.exe", "FlightSimulator.exe"],
        "poll_seconds": 10.0,
        "stop_when_sim_closes": True,
        "log_file": "logs/bridge.log",
    },
    "ui": {
        "follow_simulator": True,
        "windows_printer_name": "ACARS Printer",
        "windows_port_name": "ACARS_RAW_9100",
    },
    # Loopback port used only as a mutex between bridge instances.
    "lock_port": 49321,
    "log_jobs": True,
}


APP_DIR_NAME = "ACARS Printer Bridge"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Source checkout root (development mode)."""
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Where config, logs and the spool folder live.

    Inside a PyInstaller build the package sits in a temporary folder that is
    wiped on exit, so user data goes to %LOCALAPPDATA% instead.
    """
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME
        base.mkdir(parents=True, exist_ok=True)
        return base
    return project_root()


def config_path(base: Path | None = None) -> Path:
    return (base or data_root()) / CONFIG_NAME


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else data_root() / path


def _merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge(base.get(key), value) if key in base else value
        return merged
    return override


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.json is not valid JSON: {exc}") from exc
        cfg = _merge(cfg, user)
    cfg["_path"] = str(path)
    return cfg


def save(cfg: dict[str, Any], path: Path | None = None) -> Path:
    path = path or Path(cfg.get("_path") or config_path())
    data = {key: value for key, value in cfg.items() if not key.startswith("_")}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
