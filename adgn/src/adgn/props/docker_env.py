from __future__ import annotations

from collections.abc import Sequence
from contextlib import AsyncExitStack
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adgn.mcp._shared.mounted import Mounted
    from adgn.props.hydration import SnapshotHydrator

import aiodocker
from docker.errors import ImageNotFound

from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp._shared.container_session import BindMount, ContainerOptions
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.props.db.config import DbConnectionConfig
from adgn.props.ids import SnapshotSlug

logger = logging.getLogger(__name__)

PROPERTIES_DOCKER_IMAGE = "adgn-llm/properties-critic:latest"
DOCKER_MOUNT_PREFIX = MCPMountPrefix("docker")  # Mount prefix for properties Docker exec server

# Base directory for all snapshot mounts in containers
SNAPSHOTS_BASE_DIR = Path("/snapshots")


def snapshot_container_path(slug: SnapshotSlug) -> Path:
    """Get the container path for a snapshot's source code.

    Pattern: /snapshots/<slug>

    Agents should NOT know which split (train/valid/test) a snapshot belongs to.
    The split is internal to the training system and should not leak into agent prompts.

    Args:
        slug: Snapshot slug (e.g., "ducktape/2025-11-26-00")

    Returns:
        Container path (e.g., Path("/snapshots/ducktape/2025-11-26-00"))
    """
    return SNAPSHOTS_BASE_DIR / slug


