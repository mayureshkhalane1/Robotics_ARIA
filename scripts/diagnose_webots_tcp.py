#!/usr/bin/env python3
"""Diagnose ARIA <-> Webots TCP connection.

Checks:
1. IPv4 connection to Webots controller.
2. Small get_state response without camera.
3. Camera get_state response size/time.

Run while Webots simulation is playing:
    uv run python scripts/diagnose_webots_tcp.py
"""

from __future__ import annotations

import json
import socket
import time

HOST = "127.0.0.1"
PORT = 19997
TIMEOUT = 10.0


def roundtrip(cmd: dict, timeout: float = TIMEOUT) -> tuple[dict | None, float, int, str | None]:
    start = time.monotonic()
    received = bytearray()
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            while b"\n" not in received:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
    except Exception as exc:
        return None, time.monotonic() - start, len(received), repr(exc)

    elapsed = time.monotonic() - start
    if not received:
        return None, elapsed, 0, "empty response"

    line = bytes(received).split(b"\n", 1)[0]
    try:
        return json.loads(line.decode("utf-8")), elapsed, len(received), None
    except Exception as exc:
        return None, elapsed, len(received), f"JSON parse failed: {exc}; prefix={line[:200]!r}"


def main() -> int:
    print(f"Connecting to Webots controller at {HOST}:{PORT}")
    for name, cmd in [
        ("state-no-camera", {"cmd": "get_state", "include_camera": False}),
        ("state-with-camera", {"cmd": "get_state", "include_camera": True}),
    ]:
        response, elapsed, nbytes, error = roundtrip(cmd)
        print(f"\n{name}: {elapsed:.2f}s, {nbytes} bytes")
        if error:
            print(f"  ERROR: {error}")
            continue
        assert response is not None
        camera = response.get("camera")
        print(f"  keys: {sorted(response.keys())}")
        print(f"  position: {response.get('position')}")
        if camera:
            data_len = len(camera.get("data", ""))
            print(f"  camera: {camera.get('encoding')} {camera.get('width')}x{camera.get('height')} data_chars={data_len}")
        else:
            print("  camera: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
