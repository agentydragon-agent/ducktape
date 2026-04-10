"""Thin UDS client for the hook daemon with self-healing.

Sends hook RPCs to the daemon over a Unix domain socket. If the daemon is
unreachable, forks a new one and retries. Uses only stdlib (urllib) on the
hot path to avoid importing httpx.
"""

import fcntl
import http.client
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

from filelock import FileLock

from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.hook_daemon.models import HookRequest, HookResponse
from devinfra.claude.session_paths import SessionPaths
from util.bazel.subprocess import python_env

logger = logging.getLogger(__name__)

# How long to wait for the daemon socket to appear after starting the daemon.
_DAEMON_STARTUP_TIMEOUT_SECS = 5


class _UDSConnection(http.client.HTTPConnection):
    """HTTPConnection subclass that connects to a Unix domain socket."""

    def __init__(self, sock_path: Path) -> None:
        # host is unused but required by HTTPConnection
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self._sock_path))


class DaemonStartError(RuntimeError):
    """Raised when the hook daemon fails to start or crashes during startup."""


class DaemonHttpError(RuntimeError):
    """Raised when the hook daemon returns a non-200 HTTP response."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Daemon returned HTTP {status}: {body}")
        self.status = status
        self.body = body


def update_proxy_creds(https_proxy: str, paths: SessionPaths) -> None:
    """Send fresh proxy credentials to the daemon.

    Raises OSError if the daemon is unreachable.
    """
    sock_path = paths.hook_daemon_sock
    payload = json.dumps({"https_proxy": https_proxy}).encode()
    conn = _UDSConnection(sock_path)
    conn.timeout = 5.0
    conn.request("POST", "/update-proxy-creds", body=payload, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    if response.status != 200:
        raise OSError(f"Daemon returned HTTP {response.status} for update-proxy-creds: {body.decode()}")


def check_health(sock_path: Path, timeout: float = 0.5) -> _UDSConnection | None:
    """Check if the daemon is healthy by hitting GET /health. Returns a connection on success."""
    try:
        conn = _UDSConnection(sock_path)
        conn.timeout = timeout
        conn.request("GET", "/health")
        response = conn.getresponse()
        response.read()
        if response.status == 200:
            return conn
        conn.close()
        return None
    except (ConnectionRefusedError, FileNotFoundError, OSError, http.client.HTTPException):
        return None


def call_daemon(hook_input: AnyHookInput, env: dict[str, str], paths: SessionPaths) -> HookResponse | None:
    """POST to daemon over UDS. If unreachable, start daemon and retry.

    Raises DaemonStartError if the daemon process dies during startup.
    """
    sock_path = paths.hook_daemon_sock
    request = HookRequest(hook=hook_input, env=env)

    # Fast path: talk to an existing healthy daemon without any locking.
    if sock_path.exists():
        conn = _UDSConnection(sock_path)
        result = _post_to_daemon(request, conn)
        if result is not None:
            return result
        logger.info("Daemon unreachable on existing socket %s, will restart", sock_path)

    # Slow path: ensure a healthy daemon exists (may kill a stale/hung one
    # and start a fresh one), then retry.
    conn = _ensure_daemon(paths)
    return _post_to_daemon(request, conn)


def _post_to_daemon(request: HookRequest, conn: _UDSConnection) -> HookResponse | None:
    """Send a hook request to the daemon. Returns None if connection fails."""
    try:
        payload = request.model_dump_json().encode()
        conn.request("POST", "/hook", body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            body = response.read().decode("utf-8", errors="replace")
            conn.close()
            raise DaemonHttpError(response.status, body)
        raw = response.read()
        conn.close()
        return HookResponse.model_validate_json(raw)
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        logger.debug("Daemon unreachable: %s", e)
        return None


def read_pidfile(pidfile: Path) -> int:
    """Read PID from a pidfile. Raises ValueError/OSError if unreadable."""
    return int(pidfile.read_text().strip())


def _is_pidfile_locked(pidfile: Path) -> bool:
    """Non-blocking flock probe on the pidfile. Returns True if a daemon holds the lock.

    Uses raw fcntl.flock — filelock.FileLock.release() unlinks the file, which
    would destroy the daemon's PID data.
    """
    try:
        fd = os.open(str(pidfile), os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _kill_daemon_by_pidfile(pidfile: Path) -> None:
    """Kill the daemon identified by pidfile: SIGTERM, short grace, then SIGKILL.

    The flock on the pidfile is authoritative for liveness — no PID-reuse ambiguity.
    With double-fork daemonization the daemon is reparented to init, so no zombies.
    """
    try:
        pid = read_pidfile(pidfile)
    except (ValueError, OSError) as e:
        logger.warning("Cannot read PID from %s: %s", pidfile, e)
        return

    logger.info("Killing daemon (pid=%d): sending SIGTERM", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    # Short grace period for graceful shutdown, then force-kill.
    time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return  # Already dead from SIGTERM.
    except OSError as e:
        logger.warning("Failed to SIGKILL pid=%d: %s", pid, e)

    # Wait for process to fully exit.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    logger.warning("Daemon pid=%d still alive after SIGTERM+SIGKILL", pid)


def _ensure_daemon(paths: SessionPaths) -> _UDSConnection:
    """Ensure a healthy daemon is running, returning a connection to it.

    Holds daemon.lock for the entire duration — from checking liveness through
    forking and waiting for the new daemon's socket to accept connections. This
    prevents concurrent clients from racing to start multiple daemons (Bazel
    server pattern).

    Daemon liveness is determined by an exclusive flock on daemon.pid, held by
    the daemon for its entire lifetime. The kernel releases it on process death,
    so the probe is authoritative regardless of PID reuse.
    """
    daemon_dir = paths.hook_daemon_dir
    sock_path = paths.hook_daemon_sock
    pidfile = paths.hook_daemon_pidfile

    # Create daemon dir before acquiring the lock (FileLock needs the parent to exist).
    daemon_dir.mkdir(parents=True, exist_ok=True)

    with FileLock(str(daemon_dir / "daemon.lock")):
        # Re-check after acquiring: another client may have won the race and
        # already started a healthy daemon while we were waiting.
        if conn := check_health(sock_path):
            logger.debug("Daemon already healthy (socket=%s), skipping start", sock_path)
            return conn

        # Probe daemon liveness via flock on pidfile.
        if _is_pidfile_locked(pidfile):
            # Daemon process is alive (holds the flock), but health check
            # failed above — it's hung. Kill it.
            _kill_daemon_by_pidfile(pidfile)
        else:
            logger.debug("Pidfile lock available — no live daemon")

        paths.ensure_dirs()

        # Clean stale state from previous daemon before starting a fresh one.
        if sock_path.exists():
            logger.debug("Removing stale socket %s", sock_path)
            sock_path.unlink()
        if pidfile.exists():
            pidfile.unlink()

        daemon_pid = _fork_daemon(daemon_dir, sock_path)

        # Wait for socket while still holding daemon.lock — prevents other
        # clients from entering and trying to start a second daemon.
        try:
            return _wait_for_sock(sock_path, pidfile=pidfile, daemon_pid=daemon_pid)
        except DaemonStartError as e:
            # Enrich with daemon stderr at the error boundary (once).
            stderr = _read_daemon_stderr(daemon_dir)
            if stderr:
                raise DaemonStartError(f"{e}\n--- daemon stderr ---\n{stderr}") from e
            raise


def _fork_daemon(daemon_dir: Path, sock_path: Path) -> int:
    """Fork the daemon as a double-forked background process. Returns grandchild PID.

    Uses the classic Unix double-fork pattern: parent → child → grandchild.
    The intermediate child exits immediately (reaped synchronously by the parent),
    and the grandchild is reparented to init. This eliminates zombies — unlike
    Popen(start_new_session=True) where the parent must waitpid to reap.

    The grandchild PID is piped back from the intermediate child so the caller
    can detect pre-pidfile crashes via os.kill(pid, 0).
    """
    daemon_module = "devinfra.claude.hook_daemon.main"
    log_out = daemon_dir / "daemon.log"
    log_err = daemon_dir / "daemon.err.log"

    logger.info("Starting daemon: module=%s sock=%s daemon_dir=%s", daemon_module, sock_path, daemon_dir)

    read_fd, write_fd = os.pipe()

    pid = os.fork()
    if pid > 0:
        # Parent: close write end, reap intermediate child, read grandchild PID.
        os.close(write_fd)
        os.waitpid(pid, 0)
        data = os.read(read_fd, 32)
        os.close(read_fd)
        return int(data)

    # Intermediate child: close read end, new session, then fork again.
    os.close(read_fd)
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        # Write grandchild PID to pipe before exiting.
        os.write(write_fd, str(pid2).encode())
        os.close(write_fd)
        os._exit(0)

    # Grandchild: this becomes the daemon process.
    os.close(write_fd)
    # Redirect stdout/stderr to log files.
    fd_out = os.open(str(log_out), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    fd_err = os.open(str(log_err), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd_out, 1)
    os.dup2(fd_err, 2)
    os.close(fd_out)
    os.close(fd_err)

    env = python_env()
    os.execve(
        sys.executable,
        [sys.executable, "-m", daemon_module, "--sock", str(sock_path), "--daemon-dir", str(daemon_dir)],
        env,
    )


def _read_daemon_stderr(daemon_dir: Path, max_bytes: int = 4096) -> str:
    """Read the tail of daemon.err.log for inclusion in crash error messages."""
    err_log = daemon_dir / "daemon.err.log"
    try:
        content = err_log.read_text(errors="replace")
        if len(content) > max_bytes:
            content = "..." + content[-max_bytes:]
        return content.strip()
    except OSError:
        return ""


def _wait_for_sock(
    sock_path: Path, *, pidfile: Path, daemon_pid: int, timeout_secs: float = _DAEMON_STARTUP_TIMEOUT_SECS
) -> _UDSConnection:
    """Poll until socket file exists and accepts connections, returning a connection.

    Detects daemon crashes two ways:
    1. Post-pidfile: flock probe on the pidfile (authoritative, PID-reuse safe).
    2. Pre-pidfile: os.kill(daemon_pid, 0) — covers the gap before the daemon
       acquires the flock. PID reuse in the <5s startup window is negligible.
    """
    logger.debug("Waiting for daemon socket %s (pid=%d, timeout=%.1fs)", sock_path, daemon_pid, timeout_secs)
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        if sock_path.exists():
            try:
                conn = _UDSConnection(sock_path)
                conn.connect()
                logger.debug("Daemon socket ready at %s", sock_path)
                return conn
            except (ConnectionRefusedError, OSError):
                pass

        # Post-pidfile crash detection: if the daemon died, its flock on the
        # pidfile is released by the kernel.  The stale pidfile is deleted
        # before forking, so if it exists, the new daemon created it.  An
        # unlocked pidfile means the daemon died after creating the file but
        # before (or after) binding.
        if pidfile.exists() and not _is_pidfile_locked(pidfile):
            raise DaemonStartError("Daemon died during startup")

        # Pre-pidfile crash detection: if the daemon process exited before it
        # even wrote the pidfile (import error, execve failure, early crash),
        # os.kill(pid, 0) catches it immediately instead of waiting for timeout.
        try:
            os.kill(daemon_pid, 0)
        except ProcessLookupError:
            raise DaemonStartError("Daemon process died during startup (pre-pidfile)")

        time.sleep(0.1)
    logger.warning("Daemon socket did not appear within %.1fs at %s", timeout_secs, sock_path)
    raise DaemonStartError(f"Daemon socket did not appear within {timeout_secs}s")
