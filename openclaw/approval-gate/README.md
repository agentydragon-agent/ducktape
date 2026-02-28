# approval-gate OpenClaw plugin

OpenClaw plugin that bridges the [approval gate](../../approval_gate/) MCP proxy.

## What it does

1. **Connects** to the approval gate MCP server as a persistent MCP client.
2. **Discovers** the approval-wrapped tools exposed by the gate and re-registers
   them with OpenClaw so agents can call them.
3. **Injects `session_key`** automatically from the calling agent's session —
   agents never set this field manually.
4. **Subscribes** to `resource://actions/{id}` MCP resource notifications on
   every queued action.
5. **On `ResourceUpdated`**: reads the action state and delivers the result back
   to the agent session via `chat.inject` (local gateway WebSocket).

## Flow

```
Agent calls approval-gate tool
        │
        ▼
Plugin calls approval gate MCP → returns {action_id, approval_url, status: "pending"}
        │
        ▼
Agent receives action_id + URL, shares URL with operator
        │
        ▼ (operator approves in UI)
Approval gate executes backend call, emits ResourceUpdated
        │
        ▼
Plugin receives ResourceUpdated notification
        │  reads resource://actions/{id}
        ▼
Plugin calls chat.inject (local gateway WebSocket, OPENCLAW_GATEWAY_TOKEN)
        │
        ▼
Agent session receives result message
```

## Configuration

Add to your OpenClaw config (or plugin config UI):

```jsonc
// openclaw.config.json5
{
  "plugins": {
    "approval-gate": {
      "approvalGateUrl": "http://approval-gate.approval-gate.svc.cluster.local:8765/mcp",
      "agentApiKey": "<AGENT_API_KEY from the approval gate>",
    },
  },
}
```

## Environment variables

| Variable                  | Description                                                            |
| ------------------------- | ---------------------------------------------------------------------- |
| `OPENCLAW_GATEWAY_TOKEN`  | Gateway auth token for `chat.inject` calls (standard OpenClaw env var) |
| `OPENCLAW_GATEWAY_WS_URL` | Override gateway WebSocket URL (default: `ws://127.0.0.1:18789`)       |

## Installation

The plugin is included in the custom OpenClaw Docker image
(`docker/openclaw/Dockerfile`). The image installs plugin deps at build time.

To install manually:

```bash
cd openclaw/approval-gate
npm install
```

Then add the plugin to your OpenClaw config pointing at the plugin directory.
