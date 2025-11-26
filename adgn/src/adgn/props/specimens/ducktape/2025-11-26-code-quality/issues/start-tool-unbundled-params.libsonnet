local I = import '../../specimens/lib.libsonnet';

// iss-016: start_tool takes unbundled params instead of ToolCall object

I.issueOneOccurrence(
  rationale= |||
    The `start_tool` function takes individual `tool`, `call_id` parameters and then
    fabricates a `ToolCall` object internally. It should take a `ToolCall` directly,
    propagating the existing bundling from the caller.

    **Current implementation (state.py:104-107):**
    ```python
    def start_tool(state: UiState, *, tool: str, call_id: str, cmd: str | None, args: Any | None) -> UiState:
        content: ToolContent = ExecContent(cmd=cmd, args=args) if cmd is not None else JsonContent(args=args)
        tool_call = ToolCall(name=tool, call_id=call_id, args_json=None)
        return append_item(state, ToolItem(tool_call=tool_call, content=content))
    ```

    **Problems:**
    1. **Loses existing structure**: Callers likely already have a `ToolCall` object
    2. **Fabricates args_json=None**: Hardcodes `args_json=None` instead of using actual value
    3. **Breaks bundling**: Unbundles tool+call_id, then re-bundles them
    4. **More parameters**: 4 keyword params instead of 2
    5. **Tight coupling**: Function knows internal structure of ToolCall

    **Likely caller pattern:**
    ```python
    # Caller probably has:
    tool_call = ToolCall(name="foo", call_id="123", args_json="{...}")

    # But must unbundle it:
    start_tool(state, tool=tool_call.name, call_id=tool_call.call_id, cmd=..., args=...)

    # Function then re-bundles (losing args_json):
    tool_call = ToolCall(name=tool, call_id=call_id, args_json=None)
    ```

    **Correct approach:**
    ```python
    def start_tool(state: UiState, *, tool_call: ToolCall, cmd: str | None, args: Any | None) -> UiState:
        content: ToolContent = ExecContent(cmd=cmd, args=args) if cmd is not None else JsonContent(args=args)
        return append_item(state, ToolItem(tool_call=tool_call, content=content))
    ```

    Or if cmd/args should also be bundled in a content object:
    ```python
    def start_tool(state: UiState, *, tool_call: ToolCall, content: ToolContent) -> UiState:
        return append_item(state, ToolItem(tool_call=tool_call, content=content))
    ```

    **Benefits:**
    1. Respects existing bundling (ToolCall is already a coherent unit)
    2. Preserves all ToolCall fields (including args_json)
    3. Fewer parameters (2 instead of 4)
    4. Caller doesn't need to unbundle
    5. Function doesn't need to know ToolCall internals
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [104, 107],  // start_tool with unbundled parameters
    ],
  },
)
