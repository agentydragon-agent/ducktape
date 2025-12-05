local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `channels.ts` file (lines 138-174) manually defines TypeScript types for
    WebSocket messages (SessionMessage, McpMessage, ApprovalsMessage, etc.).

    The codebase already has a Pydantic-to-TypeScript code generator at
    `adgn/scripts/generate_frontend_code.py` that uses `json-schema-to-typescript`,
    outputs to `adgn/agent/web/src/generated/types.ts`, and is invoked via
    `npm run codegen`.

    Manual types create duplication, drift risk (Python changes may not reflect in
    TypeScript), and maintenance burden (schema changes require two updates).

    **Fix:** Find or create Python Pydantic models for SessionMessage, McpMessage,
    ApprovalsMessage, PolicyMessage, UiMessage, ErrorMessage (likely in
    `adgn/agent/server/protocol.py`). Add them to `models_to_export` in
    `generate_frontend_code.py`. Run `npm run codegen`. Replace manual types in
    channels.ts with imports from `generated/types.ts`. Keep only envelope type
    manually defined (infrastructure, not data model).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/features/chat/channels.ts': [
      [138, 174], // Manual TypeScript type definitions for all message types
    ],
  },
)
