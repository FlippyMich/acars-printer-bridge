"""Windows integration: virtual printer, autostart entry, process checks.

Everything here shells out to PowerShell so the app needs no extra packages.
Calls are blocking - run them in a thread.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

from .config import project_root

log = logging.getLogger("acars.system")

CREATE_NO_WINDOW = 0x08000000
DRIVER_NAME = "Generic / Text Only"
SHORTCUT_NAME = "ACARS Bridge.lnk"


def run_powershell(script: str, timeout: float = 120.0) -> tuple[int, str, str]:
    """Run a PowerShell snippet without flashing a console window."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "PowerShell call timed out"
    except Exception as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)


def run_elevated_script(body: str, timeout: float = 300.0) -> tuple[int, str]:
    """Run a PowerShell script elevated (UAC prompt) and return (code, transcript)."""
    temp_dir = Path(tempfile.gettempdir())
    script_path = temp_dir / "acars_bridge_elevated.ps1"
    log_path = temp_dir / "acars_bridge_elevated.log"
    if log_path.exists():
        log_path.unlink()

    script = (
        f'Start-Transcript -Path "{log_path}" -Force | Out-Null\n'
        "$ErrorActionPreference = 'Stop'\n"
        "$code = 0\n"
        "try {\n"
        f"{body}\n"
        "} catch {\n"
        "    Write-Output \"ERROR: $($_.Exception.Message)\"\n"
        "    $code = 1\n"
        "}\n"
        "Stop-Transcript | Out-Null\n"
        "exit $code\n"
    )
    script_path.write_text(script, encoding="utf-8-sig")

    launcher = (
        "$p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "
        f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{script_path}\"'; "
        "exit $p.ExitCode"
    )
    code, _out, err = run_powershell(launcher, timeout=timeout)
    transcript = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    if err and not transcript:
        transcript = err
    return code, transcript


# ------------------------------------------------------------------- processes
def sim_is_running(process_names: list[str]) -> bool:
    """True when one of the simulator processes is running."""
    if not process_names:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:
        log.warning("Cannot read the process list: %s", exc)
        return False
    running = result.stdout.lower()
    return any(name.lower() in running for name in process_names)


# -------------------------------------------------------------- windows printer
def printer_info(name: str) -> dict[str, str] | None:
    code, out, _err = run_powershell(
        f"$p = Get-Printer -Name '{name}' -ErrorAction SilentlyContinue; "
        'if ($p) { "$($p.Name)|$($p.DriverName)|$($p.PortName)|$($p.PrinterStatus)" }'
    )
    if code != 0 or not out:
        return None
    parts = (out.splitlines()[0].split("|") + ["", "", "", ""])[:4]
    return {"name": parts[0], "driver": parts[1], "port": parts[2], "status": parts[3]}


def install_windows_printer(
    printer_name: str = "ACARS Printer",
    port_name: str = "ACARS_RAW_9100",
    host: str = "127.0.0.1",
    port_number: int = 9100,
) -> tuple[bool, str]:
    """Create the virtual printer the Fenix EFB will list. Prompts for UAC."""
    body = f"""
    $printerName = '{printer_name}'
    $portName    = '{port_name}'
    $driverName  = '{DRIVER_NAME}'

    if (-not (Get-PrinterDriver -Name $driverName -ErrorAction SilentlyContinue)) {{
        Add-PrinterDriver -Name $driverName
        Write-Output "driver installed"
    }} else {{
        Write-Output "driver already present"
    }}

    if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) {{
        Add-PrinterPort -Name $portName -PrinterHostAddress '{host}' -PortNumber {port_number}
        Write-Output "port created"
    }} else {{
        Write-Output "port already present"
    }}

    if (-not (Get-Printer -Name $printerName -ErrorAction SilentlyContinue)) {{
        Add-Printer -Name $printerName -DriverName $driverName -PortName $portName
        Write-Output "printer created"
    }} else {{
        Set-Printer -Name $printerName -DriverName $driverName -PortName $portName
        Write-Output "printer updated"
    }}
    Set-Printer -Name $printerName -KeepPrintedJobs $false
    Write-Output "OK"
    """
    code, transcript = run_elevated_script(body)
    return code == 0, transcript


