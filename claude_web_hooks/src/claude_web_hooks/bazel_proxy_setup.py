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
BAZEL_COMBINED_CA = BAZEL_PROXY_DIR / "combined_ca.pem"
BAZEL_TRUSTSTORE = BAZEL_PROXY_DIR / "cacerts.jks"
BAZEL_PROXY_RC = BAZEL_PROXY_DIR / "bazelrc"
BAZEL_USER_BAZELRC = Path.home() / ".bazelrc"

# Pre-installed Anthropic CA on Claude Code web containers
ANTHROPIC_CA_PREINSTALLED = Path("/usr/local/share/ca-certificates/swp-ca-production.crt")


def _get_repo_root() -> Path:
    """Get the repo root (parent of claude_web_hooks/src/claude_web_hooks/)."""
    return Path(__file__).parent.parent.parent.parent


# Proxy env .bzl file - in repo, gitignored
BAZEL_PROXY_ENV_BZL = _get_repo_root() / ".claude" / "proxy_env.bzl"


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

    Uses our local proxy (localhost:18081) which handles auth to upstream.
    Returns True if CA was extracted successfully.
    """
    log.info("Extracting TLS inspection CA via local proxy localhost:%d", BAZEL_PROXY_PORT)

    result = subprocess.run(
        [
            "openssl",
            "s_client",
            "-proxy",
            f"localhost:{BAZEL_PROXY_PORT}",
            "-connect",
            "bcr.bazel.build:443",
            "-showcerts",
        ],
        check=False,
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
            ["openssl", "x509", "-noout", "-subject"], check=False, input=cert, capture_output=True, text=True
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
        for alt in [Path("/etc/pki/java/cacerts"), Path("/usr/lib/jvm/default-java/lib/security/cacerts")]:
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
            "keytool",
            "-importcert",
            "-trustcacerts",
            "-alias",
            "anthropic-tls-inspection",
            "-file",
            str(BAZEL_CA_FILE),
            "-keystore",
            str(BAZEL_TRUSTSTORE),
            "-storepass",
            "changeit",
            "-noprompt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.warning("Failed to import CA into truststore: %s", result.stderr)
        return False

    log.info("Created custom Java truststore at %s", BAZEL_TRUSTSTORE)
    return True


def _get_proxy_script_path() -> Path:
    """Get the path to the bazel proxy script (colocated in this package)."""
    return Path(__file__).parent / "proxy.py"


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

    Uses -r to replace any existing instance with fresh credentials.
    """
    proxy_script = _get_proxy_script_path()
    if not proxy_script.exists():
        log.warning("Bazel proxy script not found at %s", proxy_script)
        return False

    log.info("Starting Bazel proxy on port %d", BAZEL_PROXY_PORT)

    # -d: daemonize, -r: replace any existing instance
    result = subprocess.run(
        ["python3", str(proxy_script), "-d", "-r", "--listen-port", str(BAZEL_PROXY_PORT)],
        check=False,
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

    local_proxy = f"http://localhost:{BAZEL_PROXY_PORT}"

    # Write proxy config to dedicated file
    proxy_rc = f"""\
# Bazel proxy configuration for Claude Code web (auto-generated)
# JVM proxy settings for Bazel server (BCR access, etc.)
startup --host_jvm_args=-Dhttps.proxyHost=127.0.0.1
startup --host_jvm_args=-Dhttps.proxyPort={BAZEL_PROXY_PORT}
startup --host_jvm_args=-Djavax.net.ssl.trustStore={BAZEL_TRUSTSTORE}
startup --host_jvm_args=-Djavax.net.ssl.trustStorePassword=changeit

# Propagate proxy env vars into sandbox actions (for pip, uv, etc.)
build --action_env=HTTPS_PROXY={local_proxy}
build --action_env=HTTP_PROXY={local_proxy}
build --action_env=https_proxy={local_proxy}
build --action_env=http_proxy={local_proxy}
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


def _create_combined_ca_bundle() -> bool:
    """Create a combined CA bundle with system CAs plus the proxy CA.

    This is needed for tools like uv that use SSL_CERT_FILE.
    Returns True if bundle was created successfully.
    """
    # Prefer pre-installed Anthropic CA, fall back to extracted one
    ca_file = ANTHROPIC_CA_PREINSTALLED if ANTHROPIC_CA_PREINSTALLED.exists() else BAZEL_CA_FILE
    if not ca_file.exists():
        log.warning("No CA file to add to bundle")
        return False

    log.info("Using CA from %s", ca_file)

    # Find system CA bundle
    system_ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    if not system_ca_bundle.exists():
        for alt in [Path("/etc/pki/tls/certs/ca-bundle.crt"), Path("/etc/ssl/ca-bundle.pem")]:
            if alt.exists():
                system_ca_bundle = alt
                break
        else:
            log.warning("Could not find system CA bundle")
            return False

    log.info("Creating combined CA bundle from %s", system_ca_bundle)

    # Combine system CAs with proxy CA
    combined = system_ca_bundle.read_text() + "\n" + ca_file.read_text()
    BAZEL_COMBINED_CA.write_text(combined)

    log.info("Created combined CA bundle at %s", BAZEL_COMBINED_CA)
    return True


def _write_proxy_env_bzl() -> None:
    """Write a .bzl file with proxy environment variables.

    This file is loaded by BUILD files that need proxy env vars for
    sandbox actions (like the uv lock() rule which doesn't inherit --action_env).
    """
    local_proxy = f"http://localhost:{BAZEL_PROXY_PORT}"

    bzl_content = f'''\
# Auto-generated by bazel_proxy_setup.py for Claude Code web
# Provides proxy environment variables for Bazel sandbox actions

PROXY_ENV = {{
    "HTTPS_PROXY": "{local_proxy}",
    "HTTP_PROXY": "{local_proxy}",
    "https_proxy": "{local_proxy}",
    "http_proxy": "{local_proxy}",
    "SSL_CERT_FILE": "{BAZEL_COMBINED_CA}",
    "REQUESTS_CA_BUNDLE": "{BAZEL_COMBINED_CA}",
}}
'''
    BAZEL_PROXY_ENV_BZL.write_text(bzl_content)
    log.info("Wrote proxy env .bzl to %s", BAZEL_PROXY_ENV_BZL)


def _install_bazel_wrapper() -> None:
    """Install a bazel wrapper script that sets proxy env vars.

    The wrapper is placed in ~/.local/bin (which should be early in PATH).
    It sets HTTPS_PROXY to our local proxy, then execs the real bazel.
    This keeps the proxy override Bazel-specific, not global.
    """
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    wrapper_path = local_bin / "bazel"

    # Find real bazel location
    real_bazel = shutil.which("bazel")
    if not real_bazel:
        log.warning("Could not find bazel in PATH, skipping wrapper")
        return

    # Don't wrap our own wrapper
    if str(wrapper_path) == real_bazel:
        # Already have wrapper, need to find real bazel
        # Check common locations
        for candidate in ["/usr/bin/bazel", "/usr/local/bin/bazel"]:
            if Path(candidate).exists():
                real_bazel = candidate
                break
        else:
            log.warning("Could not find real bazel binary")
            return

    local_proxy = f"http://localhost:{BAZEL_PROXY_PORT}"

    wrapper_content = f'''#!/bin/bash
# Bazel wrapper for Claude Code web - sets proxy env vars for Bazel only
# Generated by bazel_proxy_setup.py

# Override proxy env vars to use our local auth proxy
export HTTPS_PROXY="{local_proxy}"
export HTTP_PROXY="{local_proxy}"
export https_proxy="{local_proxy}"
export http_proxy="{local_proxy}"

# Execute real bazel
exec {real_bazel} "$@"
'''
    wrapper_path.write_text(wrapper_content)
    wrapper_path.chmod(0o755)
    log.info("Installed bazel wrapper at %s (wraps %s)", wrapper_path, real_bazel)


def setup_bazel_proxy() -> None:
    """Set up the complete Bazel proxy environment for TLS-inspecting proxies.

    This is needed when running behind Anthropic's TLS-inspecting proxy
    (Claude Code web). Steps:
    1. Update credentials and start local proxy (handles auth to upstream)
    2. Extract the TLS inspection CA (via local proxy)
    3. Create Java truststore with the CA
    4. Write bazelrc configuration to use the proxy
    5. Persist proxy env overrides for Bazel and other tools
    """
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, Bazel proxy setup not needed")
        return

    log.info("Setting up Bazel proxy for TLS-inspecting proxy...")
    BAZEL_PROXY_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Update credentials and start local proxy first (needed for CA extraction)
    _update_proxy_credentials()
    if not _start_proxy_server():
        log.warning("Could not start Bazel proxy")
        return

    # Step 2: Extract the TLS inspection CA (via local proxy)
    if not _extract_proxy_ca():
        log.warning("Could not extract proxy CA, Bazel BCR access may fail")
        return

    # Step 3: Create Java truststore with the CA
    if not _create_java_truststore():
        log.warning("Could not create Java truststore")
        return

    # Step 4: Create combined CA bundle (for tools like uv that use SSL_CERT_FILE)
    _create_combined_ca_bundle()

    # Step 5: Write bazelrc configuration
    _write_bazel_config()

    # Step 6: Write .bzl file with proxy env vars (for rules that don't inherit --action_env)
    _write_proxy_env_bzl()

    # Step 7: Install bazel wrapper (sets proxy env vars for Bazel only)
    _install_bazel_wrapper()

    log.info("Bazel proxy setup complete")


def is_configured() -> bool:
    """Check if Bazel proxy is configured."""
    return BAZEL_TRUSTSTORE.exists()


def get_status() -> str:
    """Get human-readable proxy status."""
    if BAZEL_TRUSTSTORE.exists():
        return f"configured (port {BAZEL_PROXY_PORT})"
    return "not configured"
