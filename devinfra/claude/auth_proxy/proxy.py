"""UDS proxy for Bazel remote execution.

UdsRemoteProxy: Unix domain socket proxy for Bazel's --remote_proxy flag. Bazel
sends raw gRPC (HTTP/2) through the UDS; the proxy connects to a fixed remote
endpoint (e.g. remote.buildbuddy.io:443) either directly (no upstream proxy, for
CLI sessions with direct internet access) or via a CONNECT tunnel through an egress
proxy (for web sessions behind Anthropic's TLS-inspecting proxy).
"""

import base64
import contextlib
import logging
import select
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class UpstreamConfig:
    """Upstream proxy configuration."""

    host: str
    port: int
    auth_header: str


def parse_upstream_url(url: str) -> UpstreamConfig:
    """Parse upstream proxy URL into config with auth header."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError(f"Invalid upstream URL: {url}")

    host = parsed.hostname
    port = parsed.port or 80

    auth_header = ""
    if parsed.username:
        password = parsed.password or ""
        auth_str = f"{parsed.username}:{password}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()
        auth_header = f"Proxy-Authorization: Basic {auth_b64}\r\n"

    return UpstreamConfig(host=host, port=port, auth_header=auth_header)


@dataclass
class UpstreamCreds:
    """Thread-safe holder for an upstream proxy URL, shared across proxies in a session.

    All proxy instances in the same session reference the same UpstreamCreds, so a
    single set() call updates every proxy.
    """

    url: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def set(self, new_url: str | None) -> None:
        with self._lock:
            self.url = new_url

    def get_config(self) -> UpstreamConfig | None:
        """Return parsed upstream config, or None if no URL is set (direct mode)."""
        with self._lock:
            url = self.url
        return parse_upstream_url(url) if url is not None else None

    def require_config(self) -> UpstreamConfig:
        """Return parsed upstream config, raising if no URL has been set."""
        config = self.get_config()
        if config is None:
            raise ValueError("Proxy credentials not set")
        return config


def _tunnel_bidirectional(sock_a: socket.socket, sock_b: socket.socket) -> None:
    """Tunnel data bidirectionally between two sockets."""
    sockets = [sock_a, sock_b]

    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 1.0)

            if errored:
                break

            for sock in readable:
                try:
                    data = sock.recv(8192)
                    if not data:
                        return  # Connection closed

                    # Forward to the other socket
                    other = sock_b if sock is sock_a else sock_a
                    other.sendall(data)
                except OSError:
                    return

    except OSError:
        pass


class UdsRemoteProxy:
    """Unix domain socket proxy for Bazel's --remote_proxy flag.

    Bazel sends raw gRPC (HTTP/2) through the UDS. For each connection, this
    proxy connects to remote_target, either directly (no upstream proxy) or
    via a CONNECT tunnel through an egress proxy, then shuttles bytes
    bidirectionally.

    This bypasses gRPC-Java's ProxyDetectorImpl entirely — Bazel's
    --remote_proxy routes gRPC traffic through the UDS natively, so there's
    no Authenticator timing issue.

    When no upstream proxy credentials are set, the
    proxy connects directly to remote_target over TCP. This supports CLI
    sessions that have direct internet access.
    """

    def __init__(self, sock_path: Path, remote_target: str, creds: UpstreamCreds, max_workers: int = 100):
        """
        Args:
            sock_path: Path for the Unix domain socket.
            remote_target: host:port to connect to (e.g. "remote.buildbuddy.io:443").
                Connected to directly when no upstream proxy credentials are set, or via
                CONNECT tunnel when an upstream proxy is configured.
            creds: Shared upstream credentials. Use UpstreamCreds() for a standalone proxy.
        """
        self.sock_path = sock_path
        self.remote_target = remote_target
        self.max_workers = max_workers
        self.creds = creds
        self.server_socket: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._connections: list[socket.socket] = []
        self._conn_counter = 0
        self._conn_lock = threading.Lock()

    def start(self) -> None:
        """Start the UDS proxy server."""
        # Remove stale socket file
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            self.sock_path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(str(self.sock_path))
        self.server_socket.listen(50)
        self.server_socket.settimeout(0.5)

        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="uds-proxy")
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

        logger.info("UDS remote proxy started on %s → %s", self.sock_path, self.remote_target)

    def stop(self) -> None:
        """Stop the UDS proxy server."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        for conn in self._connections:
            with contextlib.suppress(OSError):
                conn.close()
        if self.server_socket:
            self.server_socket.close()
        with contextlib.suppress(FileNotFoundError):
            self.sock_path.unlink()
        logger.info("UDS remote proxy stopped")

    def _serve(self) -> None:
        """Main server loop."""
        while self._running:
            try:
                client_sock, _ = self.server_socket.accept()  # type: ignore[union-attr]
                self._connections.append(client_sock)
                self._executor.submit(self._handle_client, client_sock)  # type: ignore[union-attr]
            except TimeoutError:
                continue
            except OSError:
                break

    def _handle_client(self, client_sock: socket.socket) -> None:
        """Handle a single UDS connection: connect to remote_target, then shuttle bytes.

        With upstream proxy: establishes a CONNECT tunnel through the egress proxy.
        Without upstream proxy: connects directly to remote_target via TCP.
        """
        with self._conn_lock:
            self._conn_counter += 1
            conn_id = self._conn_counter

        upstream_sock: socket.socket | None = None

        try:
            config = self.creds.get_config()

            if config is not None:
                # Egress proxy mode: CONNECT tunnel through upstream proxy.
                logger.debug("[uds %d] Connecting to egress proxy %s:%d", conn_id, config.host, config.port)
                upstream_sock = socket.create_connection((config.host, config.port), timeout=30)
                upstream_sock.settimeout(None)

                connect_request = f"CONNECT {self.remote_target} HTTP/1.1\r\nHost: {self.remote_target}\r\n"
                connect_request += config.auth_header
                connect_request += "\r\n"
                upstream_sock.sendall(connect_request.encode())

                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = upstream_sock.recv(4096)
                    if not chunk:
                        logger.error("[uds %d] Egress proxy closed before CONNECT response", conn_id)
                        return
                    response += chunk

                status_line = response.decode("utf-8", errors="replace").split("\r\n")[0]
                if not status_line.startswith("HTTP/1.1 200"):
                    logger.error("[uds %d] CONNECT to %s rejected: %s", conn_id, self.remote_target, status_line)
                    return

                logger.debug("[uds %d] Tunnel established to %s via egress proxy", conn_id, self.remote_target)
            else:
                # Direct mode: connect straight to remote_target.
                host, _, port_str = self.remote_target.rpartition(":")
                port = int(port_str)
                logger.debug("[uds %d] Direct connect to %s:%d", conn_id, host, port)
                upstream_sock = socket.create_connection((host, port), timeout=30)
                upstream_sock.settimeout(None)
                logger.debug("[uds %d] Direct connection established to %s", conn_id, self.remote_target)

            # Tunnel: raw gRPC from Bazel ↔ remote endpoint
            client_sock.settimeout(None)
            _tunnel_bidirectional(client_sock, upstream_sock)
            logger.debug("[uds %d] Tunnel completed", conn_id)

        except (OSError, ValueError):
            logger.exception("[uds %d] Error", conn_id)
        finally:
            for sock in [client_sock, upstream_sock]:
                if sock:
                    with contextlib.suppress(OSError):
                        sock.close()
            with contextlib.suppress(ValueError):
                self._connections.remove(client_sock)
