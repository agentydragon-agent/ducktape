import json
import os
import select
import socket
import time


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def send_line_json(w, obj: dict) -> None:
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def read_line_json(r, timeout: float) -> dict | None:
    fd = r.fileno()
    os.set_blocking(fd, False)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            b = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not b:
            time.sleep(0.01)
            continue
        if b == b"\n":
            break
        buf.extend(b)
    if not buf:
        return None
    try:
        return json.loads(bytes(buf).decode("utf-8", errors="ignore").rstrip("\r"))
    except Exception:
        return None
