local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 71-72 in state.py define `ToolItem` with fields `tool: str` and `call_id: str` that
    duplicate fields from `ToolCall` (types.py:20-25: `name: str`, `call_id: str`, `args_json: str | None`).

    This creates parallel type hierarchies: `ToolItem.tool` duplicates `ToolCall.name`, `ToolItem.call_id`
    duplicates `ToolCall.call_id`. Changes to `ToolCall` require manual updates to `ToolItem`. Lost
    information: `ToolCall.args_json` not referenced in `ToolItem`.

    Embed `ToolCall` in `ToolItem` instead of duplicating fields: replace `tool: str` and `call_id: str`
    with `tool_call: ToolCall`. Keep only UI-specific additions (`decision`, `content`, `ts`). Access
    as `item.tool_call.name` instead of `item.tool`.

    This establishes single source of truth (ToolCall is canonical), composition over duplication (ToolItem
    adds UI concerns), and type safety (ToolCall changes propagate automatically).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [71, 72],   // tool and call_id duplicate ToolCall fields
    ],
    'adgn/src/adgn/agent/types.py': [
      [20, 25],   // Canonical ToolCall definition
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/state.py'],
    ['adgn/src/adgn/agent/types.py'],
  ],
)
