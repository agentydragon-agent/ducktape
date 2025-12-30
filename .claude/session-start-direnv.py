#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, and Bazel proxy."""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import traceback
from urllib.parse import urlparse

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv"]

# Bazel proxy configuration - files stored in ~/.cache/bazel-proxy/
BAZEL_PROXY_PORT = 18081
BAZEL_PROXY_DIR = Path.home() / ".cache" / "bazel-proxy"
BAZEL_PROXY_LOG = BAZEL_PROXY_DIR / "proxy.log"
BAZEL_CA_FILE = BAZEL_PROXY_DIR / "anthropic_ca.pem"
BAZEL_TRUSTSTORE = BAZEL_PROXY_DIR / "cacerts.jks"
BAZEL_USER_BAZELRC = Path.home() / ".bazelrc"

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0


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
    return shutil.which(cmd)


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


def get_bazel_proxy_script() -> Path:
    """Get the path to the bazel proxy script (bundled with the hook)."""
    return Path(__file__).parent / "claude-code-web" / "bazel_proxy.py"


def start_bazel_proxy() -> bool:
    """Start the local Bazel proxy in the background.

    Returns True if proxy was started successfully.
    """
    proxy_script = get_bazel_proxy_script()
    if not proxy_script.exists():
        log.warning("Bazel proxy script not found at %s", proxy_script)
        return False

    # Check if already running
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
        sock.close()
        if result == 0:
            log.info("Bazel proxy already running on port %d", BAZEL_PROXY_PORT)
            return True
    except Exception:
        pass

    # Kill any existing proxy
    subprocess.run(["pkill", "-f", "bazel_proxy.py"], capture_output=True)

    # Start the proxy (reads https_proxy from environment)
    log.info("Starting Bazel proxy on port %d", BAZEL_PROXY_PORT)
    subprocess.Popen(
        ["python3", str(proxy_script), "--listen-port", str(BAZEL_PROXY_PORT)],
        stdout=open(BAZEL_PROXY_LOG, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Wait for it to start
    for _ in range(10):
        time.sleep(0.5)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", BAZEL_PROXY_PORT))
            sock.close()
            if result == 0:
                log.info("Bazel proxy started successfully")
                return True
        except Exception:
            pass

    log.warning("Failed to start Bazel proxy")
    return False


BAZEL_PROXY_RC = BAZEL_PROXY_DIR / "bazelrc"


def write_bazel_config() -> None:
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
    """Set up the complete Bazel proxy environment."""
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not https_proxy:
        log.info("No https_proxy set, Bazel proxy setup not needed")
        return

    log.info("Setting up Bazel proxy for TLS-inspecting proxy...")
    BAZEL_PROXY_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract the TLS inspection CA
    if not extract_proxy_ca():
        log.warning("Could not extract proxy CA, Bazel BCR access may fail")
        return

    # Step 2: Create Java truststore with the CA
    if not create_java_truststore():
        log.warning("Could not create Java truststore")
        return

    # Step 3: Start the local proxy wrapper
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
