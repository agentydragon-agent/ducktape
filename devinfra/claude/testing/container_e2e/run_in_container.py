"""Script that runs inside the Docker container for the container E2E test.

Installs the ducktape wheel, runs the session start hook via `claude-hook`,
then verifies Bazel can build through the proxy chain.

Expected environment (set by the test orchestrator):
    WHEEL_PATH: Path to the mounted wheel file inside the container
    CLAUDE_CODE_REMOTE: "true" (triggers web mode)
    CLAUDE_PROJECT_DIR: Project directory with .git
    CLAUDE_ENV_FILE: Where the hook writes the env file
    HTTPS_PROXY / HTTP_PROXY: Mock egress proxy URL (on host)
    ANTHROPIC_CA_PATH: Path to the mock CA cert
    SSL_CERT_FILE / REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE / NODE_EXTRA_CA_CERTS: Combined CA
    DUCKTAPE_CLAUDE_HOOKS_*: Hook settings
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    wheel_path = os.environ["WHEEL_PATH"]
    project_dir = Path(os.environ["CLAUDE_PROJECT_DIR"])
    env_file = Path(os.environ["CLAUDE_ENV_FILE"])

    print(f"=== Installing wheel: {wheel_path}", flush=True)
    subprocess.run(["pip", "install", "--break-system-packages", wheel_path], check=True)

    # Verify claude-hook is on PATH
    result = subprocess.run(["which", "claude-hook"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR: claude-hook not found on PATH after wheel install", file=sys.stderr)
        return 1
    print(f"claude-hook installed at: {result.stdout.strip()}", flush=True)

    # Create hook input JSON (matches SessionStartHookInput schema)
    hook_input = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "session_id": "container-e2e-test",
            "cwd": str(project_dir),
            "transcript_path": "/tmp/transcript.json",
            "permission_mode": "default",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        }
    )

    print("=== Running claude-hook (session start)", flush=True)
    hook_result = subprocess.run(
        ["claude-hook"],
        check=False,
        input=hook_input,
        capture_output=True,
        text=True,
        # Clear PYTHONPATH so only wheel's own deps are visible
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
    )
    print(f"Hook stdout: {hook_result.stdout}", flush=True)
    print(f"Hook stderr: {hook_result.stderr}", flush=True)
    if hook_result.returncode != 0:
        # Dump daemon log for debugging
        daemon_log = (
            Path(os.environ["HOME"]) / ".claude" / "session-env" / "container-e2e-test" / "hook-daemon" / "daemon.log"
        )
        if daemon_log.exists():
            print(f"=== Daemon log ({daemon_log}):", flush=True)
            print(daemon_log.read_text(), flush=True)
        daemon_err = daemon_log.with_name("daemon.err.log")
        if daemon_err.exists():
            print(f"=== Daemon error log ({daemon_err}):", flush=True)
            print(daemon_err.read_text(), flush=True)
        print(f"ERROR: claude-hook failed with rc={hook_result.returncode}", file=sys.stderr)
        return 1

    # Verify key artifacts
    session_dir = env_file.parent
    assert (session_dir / "bazelrc").exists(), "bazelrc not created"
    assert (session_dir / "auth-proxy" / "anthropic_ca.pem").exists(), "CA not extracted"
    assert env_file.exists(), f"Env file not created at {env_file}"
    print("=== Session start artifacts verified", flush=True)

    # Run bazel build through the proxy chain
    test_workspace = project_dir / "test_workspace"
    # Source the env file (like Claude Code would) then run bazel
    output_base = Path("/tmp/bazel_output_base")
    output_base.mkdir(parents=True, exist_ok=True)

    bazel_cmd = (
        f"source {env_file} && bazel --output_base={output_base} build --shell_executable=$(which bash) //:hello"
    )
    print(f"=== Running: {bazel_cmd}", flush=True)
    print(f"    cwd: {test_workspace}", flush=True)

    bazel_result = subprocess.run(
        ["bash", "-c", bazel_cmd], check=False, cwd=test_workspace, capture_output=True, text=True, timeout=120
    )
    print(f"Bazel stdout: {bazel_result.stdout}", flush=True)
    print(f"Bazel stderr: {bazel_result.stderr}", flush=True)

    if bazel_result.returncode != 0:
        print(f"ERROR: bazel build failed with rc={bazel_result.returncode}", file=sys.stderr)
        return 1

    print("=== Container E2E test PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
