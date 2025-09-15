from __future__ import annotations


from dataclasses import dataclass
from importlib import resources as ilres
from pathlib import Path

import docker

from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.properties.prop_utils import props_definitions_root

PROPERTIES_DOCKER_IMAGE = "adgn-llm/properties-critic:latest"
SERVER_NAME = "docker"
WORKING_DIR: Path = Path("/workspace")
PROPS_DIR = Path("/props")
# Shared startup command for long-lived containers


@dataclass(slots=True)
class PropertiesDockerWiring:
    server_spec: ServerSlotSpec
    working_dir: Path
    definitions_container_dir: Path | None
    image_name: str

    @property
    def server_name(self) -> str:
        return SERVER_NAME

    def container_path_for_prop_rel(self, rel: str) -> Path:
        if not self.definitions_container_dir:
            raise RuntimeError("Property definitions not mounted in container")
        return self.definitions_container_dir / rel


def build_critic_build_hint() -> str:
    dockerfile_trav = ilres.files("adgn_llm").joinpath("docker/critic.Dockerfile")
    # Convert Traversable to a real filesystem path for mypy/typeshed compatibility
    dockerfile_path = str(dockerfile_trav)
    context_dir = str(Path(dockerfile_path).parent)
    return f"docker build -f '{dockerfile_path}' -t {PROPERTIES_DOCKER_IMAGE} '{context_dir}'"


def ensure_critic_image() -> None:
    """Ensure the default properties critic image exists; raise with build hint if missing."""
    dclient = docker.from_env()
    try:
        dclient.images.get(PROPERTIES_DOCKER_IMAGE)
    except docker.errors.ImageNotFound as e:
        hint = build_critic_build_hint()
        raise docker.errors.ImageNotFound(
            f"Docker image not found: {PROPERTIES_DOCKER_IMAGE}.\nBuild it first:\n{hint}"
        ) from e


def build_critic_volumes(
    workspace_root: Path,
    *,
    mount_properties: bool = True,
    workspace_mode: str = "ro",
    extra_volumes: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, dict[str, str]], Path | None]:
    """Build standard volumes map for properties critic containers.

    - Mounts workspace_root at /workspace with the provided workspace_mode ("ro" or "rw")
    - Optionally mounts property definitions at /props (always read-only)
    - Allows extra volumes to be merged in
    Returns (volumes, definitions_container_dir|None)
    """
    volumes: dict[str, dict[str, str]] = {
        str(workspace_root.resolve()): {
            "bind": str(WORKING_DIR),
            "mode": str(workspace_mode),
        }
    }
    if extra_volumes:
        volumes.update(extra_volumes)
    if not mount_properties:
        return volumes, None
    defs_dir = props_definitions_root().resolve()
    volumes[str(defs_dir)] = {"bind": str(PROPS_DIR), "mode": "ro"}
    return volumes, PROPS_DIR


def properties_docker_spec(
    workspace_root: Path,
    *,
    mount_properties: bool = True,
    extra_volumes: dict[str, dict[str, str]] | None = None,
) -> PropertiesDockerWiring:
    """Return wiring for the properties critic container.

    Ensures the default critic image exists (raises if missing). Always mounts
    `workspace_root` read-only at /workspace. Optionally mounts property
    definitions at /props.
    """
    # Ensure image exists; let exceptions propagate with helpful message
    ensure_critic_image()

    volumes, defs_container = build_critic_volumes(
        workspace_root,
        mount_properties=mount_properties,
        workspace_mode="ro",
        extra_volumes=extra_volumes,
    )

    from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp

    server = make_container_exec_mcp(
        image=PROPERTIES_DOCKER_IMAGE,
        working_dir=str(WORKING_DIR),
        volumes=volumes,
        describe=True,
    )
    return PropertiesDockerWiring(
        server_spec=make_inproc_slot_spec(server),
        working_dir=WORKING_DIR,
        definitions_container_dir=defs_container,
        image_name=PROPERTIES_DOCKER_IMAGE,
    )
