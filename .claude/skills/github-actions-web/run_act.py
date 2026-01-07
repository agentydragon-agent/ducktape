#!/usr/bin/env python3
"""Run act with all workarounds for Claude Code on the web's gVisor container.

Auto-detects CA bundle, proxy settings, and custom image if available.
All operations use stdlib only - no external dependencies needed.

Usage:
    ./run_act.py [job-name] [extra-act-args...]

Examples:
    ./run_act.py pre-commit
    ./run_act.py bazel-build --verbose
    ./run_act.py -l  # List jobs
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PODMAN_SOCKET = "/tmp/podman.sock"
CA_BUNDLE_DEST = "/tmp/ca-bundle.pem"
ACT_PATHS = ["/root/.local/bin/act"]
CUSTOM_IMAGE = "localhost/act-proxy:latest"
DEFAULT_IMAGE = "catthehacker/ubuntu:act-latest"

# Known CA bundle locations in order of preference
CA_BUNDLE_LOCATIONS = [
    "/tmp/ca-bundle.pem",
    "/root/.cache/bazel-proxy/combined_ca.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    os.environ.get("SSL_CERT_FILE", ""),
    os.environ.get("REQUESTS_CA_BUNDLE", ""),
    os.environ.get("ACT_CA_BUNDLE", ""),
]


def run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, check=check, **kwargs)


def find_ca_bundle() -> str | None:
    """Find CA bundle from known locations."""
    for loc in CA_BUNDLE_LOCATIONS:
        if loc and Path(loc).is_file():
            return loc
    return None


def ensure_ca_bundle() -> str:
    """Ensure CA bundle is available at /tmp/ca-bundle.pem."""
    ca_bundle = find_ca_bundle()
    if not ca_bundle:
        print("ERROR: CA bundle not found. Run setup_podman.py first or set ACT_CA_BUNDLE.")
        sys.exit(1)

    # Copy to /tmp if not already there
    if ca_bundle != CA_BUNDLE_DEST:
        shutil.copy(ca_bundle, CA_BUNDLE_DEST)

    return CA_BUNDLE_DEST


def ensure_podman_running() -> None:
    """Ensure podman socket is running."""
    if Path(PODMAN_SOCKET).is_socket():
        return

    print("Podman socket not found. Starting podman service...")
    run(["pkill", "-9", "podman"], check=False)
    time.sleep(1)
    subprocess.Popen(
        ["podman", "system", "service", "--time=0", f"unix://{PODMAN_SOCKET}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)


def cleanup_containers() -> None:
    """Clean up any stale containers."""
    run(["podman", "rm", "--all", "--force"], check=False, capture_output=True)


def find_act() -> str:
    """Find act binary."""
    # Check explicit paths first
    for path in ACT_PATHS:
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path

    # Check PATH
    act_in_path = shutil.which("act")
    if act_in_path:
        return act_in_path

    print("ERROR: act not found. Run setup_podman.py first.")
    sys.exit(1)


def check_custom_image() -> tuple[str, bool]:
    """Check if custom act-proxy image exists."""
    result = run(["podman", "image", "exists", CUSTOM_IMAGE], check=False, capture_output=True)
    if result.returncode == 0:
        print("Using custom act-proxy:latest image (with global-agent)")
        return CUSTOM_IMAGE, True
    print("Using standard catthehacker/ubuntu:act-latest image")
    print("Note: Some Node.js actions may fail. Build act-proxy:latest for full support.")
    return DEFAULT_IMAGE, False


def get_proxy_env() -> dict[str, str]:
    """Get proxy environment variables."""
    http_proxy = os.environ.get("HTTP_PROXY", "")
    https_proxy = os.environ.get("HTTPS_PROXY", "")

    return {
        "HTTP_PROXY": http_proxy,
        "HTTPS_PROXY": https_proxy,
        "http_proxy": os.environ.get("http_proxy", http_proxy),
        "https_proxy": os.environ.get("https_proxy", https_proxy),
        "NO_PROXY": os.environ.get("NO_PROXY", "localhost,127.0.0.1"),
        "no_proxy": os.environ.get("no_proxy", os.environ.get("NO_PROXY", "localhost,127.0.0.1")),
        "GLOBAL_AGENT_HTTP_PROXY": os.environ.get("GLOBAL_AGENT_HTTP_PROXY", http_proxy),
        "GLOBAL_AGENT_HTTPS_PROXY": os.environ.get("GLOBAL_AGENT_HTTPS_PROXY", https_proxy),
    }


def build_act_command(
    act_bin: str, job: str, runner_image: str, use_local_image: bool, ca_bundle: str, extra_args: list[str]
) -> list[str]:
    """Build the act command with all workarounds."""
    proxy_env = get_proxy_env()

    cmd = [act_bin, "-j", job, "-P", f"ubuntu-latest={runner_image}"]

    # Don't pull if using local image
    if use_local_image:
        cmd.append("--pull=false")

    cmd.append("--network=host")

    # Add proxy environment variables
    for key, value in proxy_env.items():
        cmd.extend(["--env", f"{key}={value}"])

    # Add CA bundle environment variables
    ca_env_vars = ["NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "GIT_SSL_CAINFO"]
    for var in ca_env_vars:
        cmd.extend(["--env", f"{var}={ca_bundle}"])

    # Mount CA bundle into container
    cmd.extend(["--container-options", f"-v {ca_bundle}:{ca_bundle}:ro"])

    # Add extra args
    cmd.extend(extra_args)

    return cmd


def main() -> int:
    """Main entry point."""
    # Parse arguments
    args = sys.argv[1:]
    job = args[0] if args else "-l"
    extra_args = args[1:] if len(args) > 1 else []

    # Set DOCKER_HOST for podman
    os.environ["DOCKER_HOST"] = f"unix://{PODMAN_SOCKET}"

    # Find act binary
    act_bin = find_act()

    # Handle list jobs command
    if job == "-l":
        return run([act_bin, "-l", *extra_args], check=False).returncode

    # Setup for running a job
    ca_bundle = ensure_ca_bundle()
    ensure_podman_running()
    cleanup_containers()
    runner_image, use_local_image = check_custom_image()

    print(f"Running job: {job}")
    print(f"CA bundle: {ca_bundle}")
    print()

    # Build and run act command
    cmd = build_act_command(act_bin, job, runner_image, use_local_image, ca_bundle, extra_args)

    return run(cmd, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
