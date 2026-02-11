from __future__ import annotations

from fastmcp.mcp_config import MCPConfig

from adgn.mcp._shared.constants import (
    APPROVAL_POLICY_SERVER_NAME,
    RESOURCES_SERVER_NAME,
    RUNTIME_SERVER_NAME,
    UI_SERVER_NAME,
)
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.approval_policy.engine import (
    PolicyEngine,
    attach_approval_policy_proposer,
    attach_approval_policy_readonly,
)
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.runtime.server import attach_runtime
from adgn.mcp.ui.server import attach_ui

from .images import resolve_runtime_image

# Names of servers that are auto-attached by the runtime container and should not be
# persisted in the agent's MCPConfig. Centralize here for both persistence filtering and
# runtime attach logic.
DEFAULT_AUTO_SERVER_NAMES: tuple[str, ...] = (
    UI_SERVER_NAME,
    APPROVAL_POLICY_SERVER_NAME,
    RUNTIME_SERVER_NAME,
    RESOURCES_SERVER_NAME,  # injected by manager; included for filtering completeness
)


def filter_persistable_servers(cfg: MCPConfig) -> MCPConfig:
    """Return a shallow copy of cfg without the default auto-attached servers.

    Only user-configured servers remain. This avoids persisting ephemeral/runtime
    infrastructure servers like UI, approval policy, runtime exec, or resources.
    """
    return MCPConfig(mcpServers={k: v for k, v in (cfg.mcpServers or {}).items() if k not in DEFAULT_AUTO_SERVER_NAMES})


async def attach_default_servers(comp: Compositor, *, ui_bus, engine: PolicyEngine) -> None:
    """Attach the standard UI + approval policy + runtime exec servers.

    Inlines UI + policy wiring locally.
    """
    # UI server
    await attach_ui(comp, ui_bus)
    # Approval policy servers (engine owns .reader, .proposer, .approver)
    await attach_approval_policy_readonly(comp, engine)
    # Do not mount admin (approver) server into the compositor; UI uses a private client.
    await attach_approval_policy_proposer(comp, engine)
    # Runtime exec server (no host mounts)
    runtime_image = resolve_runtime_image()
    opts = ContainerOptions(image=runtime_image, volumes=None, ephemeral=True)
    await attach_runtime(comp, opts)
