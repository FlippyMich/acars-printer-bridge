"""Simulator watcher tests.

A `ping.exe` process stands in for the simulator: the test starts it and kills
it, so both transitions are exercised for real. transport=file, no printer
needed.

Usage:  .venv\\Scripts\\python.exe tests\\test_watcher.py
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acars_bridge.system import CREATE_NO_WINDOW, sim_is_running  # noqa: E402
from acars_bridge.watcher import InstanceLock, another_instance_running, watch_simulator  # noqa: E402

PORT = 19101
OUT = ROOT / "logs" / "test_watcher_output.bin"

CFG = {
    "transport": "file",
    "protocol": "escpos",
    "file": {"path": "logs/test_watcher_output.bin"},
    "format": {"columns": 32, "codepage": "cp437", "feed_lines": 1},
    "sources": {
        "tcp": {"enabled": True, "host": "127.0.0.1", "port": PORT, "idle_timeout": 1.0},
        "folder": {"enabled": False},
    },
    "autostart": {
        "processes": ["ping.exe"],
        "poll_seconds": 0.5,
        "stop_when_sim_closes": True,
    },
    "log_jobs": False,
}


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def port_open(port: int = PORT) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


async def wait_for(predicate, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await asyncio.to_thread(predicate):
            return True
        await asyncio.sleep(0.3)
    return False


def test_detection() -> bool:
    print("Simulator process detection:")
    ok = True
    ok &= check("running process detected (explorer.exe)", sim_is_running(["explorer.exe"]))
    ok &= check(
        "missing process not detected", not sim_is_running(["ThisProcessDoesNotExist12345.exe"])
    )
    ok &= check("comparison is case insensitive", sim_is_running(["EXPLORER.EXE"]))
    ok &= check("empty list means no simulator", not sim_is_running([]))
    return ok


def test_instance_lock() -> bool:
    print("\nSingle instance lock:")
    ok = True
    first = InstanceLock(49351)
    ok &= check("first acquire succeeds", first.acquire())
    second = InstanceLock(49351)
    ok &= check("second acquire is refused", not second.acquire())
    ok &= check("probe reports the port busy", another_instance_running(49351))
    first.release()
    ok &= check("after release the port is free again", not another_instance_running(49351))
    return ok


async def test_full_cycle() -> bool:
    print("\nFull cycle: simulator starts, prints, quits:")
    ok = True
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    watcher = asyncio.create_task(watch_simulator(CFG))
    sim = None
    try:
        ok &= check("bridge stays offline while the simulator is closed", not await wait_for(port_open, 4))

        sim = subprocess.Popen(
            ["ping", "-n", "120", "127.0.0.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        ok &= check("bridge starts when the simulator appears", await wait_for(port_open, 25))

        _, writer = await asyncio.open_connection("127.0.0.1", PORT)
        writer.write(b"AUTOSTART OK\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        ok &= check(
            "job printed by the auto-started bridge",
            await wait_for(lambda: OUT.exists() and b"AUTOSTART OK" in OUT.read_bytes(), 15),
        )

        sim.kill()
        sim.wait(timeout=10)
        sim = None
        ok &= check(
            "bridge stops (printer released) when the simulator quits",
            await wait_for(lambda: not port_open(), 25),
        )
    finally:
        if sim is not None:
            sim.kill()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    ok &= check("no port left listening after shutdown", not await wait_for(port_open, 3))
    return ok


async def main() -> int:
    results = [test_detection(), test_instance_lock(), await test_full_cycle()]
    print("\nRESULT:", "ALL GOOD" if all(results) else "FAILURES PRESENT")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
