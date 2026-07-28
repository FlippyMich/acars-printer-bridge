"""Job sources: the RAW 9100 port and the watched folder."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("acars.sources")

JobHandler = Callable[[bytes, str], Awaitable[None]]

TEXT_SUFFIXES = {".prn", ".txt", ".raw", ".acars", ""}


async def run_raw_server(cfg: dict[str, Any], handler: JobHandler) -> None:
    """RAW/JetDirect server: this is where the Windows virtual printer spools to."""
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 9100))
    idle_timeout = float(cfg.get("idle_timeout", 4.0))
    first_byte_timeout = float(cfg.get("first_byte_timeout", 15.0))

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("Incoming job from %s", peer)
        try:
            data = await _read_job(reader, idle_timeout, first_byte_timeout)
        except Exception as exc:
            log.error("Error while reading the job: %s", exc)
            data = b""
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        if data.strip():
            await handler(data, f"tcp:{port}")
        else:
            log.info("Empty job ignored.")

    server = await asyncio.start_server(on_client, host, port)
    log.info("Listening for print jobs on %s:%d (RAW).", host, port)
    async with server:
        await server.serve_forever()


async def _read_job(
    reader: asyncio.StreamReader, idle_timeout: float, first_byte_timeout: float
) -> bytes:
    """Read one complete job.

    The Windows RAW port monitor normally closes the socket at the end of a job,
    but not always: if it stays open we treat silence as end of job instead of
    blocking forever.
    """
    buffer = bytearray()
    while True:
        timeout = idle_timeout if buffer else first_byte_timeout
        try:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        except asyncio.TimeoutError:
            if buffer:
                log.debug("End of job after %.1fs of silence.", idle_timeout)
            break
        if not chunk:
            break
        buffer += chunk
    return bytes(buffer)


async def run_folder_watcher(cfg: dict[str, Any], handler: JobHandler) -> None:
    """Print any text file dropped into the spool folder."""
    from .config import resolve_path

    folder = resolve_path(cfg.get("path", "spool"))
    folder.mkdir(parents=True, exist_ok=True)
    done_dir = folder / "printed"
    done_dir.mkdir(exist_ok=True)
    poll = float(cfg.get("poll_seconds", 1.0))
    sizes: dict[Path, int] = {}

    log.info("Watching folder %s", folder)
    while True:
        try:
            for entry in sorted(folder.glob("*")):
                if entry.is_dir() or entry.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                size = entry.stat().st_size
                if size == 0:
                    continue
                # wait for the file to stop growing before printing it
                if sizes.get(entry) != size:
                    sizes[entry] = size
                    continue
                sizes.pop(entry, None)
                data = entry.read_bytes()
                await handler(data, f"file:{entry.name}")
                _archive(entry, done_dir)
        except Exception as exc:
            log.error("Folder watcher error: %s", exc)
        await asyncio.sleep(poll)


def _archive(entry: Path, done_dir: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = done_dir / f"{stamp}-{entry.name}"
    try:
        entry.replace(target)
    except OSError:
        try:
            entry.unlink()
        except OSError as exc:
            log.warning("Cannot remove %s: %s", entry, exc)
