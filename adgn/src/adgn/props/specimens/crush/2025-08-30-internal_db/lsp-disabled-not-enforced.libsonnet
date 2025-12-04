local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    LSPConfig.Disabled flag doesn't prevent LSP initialization - disabled LSP servers still start and run.

    initLSPClients (internal/app/lsp.go:14-18) iterates over all configured LSPs and starts every one without checking the Disabled flag:

    for name, clientConfig := range app.config.LSP {
        go app.createAndStartLSPClient(ctx, name, clientConfig.Command, clientConfig.Args...)
    }

    Result: Disabled LSP servers still spawn processes, connect, initialize, and run workspace watchers.

    The Disabled field is only checked for:
    - TUI display (internal/tui/components/lsp/lsp.go:63) to show "disabled" label
    - Prompt building (internal/llm/prompt/coder.go:114) to omit LSP info from system prompt

    But the actual LSP process runs regardless, consuming resources and file descriptors.

    Compare to MCP initialization (internal/llm/agent/mcp_manager.go:78-80), which correctly checks the flag:

    if mc.Disabled {
        updateMCPState(name, MCPStateDisabled, nil, nil, 0)
        return
    }

    Fix: Add early-return check in initLSPClients loop before calling createAndStartLSPClient.
  |||,
  filesToRanges={
    'internal/app/lsp.go': [[14, 18]],
    'internal/tui/components/lsp/lsp.go': [[63, 63]],
    'internal/llm/prompt/coder.go': [[114, 114]],
    'internal/llm/agent/mcp_manager.go': [[78, 80]],
  },
  expect_caught_from=[['internal/app/lsp.go']],
)
