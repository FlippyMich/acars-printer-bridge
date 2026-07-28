"""Build APB.exe and APBinstaller.exe with PyInstaller.

    .venv\\Scripts\\python.exe tools\\build_exe.py            (both)
    .venv\\Scripts\\python.exe tools\\build_exe.py app        (app only)
    .venv\\Scripts\\python.exe tools\\build_exe.py installer

Output lands in dist\\. Run tools/build_assets.py first if you changed an icon.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
ASSETS = ROOT / "acars_bridge" / "ui" / "assets"

TARGETS = {
    "app": {
        "name": "APB",
        "entry": ROOT / "tools" / "entry_app.py",
        "icon": ASSETS / "app.ico",
    },
    "installer": {
        "name": "APBinstaller",
        "entry": ROOT / "tools" / "entry_installer.py",
        "icon": ASSETS / "app.ico",
    },
}


def build(target: str) -> Path:
    spec = TARGETS[target]
    print(f"\n=== building {spec['name']}.exe ===")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        str(spec["name"]),
        "--icon",
        str(spec["icon"]),
        "--add-data",
        f"{ASSETS}{os_sep()}acars_bridge/ui/assets",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        "--hidden-import",
        "acars_bridge.ui.app",
        "--hidden-import",
        "acars_bridge.ui.wizard",
        str(spec["entry"]),
    ]
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed for {spec['name']}")
    exe = DIST / f"{spec['name']}.exe"
    print(f"built {exe} ({exe.stat().st_size // 1024} KB)")
    return exe


def os_sep() -> str:
    """--add-data uses ';' on Windows and ':' elsewhere."""
    return ";" if sys.platform == "win32" else ":"


def main() -> int:
    which = sys.argv[1:] or ["app", "installer"]
    unknown = [name for name in which if name not in TARGETS]
    if unknown:
        raise SystemExit(f"unknown target(s): {', '.join(unknown)}")

    DIST.mkdir(exist_ok=True)
    built = [build(name) for name in which]

    print("\n=== done ===")
    for exe in built:
        print(f"  {exe}")
    print(
        "\nShip APBinstaller.exe on its own: it downloads APB.exe from the release URL in\n"
        "acars_bridge/installer.py. If you drop APB.exe next to the installer, it is used\n"
        "directly instead of downloading."
    )
    if (WORK).exists():
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
