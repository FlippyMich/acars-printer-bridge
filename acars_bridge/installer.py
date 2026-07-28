"""Installer helpers: fetch APB.exe, place it, create shortcuts.

Kept free of any GUI code so it can be unit tested.
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .config import APP_DIR_NAME
from .system import run_powershell

APP_EXE_NAME = "APB.exe"
INSTALLER_EXE_NAME = "APBinstaller.exe"
SHORTCUT_NAME = "ACARS Printer Bridge.lnk"

# Where the installer looks for the app when it is not shipped next to it.
# Point this at your release asset before publishing the installer.
DEFAULT_DOWNLOAD_URL = (
    "https://github.com/FlippyMich/acars-printer-bridge/releases/latest/download/APB.exe"
)

ProgressCallback = Callable[[int, int], None]


def default_install_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "Programs" / APP_DIR_NAME


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"


def start_menu_dir() -> Path:
    return (
        Path(os.environ.get("APPDATA") or Path.home())
        / "Microsoft/Windows/Start Menu/Programs"
    )


def installer_dir() -> Path:
    """Folder the installer itself was started from."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def local_app_copy() -> Path | None:
    """APB.exe shipped next to the installer (or built locally), if any."""
    candidates = [
        installer_dir() / APP_EXE_NAME,
        Path.cwd() / APP_EXE_NAME,
        Path.cwd() / "dist" / APP_EXE_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 1_000_000:
            return candidate
    return None


def looks_like_executable(path: Path) -> bool:
    """A downloaded 404 page must never be renamed to .exe."""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return False
    except OSError:
        return False
    return path.stat().st_size > 1_000_000


def download_app(
    url: str, target: Path, progress: ProgressCallback | None = None, timeout: float = 60.0
) -> Path:
    """Download the app to `target`, verifying that it really is an executable."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "APB-Installer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except urllib.error.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download failed: HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download failed: {exc}") from exc

    if not looks_like_executable(partial):
        size = partial.stat().st_size if partial.exists() else 0
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"the downloaded file is not a Windows program ({size} bytes) - check the URL"
        )

    target.unlink(missing_ok=True)
    partial.replace(target)
    return target


def place_app(install_dir: Path, url: str, progress: ProgressCallback | None = None) -> tuple[Path, str]:
    """Put APB.exe in place, preferring a local copy over the download."""
    install_dir.mkdir(parents=True, exist_ok=True)
    target = install_dir / APP_EXE_NAME
    local = local_app_copy()
    if local is not None and local.resolve() != target.resolve():
        shutil.copy2(local, target)
        return target, f"copied {APP_EXE_NAME} from {local.parent}"
    if local is not None:
        return target, f"{APP_EXE_NAME} already in place"
    download_app(url, target, progress)
    return target, f"downloaded {APP_EXE_NAME} ({target.stat().st_size // 1024} KB)"


def create_shortcut(
    link: Path,
    target: Path,
    arguments: str = "",
    workdir: Path | None = None,
    icon: Path | None = None,
    description: str = "",
) -> tuple[bool, str]:
    link.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut("{link}")
    $s.TargetPath = "{target}"
    $s.Arguments = "{arguments}"
    $s.WorkingDirectory = "{workdir or target.parent}"
    $s.Description = "{description or APP_DIR_NAME}"
    """
    if icon is not None:
        script += f'    $s.IconLocation = "{icon}"\n'
    script += '    $s.Save()\n    "OK"\n'
    code, out, err = run_powershell(script)
    if code == 0 and link.exists():
        return True, str(link)
    return False, err or out or "shortcut creation failed"


def create_shortcuts(app_exe: Path) -> list[tuple[bool, str]]:
    results = [
        create_shortcut(
            desktop_dir() / SHORTCUT_NAME,
            app_exe,
            description="Print Fenix ACARS messages on a Bluetooth thermal printer",
        ),
        create_shortcut(
            start_menu_dir() / SHORTCUT_NAME,
            app_exe,
            description="Print Fenix ACARS messages on a Bluetooth thermal printer",
        ),
    ]
    return results


def write_uninstall_note(install_dir: Path) -> Path:
    """Plain-text removal instructions - the app installs nothing system wide."""
    note = install_dir / "UNINSTALL.txt"
    note.write_text(
        "ACARS Printer Bridge - how to remove it\n"
        "======================================\n\n"
        "1. Open the app and press DISARM AUTOSTART (removes the startup entry).\n"
        "2. Delete the desktop and Start Menu shortcuts named\n"
        f"   '{SHORTCUT_NAME[:-4]}'.\n"
        f"3. Delete this folder: {install_dir}\n"
        "4. Optional: remove the Windows printer 'ACARS Printer' from\n"
        "   Settings > Bluetooth & devices > Printers & scanners.\n"
        f"5. Optional: delete your settings folder:\n"
        f"   %LOCALAPPDATA%\\{APP_DIR_NAME}\n",
        encoding="utf-8",
    )
    return note


def launch_app(app_exe: Path) -> tuple[bool, str]:
    import subprocess

    try:
        subprocess.Popen([str(app_exe)], cwd=str(app_exe.parent), close_fds=True)
        return True, f"started {app_exe.name}"
    except OSError as exc:
        return False, str(exc)
