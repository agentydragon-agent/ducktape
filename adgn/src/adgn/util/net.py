from __future__ import annotations

import socket
import time


def wait_for_port(
    host: str, port: int, *, timeout_secs: float = 10.0, interval_secs: float = 0.25
) -> None:
    """Block until host:port accepts TCP connections or timeout.

    Uses monotonic time; raises TimeoutError on expiry.
    """
    deadline = time.monotonic() + float(timeout_secs)
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), 0.5):
                return
        except OSError:
            time.sleep(interval_secs)
    raise TimeoutError(f"port did not become ready: {host}:{port}")
