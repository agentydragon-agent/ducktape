"""Bazel proxy setup for Claude Code web's TLS-inspecting proxy.

Handles:
- Extracting the Anthropic TLS inspection CA certificate from the proxy
- Creating a Java truststore with the CA for Bazel
- Starting the local bazel proxy wrapper
- Writing bazelrc configuration
"""

import logging
import os
import signal
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Bazel proxy configuration - files stored in ~/.cache/bazel-proxy/
BAZEL_PROXY_PORT = 18081
BAZEL_PROXY_DIR = Path.home() / ".cache" / "bazel-proxy"
BAZEL_PROXY_LOG = BAZEL_PROXY_DIR / "proxy.log"
BAZEL_PROXY_PID = BAZEL_PROXY_DIR / "proxy.pid"
BAZEL_CA_FILE = BAZEL_PROXY_DIR / "anthropic_ca.pem"
BAZEL_TRUSTSTORE = BAZEL_PROXY_DIR / "cacerts.jks"
BAZEL_PROXY_RC = BAZEL_PROXY_DIR / "bazelrc"
BAZEL_USER_BAZELRC = Path.home() / ".bazelrc"


def _parse_proxy_url(proxy_url: str) -> tuple[str, int, str | None, str | None]:
    """Parse proxy URL into (host, port, user, password)."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = parsed.port or 80
    user = parsed.username
    password = parsed.password
    return host, port, user, password


def _extract_proxy_ca() -> bool:
    """Extract the TLS inspection CA certificate from the proxy.

    Returns True if CA was extracted successfully.
    """
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, skipping CA extraction")
        return False

    host, port, _, _ = _parse_proxy_url(https_proxy)
    if not host:
        log.warning("Could not parse proxy URL: %s", https_proxy)
        return False

    log.info("Extracting TLS inspection CA from proxy %s:%d", host, port)

    result = subprocess.run(
        ["openssl", "s_client", "-proxy", f"{host}:{port}", "-connect", "bcr.bazel.build:443", "-showcerts"],
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )

    certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", result.stdout, re.DOTALL)
    if len(certs) < 2:
        log.warning("Expected at least 2 certs in chain, got %d", len(certs))
        return False

    # Find the Anthropic TLS inspection CA in the chain
    for i, cert in enumerate(certs):
        verify_result = subprocess.run(
            ["openssl", "x509", "-noout", "-subject"],
            input=cert,
            capture_output=True,
            text=True,
        )
        if "Anthropic" in verify_result.stdout or "TLS Inspection" in verify_result.stdout:
            log.info("Found Anthropic TLS inspection CA at position %d", i)
            BAZEL_CA_FILE.write_text(cert)
            return True

    log.warning("Could not find Anthropic TLS inspection CA in chain")
    return False


def _create_java_truststore() -> bool:
    """Create a Java truststore with the system CAs plus the proxy CA.

    Returns True if truststore was created successfully.
    """
    if not BAZEL_CA_FILE.exists():
        log.warning("No CA file to add to truststore")
        return False

    # Find system cacerts
    system_cacerts = Path("/etc/ssl/certs/java/cacerts")
    if not system_cacerts.exists():
        # Try alternative locations
        for alt in [
            Path("/etc/pki/java/cacerts"),
            Path("/usr/lib/jvm/default-java/lib/security/cacerts"),
        ]:
            if alt.exists():
                system_cacerts = alt
                break
        else:
            log.warning("Could not find system Java cacerts")
            return False

    log.info("Creating custom Java truststore from %s", system_cacerts)

    # Copy system cacerts
    shutil.copy(system_cacerts, BAZEL_TRUSTSTORE)

    # Import the proxy CA
    result = subprocess.run(
        [
            "keytool", "-importcert", "-trustcacerts",
            "-alias", "anthropic-tls-inspection",
            "-file", str(BAZEL_CA_FILE),
            "-keystore", str(BAZEL_TRUSTSTORE),
            "-storepass", "changeit",
            "-noprompt",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.warning("Failed to import CA into truststore: %s", result.stderr)
        return False

    log.info("Created custom Java truststore at %s", BAZEL_TRUSTSTORE)
    return True


def _get_proxy_script_path() -> Path:
    """Get the path to the bazel proxy script (bundled with the hook)."""
    return Path(__file__).parent / "bazel_proxy.py"


def _kill_existing_proxy() -> None:
    """Kill existing proxy using pidfile."""
    if not BAZEL_PROXY_PID.exists():
        return

    try:
        pid = int(BAZEL_PROXY_PID.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        # Kill it
        log.info("Killing existing proxy (pid %d)", pid)
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)  # Allow port to be released
    except (ValueError, ProcessLookupError, PermissionError):
        # Pid invalid, process doesn't exist, or can't kill - that's fine
        pass
    finally:
        # Clean up stale pidfile
        BAZEL_PROXY_PID.unlink(missing_ok=True)


def _start_proxy_server() -> bool:
    """Start the local Bazel proxy in the background.

    Returns True if proxy was started successfully.

    Always kills and restarts the proxy to ensure fresh credentials are used.
    The proxy captures https_proxy at startup, so if the container was replaced
    (and credentials refreshed), we need to restart to pick up new credentials.
    """
    proxy_script = _get_proxy_script_path()
    if not proxy_script.exists():
        log.warning("Bazel proxy script not found at %s", proxy_script)
        return False

    # Always kill existing proxy to pick up fresh credentials
    _kill_existing_proxy()

    # Start the proxy (reads https_proxy from environment)
    log.info("Starting Bazel proxy on port %d", BAZEL_PROXY_PORT)
    proc = subprocess.Popen(
        ["python3", str(proxy_script), "--listen-port", str(BAZEL_PROXY_PORT)],
        stdout=open(BAZEL_PROXY_LOG, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Write pidfile
    BAZEL_PROXY_PID.write_text(str(proc.pid))

    # Wait for it to start
    for _ in range(10):
        time.sleep(0.5)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
            sock.close()
            if result == 0:
                log.info("Bazel proxy started successfully (pid %d)", proc.pid)
                return True
        except Exception:
            pass

    log.warning("Failed to start Bazel proxy")
    return False


def _write_bazel_config() -> None:
    """Write Bazel proxy config to separate file and add try-import to ~/.bazelrc."""
    if not BAZEL_TRUSTSTORE.exists():
        log.warning("No truststore, skipping bazelrc")
        return

    # Write proxy config to dedicated file
    proxy_rc = f"""\