# Docker network name for properties containers
# - Shared with postgres container (container-to-container communication)
# - Allows container→host communication for MCP HTTP mode
# - Non-internal network (needed for host access)
PROPS_NETWORK_NAME = "props_default"


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
        hydrator: SnapshotHydrator,
        db_conn: DbConnectionConfig | None = None,
        extra_binds: Sequence[BindMount] = (),
        workspace_mode: str = "ro",
        network_mode: str = "none",
        extra_env: dict[str, str] | None = None,
        ephemeral: bool = True,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
    ):
        """Initialize properties compositor with Docker configuration.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            hydrator: Snapshot hydrator for automatic snapshot mounting (always required; use SnapshotHydrator.from_env() if not hydrating).
            db_conn: Database connection config (sets PG* env vars).
            extra_binds: Additional bind mounts to mount (default empty tuple).
            workspace_mode: Mount mode for workspace ("ro" or "rw").
            network_mode: Docker network mode (default "none" for isolation).
            extra_env: Additional environment variables to inject.
            ephemeral: Whether container should be removed after use.
            snapshot_slugs: Snapshot slugs to hydrate and mount (if empty, hydrator is not used).

        Note:
            If snapshot_slugs is provided, snapshots will be automatically
            hydrated and mounted at /snapshots/<slug>/ during __aenter__.
            Hydrated contexts are kept alive until __aexit__.
            Creating a hydrator is cheap; hydration only occurs if snapshot_slugs is non-empty.
        """
        super().__init__()
        self._workspace_root = workspace_root
        self._docker_client = docker_client
        self._db_conn = db_conn
        self._extra_binds = extra_binds
        self._workspace_mode = workspace_mode
        self._network_mode = network_mode
        self._extra_env = extra_env
        self._ephemeral = ephemeral
        self._hydrator = hydrator
        self._snapshot_slugs = snapshot_slugs
        self._snapshot_stack: AsyncExitStack | None = None
        self._hydrated_paths: dict[SnapshotSlug, Path] = {}

    async def __aenter__(self):
        """Start compositor and mount Docker runtime server.

        If hydrator and snapshot_slugs are provided, hydrates and mounts snapshots
        at /snapshots/<slug>/ before creating the Docker server.
        """
        await super().__aenter__()  # Mounts resources, compositor_meta

        # Hydrate snapshots if requested
        if self._hydrator and self._snapshot_slugs:
            self._snapshot_stack = AsyncExitStack()
            await self._snapshot_stack.__aenter__()

            extra_snapshot_binds: list[BindMount] = []
            for slug in self._snapshot_slugs:
                # Enter hydration context via stack (stack handles cleanup)
                hydrated = await self._snapshot_stack.enter_async_context(self._hydrator.hydrate(slug))

                # Add bind mount for this snapshot
                container_path = snapshot_container_path(slug)
                extra_snapshot_binds.append(
                    BindMount(host_path=hydrated.content_root.resolve(), container_path=container_path, mode="ro")
                )

                # Store hydrated host path for MCP servers to access
                self._hydrated_paths[slug] = hydrated.content_root.resolve()
                logger.debug(f"Hydrated {slug} → {hydrated.content_root} (mount as {container_path})")

            # Merge snapshot binds with user-provided extra_binds
            self._extra_binds = [*self._extra_binds, *extra_snapshot_binds]
            logger.info(f"Mounted {len(extra_snapshot_binds)} snapshots (read-only)")

        # Ensure Docker image exists and get immutable reference
        image_id = await ensure_critic_image_async(self._docker_client)

        # Mount Docker runtime (shared by all properties compositors)
        docker_server = self._create_docker_server(image_id)
        self.runtime = await self.mount_inproc(DOCKER_MOUNT_PREFIX, docker_server, pinned=True)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up compositor and hydrated snapshots."""
        # Clean up hydrated snapshots (stack handles cleanup in reverse order)
        if self._snapshot_stack is not None:
            await self._snapshot_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._snapshot_stack = None

        # Clean up parent compositor
        return await super().__aexit__(exc_type, exc_val, exc_tb)

    def _create_docker_server(self, image_id: str) -> ContainerExecServer:
        """Create ContainerExecServer with standard properties configuration.

        Args:
            image_id: Immutable Docker image ID (e.g., "sha256:abc123...")
        """
        # Build Docker volume binds
        binds: list[BindMount] = [
            BindMount(host_path=self._workspace_root.resolve(), container_path=WORKING_DIR, mode=self._workspace_mode)
        ]
        if self._extra_binds:
            binds.extend(self._extra_binds)

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
            env.update(self._db_conn.to_env_dict())
            logger.info(
                f"Set database env vars: PGHOST={self._db_conn.host}, "
                f"PGPORT={self._db_conn.port}, PGDATABASE={self._db_conn.database}, PGUSER={self._db_conn.user}"
            )
        else:
            logger.info("No db_conn provided - container will not have database access")
        if self._extra_env:
            env.update(self._extra_env)
            logger.info(f"Injecting extra environment variables: {list(self._extra_env.keys())}")

        return ContainerExecServer(
            self._docker_client,
            ContainerOptions(
                image=image_id,
                working_dir=WORKING_DIR,
                binds=binds,
                environment=env,
                ephemeral=self._ephemeral,
                network_mode=self._network_mode,
            ),
        )

    @property
    def working_dir(self) -> Path:
        """Get the container path where workspace is mounted."""
        return WORKING_DIR


def build_critic_build_hint() -> str:
    # Build hint uses repository docker path (not package resources):
    #   docker build -f docker/llm/properties-critic/Dockerfile -t adgn-llm/properties-critic:latest .
    return f"docker build -f 'docker/llm/properties-critic/Dockerfile' -t {PROPERTIES_DOCKER_IMAGE} ."


async def ensure_critic_image_async(docker_client: aiodocker.Docker) -> str:
    """Ensure the default properties critic image exists; return image ID.

    Args:
        docker_client: Async Docker client

    Returns:
        Image ID (e.g., "sha256:abc123...") - immutable reference to the image

    Raises:
        ImageNotFound: If image does not exist (with build hint)
    """
    try:
        image_info = await docker_client.images.inspect(PROPERTIES_DOCKER_IMAGE)
        image_id: str = image_info["Id"]
        return image_id
    except aiodocker.DockerError as e:
        hint = build_critic_build_hint()
        raise ImageNotFound(f"Docker image not found: {PROPERTIES_DOCKER_IMAGE}.\nBuild it first:\n{hint}") from e


async def get_docker_network_gateway_async(docker_client: aiodocker.Docker, network_name: str) -> str:
    """Get gateway IP for Docker network (async version).

    Args:
        docker_client: Async Docker client
        network_name: Name of the Docker network

    Returns:
        Gateway IP address (e.g., "172.19.0.1")

    Raises:
        RuntimeError: If network does not exist or gateway cannot be determined
    """
    networks = await docker_client.networks.list()
    network = next((n for n in networks if n["Name"] == network_name), None)
    if not network:
        raise RuntimeError(f"Network not found: {network_name}")

    network_obj = await docker_client.networks.get(network["Id"])
    network_info = await network_obj.show()
    ipam_config = network_info.get("IPAM", {}).get("Config", [])
    if not ipam_config:
        raise RuntimeError(f"No IPAM config for network {network_name}")

    gateway = ipam_config[0].get("Gateway")
    if isinstance(gateway, str):
        return gateway
    raise RuntimeError(f"No gateway found for network {network_name}")


def build_critic_binds(
    workspace_root: Path, *, workspace_mode: str = "ro", extra_binds: dict[str, dict[str, str]] | None = None
) -> dict[str, dict[str, str]]:
    """Build standard bind mounts map for properties critic containers.

    - Mounts workspace_root at /workspace with the provided workspace_mode ("ro" or "rw")
    - Allows extra bind mounts to be merged in
    """
    binds: dict[str, dict[str, str]] = {
        str(workspace_root.resolve()): {"bind": str(WORKING_DIR), "mode": str(workspace_mode)}
    }
    if extra_binds:
        binds.update(extra_binds)
    return binds
