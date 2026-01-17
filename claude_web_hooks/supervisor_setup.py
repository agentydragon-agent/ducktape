"""Supervisor setup for managing long-running processes in Claude Code web.

Provides a centralized process manager for:
- Bazel proxy (handles TLS-inspecting proxy authentication)
- Future: other background services as needed
"""

import configparser
import http.client
import logging
import shlex
import socket
import subprocess
import time
import xmlrpc.client
from pathlib import Path

log = logging.getLogger(__name__)

SUPERVISOR_DIR = Path.home() / ".config" / "supervisor"
SUPERVISOR_CONF = SUPERVISOR_DIR / "supervisord.conf"
SUPERVISOR_SOCK = SUPERVISOR_DIR / "supervisor.sock"
SUPERVISOR_LOG = SUPERVISOR_DIR / "supervisord.log"
SUPERVISOR_PIDFILE = SUPERVISOR_DIR / "supervisord.pid"


class _UnixStreamHTTPConnection(http.client.HTTPConnection):
    """HTTP connection over Unix domain socket."""

    def connect(self) -> None:
        """Connect to Unix socket instead of TCP."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.host)


class _UnixStreamTransport(xmlrpc.client.Transport):
    """XML-RPC transport over Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self._socket_path = socket_path

    def make_connection(self, host: object) -> _UnixStreamHTTPConnection:
        """Create Unix socket connection."""
        return _UnixStreamHTTPConnection(self._socket_path)


def _get_supervisor_client() -> xmlrpc.client.ServerProxy:
    """Get XML-RPC client for supervisor.

    Returns client connected to supervisor's Unix socket.
    Raises ConnectionError if socket doesn't exist.
    """
    if not SUPERVISOR_SOCK.exists():
        raise ConnectionError(f"Supervisor socket not found: {SUPERVISOR_SOCK}")

    transport = _UnixStreamTransport(str(SUPERVISOR_SOCK))
    return xmlrpc.client.ServerProxy("http://localhost", transport=transport)


def _write_supervisor_config() -> None:
    """Write supervisor configuration file."""
    SUPERVISOR_DIR.mkdir(parents=True, exist_ok=True)

    config = configparser.ConfigParser()
    config["unix_http_server"] = {"file": str(SUPERVISOR_SOCK)}
    config["supervisord"] = {
        "logfile": str(SUPERVISOR_LOG),
        "pidfile": str(SUPERVISOR_PIDFILE),
        "childlogdir": str(SUPERVISOR_DIR),
        "nodaemon": "false",
        "silent": "false",
    }
    config["rpcinterface:supervisor"] = {
        "supervisor.rpcinterface_factory": "supervisor.rpcinterface:make_main_rpcinterface"
    }
    config["supervisorctl"] = {"serverurl": f"unix://{SUPERVISOR_SOCK}"}
    config["include"] = {"files": f"{SUPERVISOR_DIR}/conf.d/*.conf"}

    with SUPERVISOR_CONF.open("w") as f:
        config.write(f)
    log.info("Wrote supervisor config to %s", SUPERVISOR_CONF)

    # Create conf.d directory for service configs
    (SUPERVISOR_DIR / "conf.d").mkdir(parents=True, exist_ok=True)


def is_running() -> bool:
    """Check if supervisord is running."""
    if not SUPERVISOR_SOCK.exists():
        return False

    try:
        client = _get_supervisor_client()
        # Simple API call to check if supervisor is responsive
        client.supervisor.getState()
        return True
    except (ConnectionError, OSError, xmlrpc.client.Fault):
        return False


