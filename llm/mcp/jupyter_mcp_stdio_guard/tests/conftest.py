import json
import os
import select
import socket
import time
import pytest


@pytest.fixture
def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def send_line_json_fn():
    def _send_line_json(w, obj: dict) -> None:
        w.write((json.dumps(obj) + "\n").encode("utf-8"))
        w.flush()
    return _send_line_json


@pytest.fixture
def read_line_json_fn():
    def _read_line_json(r, timeout: float) -> dict | None:
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
    return _read_line_json


@pytest.fixture
def collect_mcp_logs_fn():
    def _collect() -> tuple[str, str]:
        import glob
        out = err = ""
        try:
            for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stdout.log'))[-3:]:
                try:
                    with open(path, 'rb') as fh:
                        out += f"\n== {path} ==\n" + fh.read().decode('utf-8','ignore')[-4000:]
                except OSError:
                    pass
            for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stderr.log'))[-3:]:
                try:
                    with open(path, 'rb') as fh:
                        err += f"\n== {path} ==\n" + fh.read().decode('utf-8','ignore')[-4000:]
                except OSError:
                    pass
        except OSError:
            pass
        return out, err
    return _collect
