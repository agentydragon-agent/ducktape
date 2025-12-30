"""Streaming command execution with heartbeat output."""

from datetime import datetime
import logging
import os
import select
import subprocess

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0


def run_streaming(
    cmd: list[str],
    operation: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> int:
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
