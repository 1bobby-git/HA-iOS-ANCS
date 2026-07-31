"""Capture an ESP-IDF Unity run until its terminal result is printed."""

from __future__ import annotations

import argparse
import sys
import time

import serial


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    pending = b""

    with serial.Serial(args.port, args.baud, timeout=0.1) as connection:
        while time.monotonic() < deadline:
            chunk = connection.read(connection.in_waiting or 1)
            if not chunk:
                continue

            pending += chunk
            while b"\n" in pending:
                raw_line, pending = pending.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                print(line, flush=True)
                if "ANCS_TEST_RESULT failures=" in line:
                    return 0

    if pending:
        print(pending.decode("utf-8", errors="replace"), flush=True)
    print("ANCS_TEST_CAPTURE_TIMEOUT", file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
