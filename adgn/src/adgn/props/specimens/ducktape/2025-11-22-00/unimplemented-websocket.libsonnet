local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Four Svelte components create independent MCP client connections: AgentsSidebar (line 85), ChatPane
    (lines 87-91 and 124-128 - TWO separate clients in same component), MessageComposer (lines 16-20),
    and GlobalApprovalsList (lines 69-71 targeting non-existent /api/mcp endpoint).

    Each client creation involves handshake, auth, session setup, and dedicated connection. This wastes
    resources (multiple WebSocket/HTTP connections, repeated handshakes, memory/file descriptors), violates
    2-level compositor architecture (intended: UI → shared client → compositor; actual: parallel connections),
    creates inconsistent state (separate sessions don't coordinate, race conditions), and duplicates connection
    management (multiple reconnection paths, error handling, token refresh).

    Create global MCP client store/context (e.g., `stores/mcp-client.ts` with `mcpClient` writable), initialize
    once at app startup, and have all components import and use the shared client. This provides single connection,
    consistent state, centralized reconnection, and proper resource subscriptions.

    GlobalApprovalsList: delete component until backend supports it, or expose global approvals through shared compositor.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[85, 85]],
      },
      note: 'Creates MCP client to list agents; should use shared client from store/context',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[87, 91], [124, 128]],
      },
      note: 'Creates TWO separate clients in same component: chat-pane-client (line 87-91) for listing, chat-pane-abort-client (line 124-128) for aborting. Worst offender - not even reusing its own client',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/ChatPane.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[16, 20]],
      },
      note: 'Creates new MCP client per message send operation; should use shared client',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/MessageComposer.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[69, 71]],
      },
      note: 'Creates separate client targeting /api/mcp (non-existent endpoint). Violates 2-level compositor architecture. User suggests: delete component or expose agent-global resource through compositor',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte']],
    },
  ],
)
