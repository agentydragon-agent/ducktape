"""OCI container image utilities: auth, digest reading, image loading."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from opentelemetry import trace

from util.bazel import runfiles

# ---------------------------------------------------------------------------
# Docker auth
# ---------------------------------------------------------------------------


def docker_auth_config(registry: str, username: str, password: str) -> dict[str, object]:
    """Build a Docker auth config dict for a single registry."""
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"auths": {registry: {"auth": auth}}}


def write_docker_auth(registry: str, username: str, password: str, *, overwrite: bool = False) -> None:
    """Write ~/.docker/config.json with registry credentials."""
    docker_dir = Path.home() / ".docker"
    docker_dir.mkdir(parents=True, exist_ok=True)
    config_path = docker_dir / "config.json"
    if config_path.exists() and not overwrite:
        raise FileExistsError(f"{config_path} already exists (pass overwrite=True to replace)")
    config_path.write_text(json.dumps(docker_auth_config(registry, username, password)))


# ---------------------------------------------------------------------------
# OCI layout
# ---------------------------------------------------------------------------


def read_oci_layout_digest(image_dir: Path) -> str:
    """Read the image manifest digest from an OCI layout's index.json."""
    index = json.loads((image_dir / "index.json").read_text())
    digest: str = index["manifests"][0]["digest"]
    return digest


# ---------------------------------------------------------------------------
# Image loading via crane
# ---------------------------------------------------------------------------

tracer = trace.get_tracer(__name__)


def load_oci_image(info_rlocation: str) -> str:
    """Load an OCI image into the container runtime via crane.

    Args:
        info_rlocation: Runfiles path to the .json file produced by the
            oci_tarball macro's _oci_image_info rule (e.g.
            "_main/third_party/containers/postgres_18.json").

    Returns:
        The repo tag the image was loaded as.
    """
    info_path = runfiles.get_required_path(info_rlocation)
    info = json.loads(info_path.read_text())
    oci_layout_rlocation: str = info["oci_layout"]
    tag: str = info["tag"]

    with tracer.start_as_current_span(f"load_oci_image({tag})"):
        index_path = runfiles.get_required_path(f"{oci_layout_rlocation}/index.json")
        oci_layout = index_path.parent
        _crane_push_to_daemon(oci_layout, tag)

    return tag


def _crane_push_to_daemon(oci_layout: Path, tag: str) -> None:
    crane = runfiles.get_required_path("crane/crane")
    result = subprocess.run(
        [str(crane), "push", str(oci_layout), f"daemon://{tag}"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"crane push daemon://{tag} failed: {result.stderr}")
