from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adgn.mcp._shared.mounted import Mounted

import aiodocker
import docker
from docker.errors import ImageNotFound

from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.props.db.config import DbConnectionConfig
from adgn.props.prop_utils import props_definitions_root

logger = logging.getLogger(__name__)

# Container filesystem path where property definitions are mounted
PROPS_DIR: Path = Path("/props")

PROPERTIES_DOCKER_IMAGE = "adgn-llm/properties-critic:latest"
DOCKER_MOUNT_PREFIX = "docker"  # Mount prefix for properties Docker exec server

# Docker network name for properties containers (allows container→host communication while blocking internet)
PROPS_NETWORK_NAME = "props-network"


def get_docker_network_gateway(network_name: str) -> str:
    """Get the gateway IP for a Docker network.

    Args:
        network_name: Name of the Docker network

    Returns:
        Gateway IP address (e.g., "172.19.0.1")

    Raises:
        docker.errors.NotFound: If network does not exist
        RuntimeError: If gateway cannot be determined from network config
    """
    client = docker.from_env()
    network = client.networks.get(network_name)
    ipam_config = network.attrs.get("IPAM", {}).get("Config", [])
    if not ipam_config:
        raise RuntimeError(f"No IPAM config found for network {network_name}")
    gateway = ipam_config[0].get("Gateway")
    if isinstance(gateway, str):
        return gateway
    raise RuntimeError(f"No gateway found for network {network_name}")


class PropertiesDockerCompositor(Compositor):
    """Base compositor for properties tasks - handles Docker runtime mounting.

    This intermediate class sits between Compositor and task-specific compositors (Critic, Grader, Lint).
    It centralizes Docker container setup and mounting logic that all properties tasks share.

    Hierarchy:
        Compositor (base) → mounts resources, compositor_meta
        PropertiesDockerCompositor (this class) → mounts runtime (Docker exec server)
        Task compositors (Critic/Grader/Lint) → mount task-specific servers

    Attributes:
        runtime: Mounted Docker exec server (populated in __aenter__)
    """

    runtime: Mounted[ContainerExecServer]

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        *,
        mount_properties: bool = True,
        db_conn: DbConnectionConfig | None = None,
        extra_binds: dict[str, dict[str, str]] | None = None,
        workspace_mode: str = "ro",
        network_mode: str = "none",
        extra_env: dict[str, str] | None = None,
        ephemeral: bool = True,
    ):
        """Initialize properties compositor with Docker configuration.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            mount_properties: Whether to mount property definitions at /props.
            db_conn: Database connection config (sets PG* env vars).
            extra_binds: Additional bind mounts to mount.
            workspace_mode: Mount mode for workspace ("ro" or "rw").
            network_mode: Docker network mode (default "none" for isolation).
            extra_env: Additional environment variables to inject.
            ephemeral: Whether container should be removed after use.
        """
        super().__init__()
        self._workspace_root = workspace_root
        self._docker_client = docker_client
        self._mount_properties = mount_properties
        self._db_conn = db_conn
        self._extra_binds = extra_binds
        self._workspace_mode = workspace_mode
        self._network_mode = network_mode
        self._extra_env = extra_env
        self._ephemeral = ephemeral

    async def __aenter__(self):
        """Start compositor and mount Docker runtime server."""
        await super().__aenter__()  # Mounts resources, compositor_meta

        # Ensure Docker image exists before mounting
        ensure_critic_image()

        # Mount Docker runtime (shared by all properties compositors)
        docker_server = self._create_docker_server()
        self.runtime = await self.mount_inproc(DOCKER_MOUNT_PREFIX, docker_server, pinned=True)

        return self

    def _create_docker_server(self) -> ContainerExecServer:
        """Create ContainerExecServer with standard properties configuration."""
        # Build Docker volume binds
        binds: dict[str, dict[str, str]] = {
            str(self._workspace_root.resolve()): {"bind": str(WORKING_DIR), "mode": self._workspace_mode}
        }
        if self._extra_binds:
            binds.update(self._extra_binds)
        if self._mount_properties:
            defs_dir = props_definitions_root().resolve()
            binds[str(defs_dir)] = {"bind": str(PROPS_DIR), "mode": "ro"}

        # Build container environment variables
        env = {
            "XDG_CACHE_HOME": "/tmp",
            "RUFF_CACHE_DIR": "/tmp/.ruff_cache",
            "MYPY_CACHE_DIR": "/tmp/.mypy_cache",
            "TMPDIR": "/tmp",
            "TMP": "/tmp",
            "TEMP": "/tmp",
            "PYTHONPYCACHEPREFIX": "/tmp/__pycache__",
        }
        if self._db_conn:
            env["PGHOST"] = self._db_conn.host
            env["PGPORT"] = str(self._db_conn.port)
            env["PGDATABASE"] = self._db_conn.database
            env["PGUSER"] = self._db_conn.user
            env["PGPASSWORD"] = self._db_conn.password
            logger.info(
                f"Set database env vars: PGHOST={self._db_conn.host}, "
                f"PGPORT={self._db_conn.port}, PGDATABASE={self._db_conn.database}, PGUSER={self._db_conn.user}"
            )
        else:
            logger.warning("No db_conn provided - container will not have database access")
        if self._extra_env:
            env.update(self._extra_env)
            logger.info(f"Injecting extra environment variables: {list(self._extra_env.keys())}")

        return ContainerExecServer(
            ContainerOptions(
                image=PROPERTIES_DOCKER_IMAGE,
                working_dir=WORKING_DIR,
                binds=binds,
                environment=env,
                ephemeral=self._ephemeral,
                network_mode=self._network_mode,
            ),
            self._docker_client,
        )

    def container_path_for_prop_rel(self, rel: str) -> Path:
        """Get container path for a property definition relative path.

        Args:
            rel: Relative path within property definitions

        Returns:
            Absolute container path (/props/...)

        Raises:
            RuntimeError: If property definitions not mounted in container
        """
        if not self._mount_properties:
            raise RuntimeError("Property definitions not mounted in container")
        return PROPS_DIR / rel

    @property
    def working_dir(self) -> Path:
        """Get the container path where workspace is mounted."""
        return WORKING_DIR

    @property
    def definitions_container_dir(self) -> Path | None:
        """Get the container path where property definitions are mounted (or None if not mounted)."""
        return PROPS_DIR if self._mount_properties else None


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


def build_critic_binds(
    workspace_root: Path,
    *,
    mount_properties: bool,
    workspace_mode: str = "ro",
    extra_binds: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, dict[str, str]], Path | None]:
    """Build standard bind mounts map for properties critic containers.

    - Mounts workspace_root at /workspace with the provided workspace_mode ("ro" or "rw")
    - Optionally mounts property definitions at /props (always read-only)
    - Allows extra bind mounts to be merged in
    Returns (binds, definitions_container_dir|None)
    """
    binds: dict[str, dict[str, str]] = {
        str(workspace_root.resolve()): {"bind": str(WORKING_DIR), "mode": str(workspace_mode)}
    }
    if extra_binds:
        binds.update(extra_binds)
    if not mount_properties:
        return binds, None
    defs_dir = props_definitions_root().resolve()
    binds[str(defs_dir)] = {"bind": str(PROPS_DIR), "mode": "ro"}
    return binds, PROPS_DIR
