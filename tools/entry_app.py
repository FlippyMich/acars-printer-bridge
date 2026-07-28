"""PyInstaller entry point for APB.exe.

With no arguments it opens the app window; with arguments it behaves as the CLI
(APB.exe watch-sim, APB.exe doctor, ...), which is what the autostart shortcut
and the installer rely on.

The exe is built windowed (no console), so text commands attach to the calling
terminal - otherwise `APB.exe doctor` would print into the void.
"""

import multiprocessing
import sys

GUI_COMMANDS = {"ui", "setup", "watch-sim"}
ATTACH_PARENT_PROCESS = -1


STD_HANDLES = {1: -11, 2: -12}  # stdout, stderr


def _wrap_std_handle(fd: int):
    """Bind a text stream to the real Win32 std handle.

    In a windowed build the CRT file descriptors are not usable, but the OS
    handle is still there when the user redirects (`APB.exe doctor > log.txt`),
    so we open a fresh descriptor onto it.
    """
    import ctypes
    import io
    import msvcrt
    import os

    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel32.GetStdHandle(STD_HANDLES[fd])
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise OSError("no standard handle")
    new_fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    return io.TextIOWrapper(
        io.FileIO(new_fd, "w", closefd=False),
        encoding="utf-8",
        errors="replace",
        line_buffering=True,
    )


def attach_console() -> None:
    """Give a windowed build a usable stdout/stderr.

    Three cases: output already redirected to a file or pipe (keep it), started
    from a terminal (attach to it), or double-clicked (open a console).
    """
    try:
        sys.stdout = _wrap_std_handle(1)
        sys.stderr = _wrap_std_handle(2)
        return
    except Exception:
        pass
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
    except Exception:
        pass  # no console available: keep going silently


def bind_redirected_output() -> None:
    """Attach to redirected stdout/stderr only, never open a console window.

    Lets `APB.exe ui 2> err.txt` surface a crash without popping a console up
    for people who just double-click the app.
    """
    try:
        sys.stdout = _wrap_std_handle(1)
        sys.stderr = _wrap_std_handle(2)
    except Exception:
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    argv = sys.argv[1:] or ["ui"]
    if argv[0] in GUI_COMMANDS:
        bind_redirected_output()
    else:
        attach_console()

    from acars_bridge.cli import main

    sys.exit(main(argv))
