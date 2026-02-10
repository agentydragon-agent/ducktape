"""Pre-load OCI image tarballs into the local container runtime.

Used by test fixtures to pre-load Bazel-bundled container images (from
oci_tarball) so Testcontainers doesn't need to pull from Docker Hub.
"""

from __future__ import annotations

import shutil
import subprocess

from opentelemetry import trace

from bazel_util import runfiles

tracer = trace.get_tracer(__name__)


def load_image(tarball_rlocation: str) -> None:
    """Load a Docker image tarball into the container runtime.

    Args:
        tarball_rlocation: Runfiles-relative path to the tarball
            (e.g., "_main/props/testing/fixtures/postgres_16_tarball/tarball.tar").
    """
    tarball_name = tarball_rlocation.rsplit("/", 1)[-1]

    with tracer.start_as_current_span(f"load_image({tarball_name})"):
        with tracer.start_as_current_span("resolve_runfiles_path"):
            tarball_path = runfiles.get_required_path(tarball_rlocation)

        cmd = shutil.which("docker") or shutil.which("podman")
        if not cmd:
            raise RuntimeError("Neither docker nor podman CLI found")

        with tracer.start_as_current_span("docker load"):
            result = subprocess.run([cmd, "load", "-i", str(tarball_path)], check=False, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Failed to load image from {tarball_rlocation}: {result.stderr}")
