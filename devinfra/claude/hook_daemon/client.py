"""Thin UDS client for the hook daemon with self-healing.

Sends hook RPCs to the daemon over a Unix domain socket. If the daemon is
unreachable, forks a new one and retries. Uses only stdlib (urllib) on the
hot path to avoid importing httpx.
"""

import contextlib
import http.client
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.hook_daemon.models import HookRequest, HookResponse
from devinfra.claude.settings import HookSettings
from util.bazel.subprocess import python_env

logger = logging.getLogger(__name__)


class _UDSConnection(http.client.HTTPConnection):
    """HTTPConnection subclass that connects to a Unix domain socket."""

    def __init__(self, sock_path: Path) -> None:
        # host is unused but required by HTTPConnection
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self._sock_path))


def call_daemon(hook_input: AnyHookInput, env: dict[str, str], settings: HookSettings) -> HookResponse | None:
    """POST to daemon over UDS. If unreachable, start daemon and retry."""
    sock_path = settings.get_hook_daemon_sock()
    request = HookRequest(hook=hook_input, env=env)

    if sock_path.exists():
        result = _post_to_daemon(request, sock_path)
        if result is not None:
            return result

    # Daemon unreachable or socket missing — start it
    if _start_daemon(settings):
        _wait_for_sock(sock_path, timeout_secs=5)
        return _post_to_daemon(request, sock_path)

    return None


def _post_to_daemon(request: HookRequest, sock_path: Path) -> HookResponse | None:
    """Send a hook request to the daemon. Returns None if connection fails."""
    try:
        conn = _UDSConnection(sock_path)
        payload = request.model_dump_json().encode()
        conn.request("POST", "/hook", body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            logger.warning("Daemon returned HTTP %d", response.status)
            return None
        body = response.read()
        conn.close()
        return HookResponse.model_validate_json(body)
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        logger.debug("Daemon unreachable: %s", e)
        return None


def _start_daemon(settings: HookSettings) -> bool:
    """Fork daemon as a detached background process. Returns True if started."""
    daemon_dir = settings.get_hook_daemon_dir()
    sock_path = settings.get_hook_daemon_sock()
    pidfile = settings.get_hook_daemon_pidfile()

    # Check if daemon is already running (pidfile with live process)
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)  # Check if process is alive
            # PID is alive but socket is gone — stale state, kill it
            if not sock_path.exists():
                logger.info("Stale daemon (pid=%d, no socket), killing", pid)
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
            else:
                # Daemon is running with socket — nothing to do
                return True
        except (ProcessLookupError, ValueError, OSError):
            pass  # PID is dead, clean up below

    # Create daemon dir
    daemon_dir.mkdir(parents=True, exist_ok=True)

    # Clean stale socket
    if sock_path.exists():
        sock_path.unlink()

    # Find the daemon entry point
    daemon_module = "devinfra.claude.hook_daemon.main"

    # Fork daemon as detached subprocess
    log_out = daemon_dir / "daemon.log"
    log_err = daemon_dir / "daemon.err.log"

    with log_out.open("a") as stdout_f, log_err.open("a") as stderr_f:
        proc = subprocess.Popen(
            [sys.executable, "-m", daemon_module, "--sock", str(sock_path), "--daemon-dir", str(daemon_dir)],
            stdout=stdout_f,
            stderr=stderr_f,
            env=python_env(),
            start_new_session=True,  # Detach from parent
        )

    # Write pidfile
    pidfile.write_text(str(proc.pid))
    logger.info("Started daemon (pid=%d, sock=%s)", proc.pid, sock_path)
    return True


def _wait_for_sock(sock_path: Path, *, timeout_secs: float = 5) -> bool:
    """Poll until socket file exists and accepts connections."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        if sock_path.exists():
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(str(sock_path))
                s.close()
                return True
            except (ConnectionRefusedError, OSError):
                pass
        time.sleep(0.1)
    logger.warning("Daemon socket did not appear within %.1fs", timeout_secs)
    return False
