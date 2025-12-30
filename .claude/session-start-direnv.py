#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv, and Bazel proxy."""

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import traceback
from typing import IO
from urllib.parse import urlparse

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv", "uv"]

# Bazel proxy configuration
BAZEL_PROXY_PORT = 18081
BAZEL_PROXY_SCRIPT = Path("/tmp/bazel_proxy.py")
BAZEL_CA_FILE = Path("/tmp/anthropic_ca.pem")
BAZEL_TRUSTSTORE = Path("/tmp/custom_cacerts.jks")
BAZEL_USER_BAZELRC = Path.home() / ".bazelrc"

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0


@contextmanager
def heartbeat(operation: str) -> Iterator[None]:
    """Log heartbeat messages during long-running operations with no output."""
    stop_event = threading.Event()
    start_time = datetime.now()

    def heartbeat_thread() -> None:
        beat_count = 0
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            beat_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            log.info("heartbeat: %s still running (%.1fs elapsed, beat #%d)", operation, elapsed, beat_count)

    thread = threading.Thread(target=heartbeat_thread, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1.0)
        elapsed = (datetime.now() - start_time).total_seconds()
        log.info("heartbeat: %s completed (%.1fs total)", operation, elapsed)


def stream_output(stream: IO[str], prefix: str) -> None:
    """Stream output line by line, logging each line as it arrives."""
    for raw_line in stream:
        line = raw_line.rstrip("\n\r")
        if line:
            log.info("%s %s", prefix, line)


def run_streaming(cmd: list[str], operation: str, check: bool = True, env: dict[str, str] | None = None) -> int:
    """Run command with real-time streaming output.

    Streams stdout and stderr to the log as lines arrive.
    Uses heartbeat as fallback for periods with no output.
    """
    log.info(">>> %s", " ".join(cmd))
    start_time = datetime.now()

    merged_env = {**os.environ, **(env or {})}

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
        env=merged_env,
    )

    assert proc.stdout is not None

    # Stream output with heartbeat fallback
    last_output_time = datetime.now()
    heartbeat_count = 0

    while True:
        # Use a timeout so we can emit heartbeats during long silences
        import select

        ready, _, _ = select.select([proc.stdout], [], [], HEARTBEAT_INTERVAL_SECONDS)

        if ready:
            line = proc.stdout.readline()
            if not line:
                # EOF - process finished
                break
            line = line.rstrip("\n\r")
            if line:
                log.info("  | %s", line)
                last_output_time = datetime.now()
        else:
            # No output - emit heartbeat
            heartbeat_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            silence = (datetime.now() - last_output_time).total_seconds()
            log.info(
                "  ~ %s: waiting (%.1fs elapsed, %.1fs since last output, beat #%d)",
                operation,
                elapsed,
                silence,
                heartbeat_count,
            )

    proc.wait()
    elapsed = (datetime.now() - start_time).total_seconds()

    if proc.returncode == 0:
        log.info("<<< %s completed successfully (%.1fs)", operation, elapsed)
    else:
        log.error("<<< %s failed with code %d (%.1fs)", operation, proc.returncode, elapsed)
        if check:
            raise RuntimeError(f"{operation} failed with exit code {proc.returncode}")

    return proc.returncode


