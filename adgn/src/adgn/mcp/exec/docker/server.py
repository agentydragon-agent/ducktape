"""
FastMCP server: per-session Docker container exec.

- One container per FastMCP session (created in lifespan; stopped on exit)
- Network mode configurable (default: none); RO/RW bind mounts as provided; working_dir is writable
- Single source of truth for container contents: host-side docker image history (CreatedBy)
"""

from __future__ import annotations

from typing import Any, Final

import aiodocker
from fastmcp.server.context import Context
from fastmcp.tools import FunctionTool

from adgn.mcp._shared.container_session import (
    ContainerOptions,
    make_container_lifespan,
    render_container_result,
    run_ephemeral_container,
    run_session_container,
    session_state_from_ctx,
)
from adgn.mcp._shared.types import ContainerImageHistoryEntry, ContainerImageInfo, ContainerInfo
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.models import BaseExecResult, ExecInput, async_timer

# Resource URI for container info
CONTAINER_INFO_URI: Final[str] = "resource://container.info"


class ContainerExecServer(EnhancedFastMCP):
    """Docker container exec MCP server with typed tool access.

    Subclasses EnhancedFastMCP and adds typed tool attributes for accessing
    tool names. This is the single source of truth - no string literals elsewhere.
    """

    # Tool name constant (for test infrastructure only)
    EXEC_TOOL_NAME = "exec"

    # Tool reference (assigned in __init__ after tool registration)
    exec_tool: FunctionTool

    def __init__(self, opts: ContainerOptions, docker_client: aiodocker.Docker):
        """Create a generic per-session container exec FastMCP server.

        Args:
            opts: Container configuration options
            docker_client: Async Docker client (owned and managed by caller).

        Note:
            The caller must create and manage the docker_client lifecycle. The server
            lifespan uses the client but does not close it - caller remains responsible
            for cleanup (typically via atexit or app shutdown hooks).
        """
        super().__init__(
            "Docker Exec MCP Server",
            instructions=(
                f"Provides access to a Docker container.\n\n"
                f"Image history is available by reading the resource {CONTAINER_INFO_URI}.\n\n"
                f"/tmp is writable and can be used as a scratchpad for notes, intermediate results, "
                f"or organizing your thoughts."
            ),
            lifespan=make_container_lifespan(opts, docker_client),
        )

        # Register container.info resource
        async def container_info_json(ctx: Context) -> dict[str, Any]:
            s = session_state_from_ctx(ctx)
            img_info = await s.docker_client.images.inspect(s.image)
            img_history_raw = await s.docker_client.images.history(s.image)
            img_history = (
                [ContainerImageHistoryEntry.model_validate(entry) for entry in img_history_raw]
                if img_history_raw
                else None
            )

            ci = ContainerInfo(
                image=ContainerImageInfo(
                    name=s.image, id=img_info.get("Id", "unknown"), tags=img_info.get("RepoTags", [s.image])
                ),
                container_id=s.container_id,
                binds=s.binds,
                working_dir=str(s.working_dir),
                network_mode=s.network_mode,
                image_history=img_history,
                ephemeral=s.ephemeral,
            )
            return ci.model_dump(mode="json")

        # Ensure the context annotation is preserved after future-annotations rewriting so
        # FastMCP treats this as a static resource rather than a template.
        container_info_json.__annotations__["ctx"] = Context
        self.resource(
            CONTAINER_INFO_URI,
            mime_type="application/json",
            name="container.info",
            title="Container session metadata",
            description="Docker container details for this session",
        )(container_info_json)

        # Register exec tool - name derived from function name
        async def exec(input: ExecInput, context: Context) -> BaseExecResult:
            """Run a command inside the per-session Docker container.

            The cmd array is passed directly to Docker exec (execve-style, no shell).
            For shell features, the caller wraps in: ["sh", "-c", "command string"]
            """
            async with async_timer() as get_duration_ms:
                s = session_state_from_ctx(context)

                # Pass cmd directly to Docker
                cmd = input.cmd

                if s.ephemeral or opts.ephemeral:
                    stdout_buf, stderr_buf, exit_code, timed_out = await run_ephemeral_container(s, cmd, input)
                else:
                    stdout_buf, stderr_buf, exit_code, timed_out = await run_session_container(s, cmd, input, opts)

                duration_ms = get_duration_ms()
                return render_container_result(stdout_buf, stderr_buf, exit_code, timed_out, duration_ms)

        self.exec_tool = self.flat_model()(exec)
