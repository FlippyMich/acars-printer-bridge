"""Async plumbing for the UI: one asyncio loop in a background thread."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from concurrent.futures import Future
from datetime import datetime
from typing import Any, Awaitable, Callable


class AsyncRuntime:
    """Runs coroutines on a private event loop so the UI never blocks."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="acars-async", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(
        self,
        coro: Awaitable[Any],
        on_done: Callable[[Future[Any]], None] | None = None,
    ) -> Future[Any]:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)  # type: ignore[arg-type]
        if on_done is not None:
            future.add_done_callback(on_done)
        return future

    def call_soon(self, callback: Callable[[], None]) -> None:
        self.loop.call_soon_threadsafe(callback)

    def shutdown(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


class QueueLogHandler(logging.Handler):
    """Pushes log records to a queue the UI drains on the main thread."""

    def __init__(self, sink: queue.Queue) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        stamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        try:
            self.sink.put_nowait(("log", stamp, record.levelname, message))
        except queue.Full:
            pass


def install_log_handler(sink: queue.Queue, level: int = logging.INFO) -> QueueLogHandler:
    handler = QueueLogHandler(sink)
    handler.setLevel(level)
    root = logging.getLogger()
    root.setLevel(min(root.level or logging.INFO, level))
    root.addHandler(handler)
    logging.getLogger("bleak").setLevel(logging.WARNING)
    return handler
