from __future__ import annotations

from dataclasses import dataclass
from importlib import resources as ilres
from pathlib import Path

import docker

from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.properties.prop_utils import properties_root

PROPERTIES_DOCKER_IMAGE = "adgn-llm/properties-critic:latest"
SERVER_NAME = "docker"
WORKING_DIR: Path = Path("/workspace")
PROPS_DIR = "/props"


@dataclass(slots=True)
class PropertiesDockerWiring:
    _server_name: str
    server_spec: ServerSlotSpec
    _working_dir: Path
    definitions_container_dir: str | None

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def working_dir(self) -> Path:
        return self._working_dir

    def container_path_for_prop_rel(self, rel: str) -> str:
        if self.definitions_container_dir is None:
            raise RuntimeError("Property definitions are not mounted in the container")
        rel = rel.lstrip("/")
        return f"{self.definitions_container_dir}/{rel}"

    def describe_markdown(self) -> str:
        if self.definitions_container_dir:
            props = f"defs mounted RO at {self.definitions_container_dir}"
        else:
            props = "defs not mounted"
        return f"Docker env: image={PROPERTIES_DOCKER_IMAGE}, workdir={self.working_dir}, {props}"


def build_critic_build_hint() -> str:
    dockerfile_trav = ilres.files("adgn_llm").joinpath("docker/critic.Dockerfile")
    dockerfile_path = str(dockerfile_trav)
    context_dir = str(dockerfile_trav.parent)
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


def properties_docker_spec(
    workspace_root: Path,
    *,
    mount_properties: bool = True,
    extra_volumes: dict[str, dict] | None = None,
) -> PropertiesDockerWiring:
    """Return wiring for the properties critic container.

    Ensures the default critic image exists (raises if missing). Always mounts
    `workspace_root` read-only at /workspace. Optionally mounts property
    definitions at /props.
    """
    # Ensure image exists; let exceptions propagate with helpful message
    ensure_critic_image()

    volumes: dict[str, dict] = {str(Path(workspace_root).resolve()): {"bind": str(WORKING_DIR), "mode": "ro"}}

    defs_dir: Path | None = None
    defs_container: str | None = None
    if mount_properties:
        defs_dir = (properties_root() / "definitions").resolve()
        volumes[str(defs_dir)] = {"bind": PROPS_DIR, "mode": "ro"}
        defs_container = PROPS_DIR

    if extra_volumes:
        volumes.update(extra_volumes)

    server = make_container_exec_mcp(
        image=PROPERTIES_DOCKER_IMAGE,
        working_dir=str(WORKING_DIR),
        volumes=volumes,
        describe=True,
    )
    spec = make_inproc_slot_spec(server)
    return PropertiesDockerWiring(
        _server_name=SERVER_NAME,
        server_spec=spec,
        _working_dir=WORKING_DIR,
        definitions_container_dir=defs_container,
    )
