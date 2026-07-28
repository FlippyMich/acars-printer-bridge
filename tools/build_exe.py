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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acars_bridge import __version__  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
ASSETS = ROOT / "acars_bridge" / "ui" / "assets"

PUBLISHER = "FlippyMich"
PRODUCT = "ACARS Printer Bridge"

TARGETS = {
    "app": {
        "name": "APB",
        "entry": ROOT / "tools" / "entry_app.py",
        "icon": ASSETS / "app.ico",
        "description": "ACARS Printer Bridge - Fenix A32X to Bluetooth thermal printer",
    },
    "installer": {
        "name": "APBinstaller",
        "entry": ROOT / "tools" / "entry_installer.py",
        "icon": ASSETS / "app.ico",
        "description": "ACARS Printer Bridge Setup",
    },
}


def write_version_file(target: str) -> Path:
    """Windows version resource.

    Without it the exe shows "Unknown publisher" and empty file details, which
    is both unhelpful to users and a red flag for antivirus heuristics.
    """
    spec = TARGETS[target]
    parts = (__version__.split(".") + ["0", "0", "0", "0"])[:4]
    numbers = ", ".join(str(int(part)) for part in parts)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numbers}),
    prodvers=({numbers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{PUBLISHER}'),
        StringStruct('FileDescription', '{spec["description"]}'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', '{spec["name"]}'),
        StringStruct('LegalCopyright',
                     'Copyright (c) 2026 {PUBLISHER} - MIT License'),
        StringStruct('OriginalFilename', '{spec["name"]}.exe'),
        StringStruct('ProductName', '{PRODUCT}'),
        StringStruct('ProductVersion', '{__version__}'),
      ]),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"version_{spec['name']}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def build(target: str) -> Path:
    spec = TARGETS[target]
    print(f"\n=== building {spec['name']}.exe ===")
    version_file = write_version_file(target)
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
        "--version-file",
        str(version_file),
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