def remove_windows_printer(
    printer_name: str = "ACARS Printer", port_name: str = "ACARS_RAW_9100"
) -> tuple[bool, str]:
    body = f"""
    if (Get-Printer -Name '{printer_name}' -ErrorAction SilentlyContinue) {{
        Remove-Printer -Name '{printer_name}'
        Write-Output "printer removed"
    }}
    if (Get-PrinterPort -Name '{port_name}' -ErrorAction SilentlyContinue) {{
        try {{ Remove-PrinterPort -Name '{port_name}'; Write-Output "port removed" }}
        catch {{ Write-Output "port still in use, try again in a few seconds" }}
    }}
    Write-Output "OK"
    """
    code, transcript = run_elevated_script(body)
    return code == 0, transcript


# ------------------------------------------------------------------- autostart
def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"


def autostart_shortcut() -> Path:
    return startup_dir() / SHORTCUT_NAME


def autostart_installed() -> bool:
    return autostart_shortcut().exists()


def pythonw_path() -> Path:
    """Windowless interpreter of the current environment."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def watcher_command() -> tuple[Path, str, Path]:
    """(target, arguments, working directory) that starts the headless watcher.

    Frozen build: APB.exe watch-sim. Source checkout: pythonw -m acars_bridge.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return exe, "watch-sim", exe.parent
    return pythonw_path(), "-m acars_bridge watch-sim", project_root()


def install_autostart() -> tuple[bool, str]:
    target, arguments, workdir = watcher_command()
    link = autostart_shortcut()
    script = f"""
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut("{link}")
    $s.TargetPath = "{target}"
    $s.Arguments = "{arguments}"
    $s.WorkingDirectory = "{workdir}"
    $s.WindowStyle = 7
    $s.Description = "Start the ACARS bridge together with MSFS"
    $s.Save()
    "OK"
    """
    code, out, err = run_powershell(script)
    if code == 0 and link.exists():
        return True, f"Autostart armed: {link}"
    return False, err or out or "could not create the shortcut"


def remove_autostart() -> tuple[bool, str]:
    link = autostart_shortcut()
    try:
        if link.exists():
            link.unlink()
    except OSError as exc:
        return False, str(exc)
    stopped = stop_background_watchers()
    suffix = f", stopped {stopped} background process(es)" if stopped else ""
    return True, f"Autostart disarmed{suffix}"


WATCHER_FILTER = (
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { "
    "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe' -or $_.Name -eq 'APB.exe') "
    "-and $_.CommandLine -like '*watch-sim*' }"
)


def background_watcher_running() -> bool:
    # Match 'watch-sim' specifically: the GUI itself also runs as
    # "pythonw -m acars_bridge ..." / "APB.exe", and must never count as a watcher.
    code, out, _err = run_powershell(f"@({WATCHER_FILTER}).Count")
    if code != 0 or not out:
        return False
    try:
        return int(out.splitlines()[-1].strip()) > 0
    except ValueError:
        return False


def stop_background_watchers() -> int:
    # Only watch-sim processes: killing every app process would also kill the
    # window you are clicking in.
    code, out, _err = run_powershell(
        f"$n = 0; {WATCHER_FILTER} | ForEach-Object {{ "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }}; $n"
    )
    if code != 0 or not out:
        return 0
    try:
        return int(out.splitlines()[-1].strip())
    except ValueError:
        return 0


def start_background_watcher() -> tuple[bool, str]:
    target = pythonw_path()
    try:
        subprocess.Popen(
            [str(target), "-m", "acars_bridge", "watch-sim"],
            cwd=str(project_root()),
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True, "Background watcher started"
    except Exception as exc:
        return False, str(exc)


# ------------------------------------------------------------------------ misc
def open_path(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))  # noqa: S606 - Windows only, user initiated


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)