def which(cmd: str) -> str | None:
    """Find command in PATH."""
    result = subprocess.run(["which", cmd], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def find_nix_bin() -> Path | None:
    """Find nix binary directory in /nix/store."""
    nix_store = Path("/nix/store")
    if not nix_store.exists():
        return None
    for entry in sorted(nix_store.iterdir(), reverse=True):
        if "-nix-" in entry.name:
            bin_dir = entry / "bin"
            if bin_dir.exists() and (bin_dir / "nix").exists():
                return bin_dir
    return None


def setup_nix_path(nix_store_bin: Path) -> None:
    """Add nix store bin and profile bin to PATH."""
    paths = [nix_store_bin, Path.home() / ".nix-profile" / "bin"]
    paths = [p for p in paths if p.exists()]
    if paths:
        os.environ["PATH"] = ":".join(map(str, paths)) + ":" + os.environ.get("PATH", "")
        log.info("Added to PATH: %s", ", ".join(map(str, paths)))


def install_nix(project_dir: Path) -> Path:
    """Install nix if not present. Returns the nix store bin path."""
    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    if nix_conf.exists():
        os.environ["NIX_USER_CONF_FILES"] = str(nix_conf)
        log.info("Using nix.conf: %s", nix_conf)

    # Check if nix is already in the store
    nix_store_bin = find_nix_bin()
    if nix_store_bin:
        log.info("nix already in store: %s", nix_store_bin)
        setup_nix_path(nix_store_bin)
        return nix_store_bin

    log.info("Installing nix...")

    # Download with progress bar
    run_streaming(
        ["curl", "--progress-bar", "-L", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"],
        "downloading nix installer",
    )

    # The nix-env step fails in gVisor containers due to a PTY bug.
    # nix-env opens /dev/ptmx, forks a sandbox process, then reads from the PTY master.
    # gVisor returns EIO on this read (race condition in PTY emulation).
    #
    # ROOT CAUSE (discovered via strace):
    # Claude Code web runs on gVisor (runsc), not a real Linux kernel. gVisor's PTY
    # emulation has a race condition. When nix-env builds a derivation, it:
    #   1. Opens /dev/ptmx to create a PTY pair (master fd)
    #   2. Forks a child process for the build sandbox
    #   3. Parent immediately calls read() on the PTY master
    #   4. gVisor returns EIO instead of blocking until data arrives
    #
    # WORKAROUND:
    # Skip nix-env entirely. The installer already unpacked Nix to /nix/store.
    # We use the store path directly instead of relying on profiles.
    run_streaming(
        ["sh", "-x", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        "running nix installer",
        check=False,  # Installer may fail on nix-env step, that's OK
    )

    nix_store_bin = find_nix_bin()
    if not nix_store_bin:
        raise RuntimeError("Failed to install nix - no nix binary found in store")

    log.info("nix installed: %s", nix_store_bin)
    setup_nix_path(nix_store_bin)
    return nix_store_bin


def install_tools(nix_store_bin: Path, tools: list[str]) -> None:
    """Install tools via nix profile using the store path directly.

    Uses the nix binary from the store path, NOT from PATH or profile.
    This avoids the issue where `nix profile install` replaces the profile
    and removes nix from PATH.
    """
    nix_cmd = nix_store_bin / "nix"

    # Filter out tools that are already available
    missing_tools = [t for t in tools if not which(t)]
    if not missing_tools:
        log.info("All tools already available: %s", ", ".join(tools))
        return

    log.info("Installing tools: %s", ", ".join(missing_tools))

    # Install all missing tools in one command with verbose output
    # -v: verbose, --print-build-logs: show build output
    cmd = [str(nix_cmd), "profile", "install", "-v", "--print-build-logs"] + [f"nixpkgs#{t}" for t in missing_tools]

    run_streaming(cmd, f"installing {', '.join(missing_tools)}")

    log.info("Tools installed successfully")


def persist_environment(env_file: str | None, nix_store_bin: Path, project_dir: Path) -> None:
    """Write environment to CLAUDE_ENV_FILE for persistence.

    Persists BOTH the nix store bin (for running nix commands) AND the
    profile bin (for user-installed tools like direnv, devenv).
    """
    if not env_file:
        log.warning("CLAUDE_ENV_FILE is empty, PATH changes will not persist")
        return

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    content = f'''# Nix environment (added by session-start-direnv.py)
export NIX_USER_CONF_FILES="{nix_conf}"
# Nix store bin for running nix commands (immutable, always available)
[ -d "{nix_store_bin}" ] && export PATH="{nix_store_bin}:$PATH"
# Profile bin for user-installed tools (direnv, devenv, etc.)
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"
'''
    Path(env_file).write_text(content)
    log.info("Wrote environment to CLAUDE_ENV_FILE=%s", env_file)


# ============================================================================
# Bazel Proxy Setup
# ============================================================================
# Claude Code web uses a TLS-inspecting proxy that breaks Bazel's BCR access.
# This section sets up a local proxy wrapper that handles JWT authentication
# and a custom Java truststore for the proxy's TLS inspection CA.


def parse_proxy_url(proxy_url: str) -> tuple[str, int, str | None, str | None]:
    """Parse proxy URL into (host, port, user, password)."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = parsed.port or 80
    user = parsed.username
    password = parsed.password
    return host, port, user, password


def extract_proxy_ca() -> bool:
    """Extract the TLS inspection CA certificate from the proxy.

    Returns True if CA was extracted successfully.
    """
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, skipping CA extraction")
        return False

    host, port, _, _ = parse_proxy_url(https_proxy)
    if not host:
        log.warning("Could not parse proxy URL: %s", https_proxy)
        return False

    log.info("Extracting TLS inspection CA from proxy %s:%d", host, port)

    # Use openssl to connect through proxy and extract certificates
    try:
        result = subprocess.run(
            [
                "openssl", "s_client",
                "-proxy", f"{host}:{port}",
                "-connect", "bcr.bazel.build:443",
                "-showcerts",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Extract all certificates from the chain
        certs = re.findall(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
            result.stdout,
            re.DOTALL,
        )

        if len(certs) < 2:
            log.warning("Expected at least 2 certs in chain, got %d", len(certs))
            return False

        # The TLS inspection CA is typically the second-to-last cert in the chain
        # (the last one is the root CA, the one before is the inspection CA)
        inspection_ca = certs[-1]  # Try the root CA first

        # Verify it's the Anthropic CA
        verify_result = subprocess.run(
            ["openssl", "x509", "-noout", "-subject", "-issuer"],
            input=inspection_ca,
            capture_output=True,
            text=True,
        )

        if "Anthropic" in verify_result.stdout or "TLS Inspection" in verify_result.stdout:
            log.info("Found Anthropic TLS inspection CA")
            BAZEL_CA_FILE.write_text(inspection_ca)
            return True

        # Try other certs in the chain
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

    except subprocess.TimeoutExpired:
        log.warning("Timeout extracting CA from proxy")
        return False
    except Exception as e:
        log.warning("Error extracting CA: %s", e)
        return False


def create_java_truststore() -> bool:
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


def write_bazel_proxy_script() -> None:
    """Write the local proxy wrapper script."""
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        return

    host, port, user, password = parse_proxy_url(https_proxy)

    script = f'''#!/usr/bin/env python3
"""Local proxy that adds authentication for the upstream proxy."""

import base64
import socket
import threading
import sys

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = {BAZEL_PROXY_PORT}
UPSTREAM_HOST = "{host}"
UPSTREAM_PORT = {port}
UPSTREAM_USER = "{user or ''}"
UPSTREAM_PASS = "{password or ''}"


def make_auth_header() -> str:
    """Create Proxy-Authorization header."""
    if not UPSTREAM_USER:
        return ""
    creds = f"{{UPSTREAM_USER}}:{{UPSTREAM_PASS}}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Proxy-Authorization: Basic {{encoded}}\\r\\n"


def handle_connect(client_sock: socket.socket, target_host: str, target_port: int) -> None:
    """Handle CONNECT request by tunneling through upstream proxy."""
    try:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.connect((UPSTREAM_HOST, UPSTREAM_PORT))

        # Send CONNECT with auth to upstream
        connect_req = (
            f"CONNECT {{target_host}}:{{target_port}} HTTP/1.1\\r\\n"
            f"Host: {{target_host}}:{{target_port}}\\r\\n"
            f"{{make_auth_header()}}"
            f"\\r\\n"
        )
        upstream.sendall(connect_req.encode())

        # Read response
        response = b""
        while b"\\r\\n\\r\\n" not in response:
            chunk = upstream.recv(4096)
            if not chunk:
                break
            response += chunk

        # Check if connection established
        if b"200" in response.split(b"\\r\\n")[0]:
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\\r\\n\\r\\n")

            # Tunnel data bidirectionally
            def forward(src: socket.socket, dst: socket.socket) -> None:
                try:
                    while True:
                        data = src.recv(65536)
                        if not data:
                            break
                        dst.sendall(data)
                except:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except:
                        pass

            t1 = threading.Thread(target=forward, args=(client_sock, upstream))
            t2 = threading.Thread(target=forward, args=(upstream, client_sock))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        else:
            client_sock.sendall(response)

    except Exception as e:
        print(f"Error: {{e}}", file=sys.stderr)
    finally:
        try:
            upstream.close()
        except:
            pass
        try:
            client_sock.close()
        except:
            pass


def handle_client(client_sock: socket.socket) -> None:
    """Handle incoming client connection."""
    try:
        # Read the request
        request = b""
        while b"\\r\\n\\r\\n" not in request:
            chunk = client_sock.recv(4096)
            if not chunk:
                return
            request += chunk

        first_line = request.split(b"\\r\\n")[0].decode()
        parts = first_line.split()
        if len(parts) < 3:
            return

        method = parts[0]
        target = parts[1]

        if method == "CONNECT":
            # Parse host:port
            if ":" in target:
                host, port = target.rsplit(":", 1)
                port = int(port)
            else:
                host = target
                port = 443
            handle_connect(client_sock, host, port)
        else:
            # Forward non-CONNECT requests (shouldn't happen for HTTPS)
            client_sock.close()

    except Exception as e:
        print(f"Error handling client: {{e}}", file=sys.stderr)
        try:
            client_sock.close()
        except:
            pass


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(10)
    print(f"Bazel proxy listening on {{LISTEN_HOST}}:{{LISTEN_PORT}}")
    print(f"Forwarding to {{UPSTREAM_HOST}}:{{UPSTREAM_PORT}}")

    while True:
        client_sock, addr = server.accept()
        threading.Thread(target=handle_client, args=(client_sock,), daemon=True).start()


if __name__ == "__main__":
    main()
'''
    BAZEL_PROXY_SCRIPT.write_text(script)
    BAZEL_PROXY_SCRIPT.chmod(0o755)
    log.info("Wrote Bazel proxy script to %s", BAZEL_PROXY_SCRIPT)


def start_bazel_proxy() -> bool:
    """Start the local Bazel proxy in the background.

    Returns True if proxy was started successfully.
    """
    if not BAZEL_PROXY_SCRIPT.exists():
        log.warning("Bazel proxy script not found")
        return False

    # Check if already running
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
        sock.close()
        if result == 0:
            log.info("Bazel proxy already running on port %d", BAZEL_PROXY_PORT)
            return True
    except:
        pass

    # Kill any existing proxy
    subprocess.run(["pkill", "-f", "bazel_proxy.py"], capture_output=True)

    # Start the proxy
    log.info("Starting Bazel proxy on port %d", BAZEL_PROXY_PORT)
    subprocess.Popen(
        ["python3", str(BAZEL_PROXY_SCRIPT)],
        stdout=open("/tmp/bazel_proxy.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Wait for it to start
    import time
    for _ in range(10):
        time.sleep(0.5)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
            sock.close()
            if result == 0:
                log.info("Bazel proxy started successfully")
                return True
        except:
            pass

    log.warning("Failed to start Bazel proxy")
    return False


def write_bazel_config() -> None:
    """Write Bazel configuration for the proxy."""
    if not BAZEL_TRUSTSTORE.exists():
        log.warning("No truststore, skipping bazelrc")
        return

    # Write user bazelrc with proxy settings
    bazelrc_content = f"""# Bazel proxy configuration for Claude Code web (auto-generated)
# This configures Bazel to use the local proxy wrapper and custom truststore

# JVM args for proxy and TLS
startup --host_jvm_args=-Dhttps.proxyHost=127.0.0.1
startup --host_jvm_args=-Dhttps.proxyPort={BAZEL_PROXY_PORT}
startup --host_jvm_args=-Djavax.net.ssl.trustStore={BAZEL_TRUSTSTORE}
startup --host_jvm_args=-Djavax.net.ssl.trustStorePassword=changeit
"""

    # Append to existing bazelrc or create new
    if BAZEL_USER_BAZELRC.exists():
        existing = BAZEL_USER_BAZELRC.read_text()
        if "Claude Code web" in existing:
            log.info("Bazel proxy config already in ~/.bazelrc")
            return
        BAZEL_USER_BAZELRC.write_text(existing + "\n" + bazelrc_content)
    else:
        BAZEL_USER_BAZELRC.write_text(bazelrc_content)

    log.info("Wrote Bazel proxy config to %s", BAZEL_USER_BAZELRC)


def setup_bazel_proxy() -> None:
    """Set up the complete Bazel proxy environment."""
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, Bazel proxy setup not needed")
        return

    log.info("Setting up Bazel proxy for TLS-inspecting proxy...")

    # Step 1: Extract the TLS inspection CA
    if not extract_proxy_ca():
        log.warning("Could not extract proxy CA, Bazel BCR access may fail")
        return

    # Step 2: Create Java truststore with the CA
    if not create_java_truststore():
        log.warning("Could not create Java truststore")
        return

    # Step 3: Write and start the local proxy wrapper
    write_bazel_proxy_script()
    if not start_bazel_proxy():
        log.warning("Could not start Bazel proxy")
        return

    # Step 4: Write bazelrc configuration
    write_bazel_config()

    log.info("Bazel proxy setup complete")


def main() -> int:
    log.info("=" * 60)
    log.info("Starting hook at %s", datetime.now().isoformat())
    log.info("=" * 60)
    log.info("Environment: %s", json.dumps(dict(os.environ), sort_keys=True, indent=2))

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir:
        raise RuntimeError("CLAUDE_PROJECT_DIR not set")
    project_dir = Path(project_dir)

    log.info("Setting up dev environment...")

    # Install nix and get the store bin path (used for all subsequent nix commands)
    nix_store_bin = install_nix(project_dir)

    # Install tools using the store path directly
    install_tools(nix_store_bin, TOOLS)

    # Allow .envrc files
    if which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            log.info("Allowing direnv for: %s", envrc.parent)
            run_streaming(["direnv", "allow", str(envrc.parent)], f"direnv allow {envrc.parent.name}", check=False)

    # Persist environment with both store bin and profile bin
    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    # Set up Bazel proxy for TLS-inspecting proxy (Claude Code web specific)
    setup_bazel_proxy()

    log.info("=" * 60)
    log.info("Session environment initialized:")
    for tool in ["nix", *TOOLS, "bazel"]:
        if path := which(tool):
            result = subprocess.run([tool, "--version"], capture_output=True, text=True, check=False)
            version = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?"
            log.info("  %-10s %s (%s)", tool + ":", version, path)
        else:
            log.info("  %-10s N/A", tool + ":")

    # Log Bazel proxy status
    if BAZEL_TRUSTSTORE.exists():
        log.info("  Bazel proxy: configured (port %d)", BAZEL_PROXY_PORT)
    else:
        log.info("  Bazel proxy: not configured")

    log.info("=" * 60)
    log.info("Setup complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("=" * 60)
        log.error("Hook failed: %s", e)
        log.error("=" * 60)
        log.error(traceback.format_exc())
        sys.exit(1)
