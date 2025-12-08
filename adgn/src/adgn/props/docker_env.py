from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path

import docker
from docker.errors import ImageNotFound
from fastmcp.server import FastMCP

from adgn.mcp._shared.constants import DOCKER_SERVER_NAME, PROPS_DIR, WORKING_DIR
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.props.prop_utils import props_definitions_root

logger = logging.getLogger(__name__)

PROPERTIES_DOCKER_IMAGE = "adgn-llm/properties-critic:latest"


@dataclass(slots=True)
class PropertiesDockerWiring:
    """Wiring for a properties Docker exec server.

    Exposes a factory to build a FastMCP (auth wiring is encapsulated). Callers should
    attach via mcp.attach_inproc(wiring.server_name, wiring.server_factory()).
    """

    server_factory: Callable[[], FastMCP]
    working_dir: Path
    definitions_container_dir: Path | None
    image_name: str

    @property
    def server_name(self) -> str:
        return DOCKER_SERVER_NAME

    def container_path_for_prop_rel(self, rel: str) -> Path:
        if not self.definitions_container_dir:
            raise RuntimeError("Property definitions not mounted in container")
        return self.definitions_container_dir / rel

    async def attach(self, comp: Compositor) -> FastMCP:
        """Mount this wiring on a Compositor (in-proc, no auth)."""
        server = self.server_factory()
        await comp.mount_inproc(self.server_name, server)
        return server


def build_critic_build_hint() -> str:
    # Build hint uses repository docker path (not package resources):
    #   docker build -f docker/llm/properties-critic/Dockerfile -t adgn-llm/properties-critic:latest .
    return f"docker build -f 'docker/llm/properties-critic/Dockerfile' -t {PROPERTIES_DOCKER_IMAGE} ."


def ensure_critic_image() -> None:
    """Ensure the default properties critic image exists; raise with build hint if missing."""

    dclient = docker.from_env()
    try:
        dclient.images.get(PROPERTIES_DOCKER_IMAGE)
    except ImageNotFound as e:
        hint = build_critic_build_hint()
        raise ImageNotFound(f"Docker image not found: {PROPERTIES_DOCKER_IMAGE}.\nBuild it first:\n{hint}") from e


def build_critic_volumes(
    workspace_root: Path,
    *,
    mount_properties: bool,
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
        str(workspace_root.resolve()): {"bind": str(WORKING_DIR), "mode": str(workspace_mode)}
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
    mount_properties: bool,
    extra_volumes: dict[str, dict[str, str]] | None = None,
    ephemeral: bool = True,
    workspace_mode: str = "ro",
    db_url: str | None = None,
    network_mode: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> PropertiesDockerWiring:
    """Return wiring for the properties critic container.

    Ensures the default critic image exists (raises if missing). Sets up standard tool cache
    environment variables to use /tmp.

    Args:
        workspace_root: Path to workspace directory to mount in container.
        mount_properties: Whether to mount property definitions at /props.
        extra_volumes: Additional volumes to mount (merged with standard volumes).
        ephemeral: Whether container should be removed after use.
        workspace_mode: Mount mode for workspace ("ro" or "rw").
        db_url: Database URL to inject as DATABASE_URL environment variable.
        network_mode: Docker network mode (default "none" for isolation).
        extra_env: Additional environment variables to inject (e.g., MCP_SERVER_URL).
    """
    # Ensure image exists; let exceptions propagate with helpful message
    ensure_critic_image()

    volumes, defs_container = build_critic_volumes(
        workspace_root, mount_properties=mount_properties, workspace_mode=workspace_mode, extra_volumes=extra_volumes
    )

    # Provide sane defaults for tool caches and tmp dirs inside the container
    env = {
        "XDG_CACHE_HOME": "/tmp",
        "RUFF_CACHE_DIR": "/tmp/.ruff_cache",
        "MYPY_CACHE_DIR": "/tmp/.mypy_cache",
        "TMPDIR": "/tmp",
        "TMP": "/tmp",
        "TEMP": "/tmp",
        "PYTHONPYCACHEPREFIX": "/tmp/__pycache__",
    }

    # Inject database URL if provided
    if db_url:
        env["DATABASE_URL"] = db_url
        logger.info(f"Setting DATABASE_URL in container environment: {db_url[:50]}...")
    else:
        logger.warning("No db_url provided - container will not have database access")

    # Merge extra environment variables (e.g., MCP_SERVER_URL, MCP_SERVER_TOKEN)
    env.update(extra_env or {})
    if extra_env:
        logger.info(f"Injecting extra environment variables: {list(extra_env.keys())}")

    def _factory() -> FastMCP:
        return make_container_exec_server(
            ContainerOptions(
                image=PROPERTIES_DOCKER_IMAGE,
                working_dir=WORKING_DIR,
                volumes=volumes,
                environment=env,
                describe=True,
                ephemeral=ephemeral,
                network_mode=network_mode or "none",
            )
        )

    return PropertiesDockerWiring(
        server_factory=_factory,
        working_dir=WORKING_DIR,
        definitions_container_dir=defs_container,
        image_name=PROPERTIES_DOCKER_IMAGE,
    )