def _ensure_supervisor_installed() -> bool:
    """Ensure supervisor is installed via apt.

    Returns True if supervisor is available.
    """
    try:
        subprocess.run(["supervisord", "--version"], capture_output=True, timeout=5, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.info("Installing supervisor...")
        try:
            result = subprocess.run(
                ["apt-get", "install", "-y", "supervisor"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                log.warning("Failed to install supervisor: %s", result.stderr)
                return False
            log.info("supervisor installed successfully")
            return True
        except subprocess.TimeoutExpired:
            log.warning("supervisor installation timed out")
            return False


def start() -> bool:
    """Start supervisord if not already running.

    Returns True if supervisord is running (either already or newly started).
    """
    if is_running():
        log.info("supervisord already running")
        return True

    # Ensure supervisor is installed
    if not _ensure_supervisor_installed():
        log.warning("Could not install supervisor")
        return False

    log.info("Starting supervisord...")

    # Ensure config exists
    if not SUPERVISOR_CONF.exists():
        _write_supervisor_config()

    # Start supervisord
    try:
        result = subprocess.run(
            ["supervisord", "-c", str(SUPERVISOR_CONF)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            log.warning("Failed to start supervisord: %s", result.stderr)
            return False
    except subprocess.TimeoutExpired:
        log.warning("supervisord startup timed out")
        return False

    # Wait for supervisor to be ready
    for _ in range(10):
        time.sleep(0.3)
        if is_running():
            log.info("supervisord started successfully")
            return True

    log.warning("supervisord did not start in time")
    return False


def add_service(name: str, command: str, directory: str | None = None, environment: dict[str, str] | None = None) -> bool:
    """Add a service to supervisor.

    Args:
        name: Service name (used in supervisorctl commands)
        command: Command to run
        directory: Working directory (optional)
        environment: Environment variables (optional)

    Returns:
        True if service was added successfully.
    """
    if not is_running():
        log.warning("supervisord not running, cannot add service %s", name)
        return False

    service_conf = SUPERVISOR_DIR / "conf.d" / f"{name}.conf"

    config = configparser.ConfigParser()
    section = f"program:{name}"
    config[section] = {
        "command": command,
        "autostart": "true",
        "autorestart": "true",
        "startsecs": "1",
        "startretries": "3",
        "stdout_logfile": f"{SUPERVISOR_DIR}/{name}.log",
        "stdout_logfile_maxbytes": "10MB",
        "stdout_logfile_backups": "2",
        "stderr_logfile": f"{SUPERVISOR_DIR}/{name}.err.log",
        "stderr_logfile_maxbytes": "10MB",
        "stderr_logfile_backups": "2",
    }

    if directory:
        config[section]["directory"] = directory

    if environment:
        # Supervisor environment format: KEY="value",KEY2="value2"
        # Use shlex.quote for proper shell escaping
        env_parts = [f'{k}={shlex.quote(v)}' for k, v in environment.items()]
        config[section]["environment"] = ",".join(env_parts)

    with service_conf.open("w") as f:
        config.write(f)
    log.info("Wrote service config: %s", service_conf)

    # Reload supervisor config via XML-RPC
    try:
        client = _get_supervisor_client()
        # Reread config files
        result = client.supervisor.reloadConfig()
        # result is ([added], [changed], [removed])
        log.info("Reloaded config: added=%s, changed=%s, removed=%s", *result)

        # Add/update the service
        client.supervisor.addProcessGroup(name)
        log.info("Added and started service: %s", name)
        return True
    except xmlrpc.client.Fault as e:
        # addProcessGroup raises fault if already exists, which is fine
        if "ALREADY_ADDED" in str(e):
            log.info("Service %s already running", name)
            return True
        log.warning("Failed to add service %s: %s", name, e)
        return False
    except (ConnectionError, OSError) as e:
        log.warning("Failed to communicate with supervisor: %s", e)
        return False


def is_service_running(service_name: str) -> bool:
    """Check if a specific service is running under supervisor.

    Args:
        service_name: Name of the service to check

    Returns:
        True if service is running, False otherwise
    """
    if not is_running():
        return False

    try:
        client = _get_supervisor_client()
        info = client.supervisor.getProcessInfo(service_name)
        return info["statename"] == "RUNNING"
    except (ConnectionError, OSError, xmlrpc.client.Fault):
        return False


def get_status() -> str:
    """Get human-readable supervisor status."""
    if not is_running():
        return "not running"

    try:
        client = _get_supervisor_client()
        # Get all process info
        all_info = client.supervisor.getAllProcessInfo()
        # Count running services
        running = sum(1 for info in all_info if info["statename"] == "RUNNING")
        return f"running ({running} services)"
    except (ConnectionError, OSError, xmlrpc.client.Fault):
        return "error"


def emit_usage_guidance() -> None:
    """Emit supervisor usage guidance (visible to agent)."""
    guidance = f"""
Supervisor Process Management
==============================

Supervisor manages background processes (bazel proxy, etc.).

Common Commands:
----------------
# View all service status
supervisorctl -c {SUPERVISOR_CONF} status

# View service logs
tail -f {SUPERVISOR_DIR}/bazel-proxy.log
tail -f {SUPERVISOR_DIR}/bazel-proxy.err.log

# Restart a service
supervisorctl -c {SUPERVISOR_CONF} restart bazel-proxy

# Stop/start a service
supervisorctl -c {SUPERVISOR_CONF} stop bazel-proxy
supervisorctl -c {SUPERVISOR_CONF} start bazel-proxy

# View all logs
ls -lh {SUPERVISOR_DIR}/*.log

Configuration:
--------------
Main config: {SUPERVISOR_CONF}
Service configs: {SUPERVISOR_DIR}/conf.d/
Logs: {SUPERVISOR_DIR}/

"""
    print(guidance)
