"""Follow the simulator: keep the bridge online only while MSFS is running."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any, Callable

from .bridge import Bridge
from .system import sim_is_running

log = logging.getLogger("acars.watcher")

BridgeCallback = Callable[[Bridge | None], None]


class InstanceLock:
    """Loopback socket used as a mutex, so two bridges never run at once.

    Two bridges would fight over the RAW port and over the printer itself.
    """

    def __init__(self, port: int = 49321) -> None:
        self.port = port
        self._socket: socket.socket | None = None

    @property
    def held(self) -> bool:
        return self._socket is not None

    def acquire(self) -> bool:
        if self._socket is not None:
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._socket = sock
        return True

    def release(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def another_instance_running(port: int = 49321) -> bool:
    probe = InstanceLock(port)
    if probe.acquire():
        probe.release()
        return False
    return True


async def watch_simulator(
    cfg: dict[str, Any],
    on_bridge: BridgeCallback | None = None,
) -> None:
    """Start the bridge when the simulator appears, stop it when it quits."""
    auto = cfg.get("autostart", {})
    names = list(auto.get("processes", ["FlightSimulator2024.exe"]))
    poll = float(auto.get("poll_seconds", 10.0))
    stop_with_sim = bool(auto.get("stop_when_sim_closes", True))

    bridge: Bridge | None = None
    task: asyncio.Task[Any] | None = None
    log.info("Watching for %s (every %.0fs).", " / ".join(names), poll)

    def announce(value: Bridge | None) -> None:
        if on_bridge is not None:
            on_bridge(value)

    try:
        while True:
            running = await asyncio.to_thread(sim_is_running, names)

            if task is not None and task.done():
                error = task.exception()
                if error:
                    log.error("The bridge stopped with an error: %s", error)
                bridge, task = None, None
                announce(None)

            if running and task is None:
                log.info("Simulator detected: starting the bridge.")
                bridge = Bridge(cfg)
                task = asyncio.create_task(bridge.run(), name="bridge")
                announce(bridge)
            elif not running and task is not None and stop_with_sim:
                log.info("Simulator closed: stopping the bridge and releasing the printer.")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if bridge is not None:
                    await bridge.transport.close()
                bridge, task = None, None
                announce(None)

            await asyncio.sleep(poll)
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if bridge is not None:
            await bridge.transport.close()
        announce(None)
