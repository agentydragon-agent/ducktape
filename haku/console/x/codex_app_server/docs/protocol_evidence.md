# Codex app-server protocol evidence

This package is pinned to the Codex version already installed in the `agent-workspace` image:
`@openai/codex@0.144.1` (`cluster/k8s/agents/agent-sandbox/workspace-image/Dockerfile`). The npm
package declares the six platform packages at that same version and launches their native binary.
The corresponding authoritative source is OpenAI's tag `rust-v0.144.1`, peeled commit
`44918ea10c0f99151c6710411b4322c2f5c96bea`.

The claims implemented here were checked against that tag, in these vendored/generated artifacts:

- `codex-rs/app-server/README.md`: newline-delimited stdio transport, omitted `jsonrpc` header,
  initialization handshake, and thread/turn/item lifecycle.
- `codex-rs/app-server-protocol/schema/typescript/ClientRequest.ts` and
  `ClientNotification.ts`: `initialize`, `thread/start`, `turn/start`, and `initialized` envelopes.
- `schema/typescript/v2/ThreadItem.ts`: the complete item union and terminal payload fields.
- `AgentMessageDeltaNotification.ts`, `ReasoningSummaryTextDeltaNotification.ts`,
  `CommandExecutionOutputDeltaNotification.ts`, `ItemStartedNotification.ts`, and
  `ItemCompletedNotification.ts`: stable item IDs on lifecycle and delta notifications.
- `CommandExecutionStatus.ts`, `McpToolCallStatus.ts`, and `TurnStatus.ts`: the status enums mapped by
  the adapter.
- `McpToolCallResult.ts`: MCP `content`, `structuredContent`, and `_meta` result payloads.
- `codex-rs/tui/src/thread_transcript.rs`: completed reasoning summary parts render joined with two
  newlines, matching `item/reasoning/summaryPartAdded` in the live TUI.

`codex app-server generate-ts` and `generate-json-schema` produce version-specific schemas from the
installed binary. Use those commands when the image pin moves; do not assume a newer online schema
still describes 0.144.1.

## Projection boundary

The adapter consumes server notifications and produces the existing types from
`haku.console.x.conversation_events`. It does not define a new event vocabulary and is not imported
by `frame_projection.py` or any production runtime.

Supported now:

- agent-message start, text deltas, and completion (completion text contributes only an
  undelivered suffix);
- reasoning-summary start, deltas, and completion as `disclosure=summary`;
- command execution start/output/completion, including exit status and duration in `structured`;
- MCP tool call start/completion, rendered result content, and native structured payload;
- completed/interrupted/failed turn outcomes.

Deliberately ignored because the conversation schema assigns them elsewhere or rejects the detail:
thread status, token usage, `turn/started`, MCP progress narration, and server-request resolution.
User-message items are also ignored: prompts are console-authored before the backend claims them.

Currently counted as `unprojected`, preserving fail-soft observability: file changes, web search,
plans, raw reasoning text, dynamic/collaboration tool items, and any future method or item type.
They remain in the native frame log for a later explicitly reviewed mapping.

The committed `testdata/real_text_command.sanitized.jsonl` is the reviewed real capture supplied
with issue #4431's staging notes (`.openclaw/codex-trace-4431/README.md`). It observed two bounded
turns on 2026-08-19 UTC: text deltas/completion, then reasoning item completion, command execution
start/completion, and a second text answer. `testdata/schema_derived_turn.synthetic.jsonl` remains
synthetic and exists only to cover schema-supported MCP, output-delta, and future-item cases that
the safe capture did not exercise.