# Bazel proxy configuration for Claude Code web (auto-generated)
startup --host_jvm_args=-Dhttps.proxyHost=127.0.0.1
startup --host_jvm_args=-Dhttps.proxyPort={BAZEL_PROXY_PORT}
startup --host_jvm_args=-Djavax.net.ssl.trustStore={BAZEL_TRUSTSTORE}
startup --host_jvm_args=-Djavax.net.ssl.trustStorePassword=changeit
"""
    BAZEL_PROXY_RC.write_text(proxy_rc)
    log.info("Wrote proxy config to %s", BAZEL_PROXY_RC)

    # Add try-import to user bazelrc (idempotent)
    import_line = f"try-import {BAZEL_PROXY_RC}\n"
    if BAZEL_USER_BAZELRC.exists():
        existing = BAZEL_USER_BAZELRC.read_text()
        if str(BAZEL_PROXY_RC) in existing:
            return
        BAZEL_USER_BAZELRC.write_text(existing.rstrip() + "\n" + import_line)
    else:
        BAZEL_USER_BAZELRC.write_text(import_line)
    log.info("Added try-import to %s", BAZEL_USER_BAZELRC)


def setup_bazel_proxy() -> None:
    """Set up the complete Bazel proxy environment for TLS-inspecting proxies.

    This is needed when running behind Anthropic's TLS-inspecting proxy
    (Claude Code web). Steps:
    1. Extract the TLS inspection CA certificate
    2. Create Java truststore with the CA
    3. Start local proxy wrapper that adds auth headers
    4. Write bazelrc configuration to use the proxy
    """
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, Bazel proxy setup not needed")
        return

    log.info("Setting up Bazel proxy for TLS-inspecting proxy...")
    BAZEL_PROXY_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract the TLS inspection CA
    if not _extract_proxy_ca():
        log.warning("Could not extract proxy CA, Bazel BCR access may fail")
        return

    # Step 2: Create Java truststore with the CA
    if not _create_java_truststore():
        log.warning("Could not create Java truststore")
        return

    # Step 3: Start the local proxy wrapper
    if not _start_proxy_server():
        log.warning("Could not start Bazel proxy")
        return

    # Step 4: Write bazelrc configuration
    _write_bazel_config()

    log.info("Bazel proxy setup complete")


def is_configured() -> bool:
    """Check if Bazel proxy is configured."""
    return BAZEL_TRUSTSTORE.exists()


def get_status() -> str:
    """Get human-readable proxy status."""
    if BAZEL_TRUSTSTORE.exists():
        return f"configured (port {BAZEL_PROXY_PORT})"
    return "not configured"
