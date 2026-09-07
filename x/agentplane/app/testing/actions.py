"""Explicit fixture injection for the original app ActionRequest vertical slice."""

from x.agentplane.action_service.catalog import ActionCatalog, ActionDefinition, ActionGroup, McpExecutorBinding
from x.agentplane.app.actions import ActionState, ExecutionRequest, ExecutionResult


class EchoExecutor:
    CAPABILITY = "agentplane:v0.echo"

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(state=ActionState.SUCCEEDED, result={"echo": request.arguments})


def echo_catalog() -> ActionCatalog:
    return ActionCatalog(groups={"agentplane": ActionGroup(
        title="Test fixture", description="Explicit test-only injection; no runtime MCP binding",
        executor=McpExecutorBinding(description="Test injection"),
        actions={"echo": ActionDefinition(description="Echo fixture")},
    )})
