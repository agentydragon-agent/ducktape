local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    AgentRuntime.close() (lines 40-44) executes two close operations sequentially without
    error handling: await self.runtime.close() followed by await self.running.close(). If
    the first call raises, the second never executes, leaving the entire MCP infrastructure
    alive. RunningInfrastructure.close() is responsible for critical cleanup: detaching
    sidecars, closing the AsyncExitStack containing the compositor client, all mounted MCP
    servers, policy reader/approver servers, approval engine infrastructure, and notification
    handlers. LocalAgentRuntime.close()'s docstring explicitly states it "Does NOT close the
    underlying RunningInfrastructure", making the sequential pattern particularly problematic.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [[40, 44]],
  },
)
