"""Pre-load OCI image tarballs into the local container runtime.

Used by test fixtures to pre-load Bazel-bundled container images (from
oci_tarball) so Testcontainers doesn't need to pull from Docker Hub.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

import runfiles

logger = logging.getLogger(__name__)


def load_image(tarball_rlocation: str) -> None:
    """Load a Docker image tarball into the container runtime.

    Args:
        tarball_rlocation: Runfiles-relative path to the tarball
            (e.g., "_main/props/testing/fixtures/postgres_16_tarball/tarball.tar").
    """
    start = time.monotonic()
    tarball_path = runfiles.get_required_path(tarball_rlocation)
    resolve_elapsed = time.monotonic() - start

    cmd = shutil.which("docker") or shutil.which("podman")
    if not cmd:
        raise RuntimeError("Neither docker nor podman CLI found")

    logger.info("Loading image from %s via %s", tarball_path, cmd)
    load_start = time.monotonic()
    result = subprocess.run([cmd, "load", "-i", str(tarball_path)], check=False, capture_output=True, text=True)
    load_elapsed = time.monotonic() - load_start

    if result.returncode != 0:
        raise RuntimeError(f"Failed to load image from {tarball_rlocation}: {result.stderr}")

    total_elapsed = time.monotonic() - start
    logger.info(
        "TIMING: load_image(%s) took %.2fs total (resolve=%.2fs, docker_load=%.2fs): %s",
        tarball_rlocation.rsplit("/", 1)[-1],
        total_elapsed,
        resolve_elapsed,
        load_elapsed,
        result.stdout.strip(),
    )
