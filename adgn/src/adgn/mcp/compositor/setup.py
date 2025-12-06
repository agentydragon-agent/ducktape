from __future__ import annotations

from adgn.mcp._shared.constants import (
    APPROVAL_ADMIN_SERVER_NAME,
    COMPOSITOR_META_SERVER_NAME,
    POLICY_PROPOSER_SERVER_NAME,
    POLICY_READER_SERVER_NAME,
)
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor_meta.server import make_compositor_meta_server
from adgn.mcp.resources.server import make_resources_server

"""Helpers to mount the standard in-proc servers under a Compositor.

- resources
- compositor_meta
- compositor_admin

All mounts are pinned by default to prevent accidental unmounts.
"""


async def mount_standard_inproc_servers(*, compositor: Compositor, policy_engine=None) -> None:
    """Mount standard servers on the given compositor, pinned by default.

    Args:
        compositor: The compositor to mount servers on
        policy_engine: Optional PolicyEngine to mount (reader, proposer, admin servers)

    - Always mounts resources (pinned)
    - Always mounts compositor_meta (pinned)
    - Optionally mounts policy engine servers if policy_engine provided

    Note: compositor_admin is NOT mounted by default - only for agents with policy gateway
    under adgn/agent/server. Standard agents (critic, grader) should only have resources
    and compositor_meta.
    """
    await compositor.mount_inproc(
        "resources", make_resources_server(name="resources", compositor=compositor), pinned=True
    )

    compmeta_server = make_compositor_meta_server(compositor=compositor, name=COMPOSITOR_META_SERVER_NAME)
    await compositor.mount_inproc(COMPOSITOR_META_SERVER_NAME, compmeta_server, pinned=True)

    if policy_engine is not None:
        await compositor.mount_inproc(POLICY_READER_SERVER_NAME, policy_engine.reader)
        await compositor.mount_inproc(POLICY_PROPOSER_SERVER_NAME, policy_engine.policy_proposer)
        await compositor.mount_inproc(APPROVAL_ADMIN_SERVER_NAME, policy_engine.admin)
