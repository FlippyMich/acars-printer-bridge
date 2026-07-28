"""End-to-end bridge test without hardware (transport=file).

Starts the real bridge process, feeds it a job through the RAW port and another
one through the spool folder, then checks what came out.

Usage:  .venv\\Scripts\\python.exe tests\\test_bridge.py
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PY = ROOT / ".venv" / "Scripts" / "python.exe"
CFG = ROOT / "tests" / "config.test.json"
OUT = ROOT / "logs" / "test_output.bin"
SPOOL = ROOT / "tests" / "spool"
PORT = 19100

# What the Windows "Generic / Text Only" driver sends: text plus a form feed.
ACARS_MSG = (
    b"\x1b@"
    b"ACARS MSG - RCVD 1425Z\r\n"
    b"AN D-AIZA/MA EDDF\r\n"
    b"- WEATHER REQUEST -\r\n"
    b"METAR LIRF 271420Z 24012KT 9999 FEW035 SCT100 28/17 Q1013 NOSIG\r\n"
    b"\r\n"
    b"END OF MESSAGE\r\n"
    b"\x0c"
)


def check(label: str, cond: bool) -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    return bool(cond)


def main() -> int:
    print("Bridge end-to-end (RAW port + spool folder):")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    SPOOL.mkdir(parents=True, exist_ok=True)
    for leftover in SPOOL.rglob("*.txt"):
        leftover.unlink()
    for leftover in (ROOT / "logs" / "jobs").glob("*.txt"):
        leftover.unlink()

    process = subprocess.Popen(
        [str(PY), "-m", "acars_bridge", "--config", str(CFG), "run"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ok = True
    try:
        deadline = time.time() + 20
        listening = False
        while time.time() < deadline and not listening:
            with socket.socket() as probe:
                probe.settimeout(0.3)
                listening = probe.connect_ex(("127.0.0.1", PORT)) == 0
            if not listening:
                time.sleep(0.3)
        ok &= check(f"bridge listening on {PORT}", listening)
        if not listening:
            return 1

        with socket.create_connection(("127.0.0.1", PORT), timeout=5) as sock:
            sock.sendall(ACARS_MSG)
            sock.shutdown(socket.SHUT_WR)

        (SPOOL / "telex.txt").write_text(
            "TELEX FROM DISPATCH\nFUEL UPLIFT CONFIRMED 4.8T\n", encoding="utf-8"
        )

        deadline = time.time() + 25
        data = b""
        while time.time() < deadline:
            if OUT.exists():
                data = OUT.read_bytes()
                if b"METAR" in data and b"TELEX" in data:
                    break
            time.sleep(0.5)

        ok &= check("job from the RAW port printed", b"METAR LIRF" in data)
        ok &= check("job from the spool folder printed", b"FUEL UPLIFT CONFIRMED" in data)
        ok &= check("two separate jobs (2 x ESC @)", data.count(b"\x1b@") >= 2)
        ok &= check("timestamp header applied", b"ACARS" in data)
        ok &= check(
            "spool file archived into 'printed'",
            len(list((SPOOL / "printed").glob("*telex.txt"))) == 1,
        )
        ok &= check(
            "job copies kept in logs/jobs",
            len(list((ROOT / "logs" / "jobs").glob("*.txt"))) >= 2,
        )
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        print("\n--- bridge log ---")
        print((output or "").strip()[-1200:])

    print("\nRESULT:", "ALL GOOD" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
