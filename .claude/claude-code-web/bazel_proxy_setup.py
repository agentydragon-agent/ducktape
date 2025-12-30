"""Bazel proxy setup for Claude Code web's TLS-inspecting proxy.

Handles:
- Extracting the Anthropic TLS inspection CA certificate from the proxy
- Creating a Java truststore with the CA for Bazel
- Starting the local bazel proxy wrapper
- Writing bazelrc configuration
"""

import logging
import os
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
    """Get the path to the bazel proxy script.

    The proxy lives in the bazel_proxy package at the repo root.
    """
    # Navigate from .claude/claude-code-web/ to bazel_proxy/
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / "bazel_proxy" / "src" / "bazel_proxy" / "proxy.py"


def _update_proxy_credentials() -> None:
    """Write fresh proxy credentials from environment to the credentials file.

    This allows the running proxy to pick up new credentials without restart.
    The proxy checks file mtime and reloads when the file changes.
    """
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        return

    creds_file = BAZEL_PROXY_DIR / "upstream_proxy"
    BAZEL_PROXY_DIR.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(https_proxy)
    log.info("Updated proxy credentials in %s", creds_file)


def _start_proxy_server() -> bool:
    """Start the local Bazel proxy in the background.

    Returns True if proxy was started successfully.

    The proxy handles killing any existing instance and daemonizing itself.
    This ensures fresh credentials are used (proxy captures https_proxy at startup).
    """
    proxy_script = _get_proxy_script_path()
    if not proxy_script.exists():
        log.warning("Bazel proxy script not found at %s", proxy_script)
        return False

    log.info("Starting Bazel proxy on port %d", BAZEL_PROXY_PORT)

    # The proxy handles: killing existing, daemonizing, logging, pidfile
    result = subprocess.run(
        ["python3", str(proxy_script), "-d", "--listen-port", str(BAZEL_PROXY_PORT)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("Failed to start proxy: %s", result.stderr)
        return False

    # Wait for it to start listening
    for _ in range(10):
        time.sleep(0.5)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn_result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
            sock.close()
            if conn_result == 0:
                log.info("Bazel proxy started successfully")
                return True
        except Exception:
            pass

    log.warning("Bazel proxy did not start listening in time")
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

    # Step 4: Update credentials file (allows refresh without proxy restart)
    _update_proxy_credentials()

    # Step 5: Write bazelrc configuration
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
