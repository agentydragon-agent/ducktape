from __future__ import annotations

from fastmcp.mcp_config import MCPConfig

from adgn.mcp._shared.constants import (
    APPROVAL_ADMIN_MOUNT_PREFIX,
    POLICY_PROPOSER_MOUNT_PREFIX,
    POLICY_READER_MOUNT_PREFIX,
    RESOURCES_MOUNT_PREFIX,
    RUNTIME_MOUNT_PREFIX,
    UI_MOUNT_PREFIX,
)

# Names of servers that are auto-attached by the runtime container and should not be
# persisted in the agent's MCPConfig. Centralize here for both persistence filtering and
# runtime attach logic.
DEFAULT_AUTO_SERVER_NAMES: tuple[str, ...] = (
    UI_MOUNT_PREFIX,
    POLICY_READER_MOUNT_PREFIX,
    POLICY_PROPOSER_MOUNT_PREFIX,
    APPROVAL_ADMIN_MOUNT_PREFIX,
    RUNTIME_MOUNT_PREFIX,
    RESOURCES_MOUNT_PREFIX,  # injected by manager; included for filtering completeness
)


# TODO: Consider eliminating this filtering layer entirely - ideally persistence should only
# receive user-configured servers, not have to filter out infrastructure servers after the fact.
def filter_persistable_servers(cfg: MCPConfig) -> MCPConfig:
    """Return a shallow copy of cfg without the default auto-attached servers.

    Only user-configured servers remain. This avoids persisting ephemeral/runtime
    infrastructure servers like UI, approval policy, runtime exec, or resources.
    """
    return MCPConfig(mcpServers={k: v for k, v in (cfg.mcpServers or {}).items() if k not in DEFAULT_AUTO_SERVER_NAMES})
