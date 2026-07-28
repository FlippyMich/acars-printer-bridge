"""Job queue, rendering and delivery to the printer."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import escpos
from .config import resolve_path
from .sources import run_folder_watcher, run_raw_server
from .transport import PrinterError, build_transport

log = logging.getLogger("acars.bridge")

JobCallback = Callable[[str, str], None]


def resolve_protocol(cfg: dict[str, Any]) -> str:
    """Which language the printer speaks: ESC/POS or cat-printer raster."""
    protocol = str(cfg.get("protocol", "auto")).lower()
    if protocol != "auto":
        return protocol
    if str(cfg.get("transport", "ble")).lower() == "ble":
        uuid = (cfg.get("ble", {}).get("write_char_uuid") or "").lower()
        if uuid.startswith("0000ae01") or uuid.startswith("0000ae03"):
            return "catprinter"
    return "escpos"


class Bridge:
    def __init__(self, cfg: dict[str, Any], on_job: JobCallback | None = None) -> None:
        self.cfg = cfg
        self.protocol = resolve_protocol(cfg)
        self.transport = build_transport(cfg)
        self.queue: asyncio.Queue[tuple[bytes, str]] = asyncio.Queue()
        self.jobs_dir = resolve_path("logs/jobs")
        self.on_job = on_job
        self.jobs_printed = 0
        log.info("Print protocol: %s", self.protocol)

    # ---------------------------------------------------------------- rendering
    def build_payload(self, text: str, *, title: str | None = None) -> bytes:
        fmt = self.cfg["format"]
        if self.protocol != "catprinter":
            return escpos.build_job(text, fmt, title=title)

        # Cat printers have no fonts: draw the text and send it as a bitmap.
        from . import catprinter, raster

        page = escpos.compose_text(text, fmt, title=title)
        cat = dict(self.cfg.get("catprinter", {}))
        rows = raster.render_text(page, {**cat, "columns": int(fmt.get("columns", 32))})
        log.debug("Rasterized %d dot rows.", len(rows))
        return catprinter.build_print(
            rows,
            energy=int(cat.get("energy", 58000)),
            quality=int(cat.get("quality", 0x33)),
            drawing_mode=cat.get("drawing_mode", "text"),
            feed_steps=int(cat.get("feed_steps", 120)),
            compress=bool(cat.get("compress", False)),
        )

    # ----------------------------------------------------------------- printing
    async def enqueue(self, data: bytes, origin: str) -> None:
        await self.queue.put((data, origin))

    async def print_text(self, text: str, *, title: str | None = None) -> None:
        await self.transport.send(self.build_payload(text, title=title))

    async def _worker(self) -> None:
        while True:
            data, origin = await self.queue.get()
            try:
                if self.protocol == "escpos" and escpos.looks_binary_escpos(data):
                    log.info(
                        "Job from %s (%d bytes) is already binary ESC/POS: passing through.",
                        origin,
                        len(data),
                    )
                    await self.transport.send(data)
                    self.jobs_printed += 1
                    log.info("Job done.")
                    continue

                text = escpos.decode_raw(data)
                preview = [line.strip() for line in text.strip().splitlines()[:2]]
                log.info(
                    "Printing job from %s (%d bytes): %s",
                    origin,
                    len(data),
                    " | ".join(preview) or "(empty)",
                )
                if self.cfg.get("log_jobs"):
                    self._archive_job(text, origin)
                await self.print_text(text)
                self.jobs_printed += 1
                log.info("Job done.")
                if self.on_job is not None:
                    self.on_job(origin, text)
            except PrinterError as exc:
                log.error("PRINT FAILED: %s", exc)
            except Exception as exc:
                log.exception("Unexpected error while printing: %s", exc)
            finally:
                self.queue.task_done()

    def _archive_job(self, text: str, origin: str) -> None:
        try:
            self.jobs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe = "".join(c for c in origin if c.isalnum() or c in "-_.") or "job"
            (self.jobs_dir / f"{stamp}-{safe}.txt").write_text(text, encoding="utf-8")
        except OSError as exc:
            log.debug("Cannot archive the job: %s", exc)

    # ---------------------------------------------------------------------- run
    async def run(self) -> None:
        tasks: list[asyncio.Task[Any]] = [asyncio.create_task(self._worker(), name="printer")]

        sources = self.cfg.get("sources", {})
        tcp_cfg = sources.get("tcp", {})
        if tcp_cfg.get("enabled", True):
            tasks.append(asyncio.create_task(run_raw_server(tcp_cfg, self.enqueue), name="tcp"))
        folder_cfg = sources.get("folder", {})
        if folder_cfg.get("enabled", True):
            tasks.append(
                asyncio.create_task(run_folder_watcher(folder_cfg, self.enqueue), name="folder")
            )

        if len(tasks) == 1:
            raise RuntimeError("No job source enabled in config.json (sources).")

        # Connect up front; if the printer is off we retry on the first job.
        try:
            await self.transport.connect()
        except Exception as exc:
            log.warning("Printer not reachable yet (%s). Will retry on the first job.", exc)

        log.info("Bridge online.")
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await self.transport.close()
            log.info("Bridge offline.")


async def print_file(cfg: dict[str, Any], path: Path) -> None:
    bridge = Bridge(cfg)
    try:
        await bridge.print_text(escpos.decode_raw(path.read_bytes()))
    finally:
        await bridge.transport.close()


async def print_test_page(cfg: dict[str, Any]) -> None:
    bridge = Bridge(cfg)
    try:
        await bridge.print_text(escpos.TEST_PAGE, title="TEST")
    finally:
        await bridge.transport.close()


async def print_calibration(cfg: dict[str, Any], levels: list[int]) -> None:
    """Print the same sample at several energy levels to pick the best one."""
    bridge = Bridge(cfg)
    if bridge.protocol != "catprinter":
        raise RuntimeError("Energy calibration only applies to cat-printer devices.")

    sample = (
        "ABCDEFGHIJKLMNOP 0123456789\n"
        "abcdefghijklmnop  ACARS MSG\n"
        "WIND 24012KT  QNH 1013  M05"
    )
    original_feed = bridge.cfg["catprinter"].get("feed_steps", 120)
    try:
        for index, level in enumerate(levels):
            bridge.cfg["catprinter"]["energy"] = int(level)
            bridge.cfg["catprinter"]["feed_steps"] = (
                original_feed if index == len(levels) - 1 else 30
            )
            log.info("Printing sample at energy %d", level)
            await bridge.print_text(f"--- ENERGY {level} ---\n{sample}")
    finally:
        bridge.cfg["catprinter"]["feed_steps"] = original_feed
        await bridge.transport.close()
