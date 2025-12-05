local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 29-36 define `parseArgs()` using manual `JSON.parse()` that returns `{}` on error (silent
    failure). Lines 115-121 manually parse approval blocks with `JSON.parse()`, destructuring
    `agent_id`, `tool_call`, `timestamp` without validation.

    Manual JSON parsing loses: (1) validation (accepts any JSON structure), (2) type safety
    (`Record<string, unknown>` doesn't match actual shape), (3) error visibility (parseArgs
    silently returns empty object), (4) schema checking (can't detect missing/extra fields).

    Backend has `ToolCall` Pydantic model (agent/types.py:20-25) with `name`, `call_id`,
    `args_json` fields. Frontend should use Zod schemas generated from Pydantic models via
    `adgn/scripts/generate_types.py` (commit 7c6cae7ad) extended with `json-schema-to-zod`.

    Replace `JSON.parse()` with `PendingApprovalSchema.parse(data)` for runtime validation,
    detailed error messages, and single source of truth (Backend Pydantic → Frontend Zod).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [29, 36],    // parseArgs manual JSON.parse
      [115, 121],  // Manual parsing in fetchApprovals
    ],
  },
)
