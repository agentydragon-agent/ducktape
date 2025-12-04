local I = import '../../lib.libsonnet';

// iss-036: ToolItem duplicates ToolCall structure

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    The `ToolItem` class in `server/state.py` duplicates structural information
    already present in `ToolCall` from `types.py`, creating redundant type definitions
    instead of composing them.

    **Problem: Duplicated tool call structure**

    `ToolItem` (state.py) defines fields that overlap with `ToolCall` (types.py),
    creating two parallel representations of tool call information.

    **Current implementation (state.py, lines 67-75):**
    ```python
    class ToolItem(BaseModel):
        kind: Literal["Tool"] = Field("Tool", description="Item type identifier")
        id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="Unique item identifier")
        ts: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Timestamp when tool was called")
        tool: str = Field(description="Tool name")
        call_id: str = Field(description="Unique call identifier")
        decision: UserApprovalDecision | None = Field(None, description="Approval decision (approve, deny_continue, or deny_abort)")
        content: ToolContent = Field(description="Tool execution content (Exec or Json variant)")
        model_config = ConfigDict(extra="forbid")
    ```

    **Compared to existing ToolCall (types.py, lines 20-25):**
    ```python
    class ToolCall(BaseModel):
        """Tool call information (simple version without discriminator)."""

        name: str = Field(description="Tool name")
        call_id: str = Field(description="Unique call identifier")
        args_json: str | None = Field(None, description="Tool arguments as JSON string")
    ```

    **Overlap:**
    - `ToolItem.tool` duplicates `ToolCall.name`
    - `ToolItem.call_id` duplicates `ToolCall.call_id`

    **Why this is a problem:**

    1. **Duplication**: Same information (`call_id`, tool name) stored in two parallel types
    2. **Fragility**: If `ToolCall` changes, `ToolItem` must be manually updated
    3. **Unclear canonical type**: Which is the "real" tool call representation?
    4. **Lost information**: `ToolCall.args_json` isn't referenced in `ToolItem`
    5. **Type conversion overhead**: Converting between these types requires manual mapping

    **The correct approach:**

    Embed `ToolCall` in `ToolItem` and add only UI-specific enrichment:

    ```python
    from adgn.agent.types import ToolCall

    class ToolItem(BaseModel):
        kind: Literal["Tool"] = Field("Tool", description="Item type identifier")
        id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="Unique item identifier")
        ts: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Timestamp when tool was called")

        # Embed the canonical ToolCall structure
        tool_call: ToolCall = Field(description="Tool call information")

        # UI-specific additions only
        decision: UserApprovalDecision | None = Field(None, description="Approval decision")
        content: ToolContent = Field(description="Tool execution content (Exec or Json variant)")

        model_config = ConfigDict(extra="forbid")
    ```

    **Benefits:**

    1. **Single source of truth**: `ToolCall` is canonical tool call representation
    2. **Composition over duplication**: `ToolItem` adds UI concerns, delegates core info to `ToolCall`
    3. **Type safety**: Changes to `ToolCall` automatically propagate
    4. **Clearer intent**: `ToolItem` is "ToolCall + UI state"
    5. **All data preserved**: `args_json` available via embedded `tool_call`

    **Migration:**

    Update construction sites:
    ```python
    # Old:
    item = ToolItem(
        tool=name,
        call_id=call_id,
        decision=decision,
        content=content,
    )

    # New:
    item = ToolItem(
        tool_call=ToolCall(name=name, call_id=call_id, args_json=args_json),
        decision=decision,
        content=content,
    )
    ```

    Update access sites:
    ```python
    # Old:
    name = item.tool
    call_id = item.call_id

    # New:
    name = item.tool_call.name
    call_id = item.tool_call.call_id
    ```

    **Why duplication happened:**

    `ToolItem` was likely created for UI display without considering existing `ToolCall`.
    The flat structure (`tool`, `call_id` as top-level fields) was convenient for initial
    implementation but created parallel type hierarchies.

    **Design principle: Compose types, don't duplicate them**

    When creating UI-specific types:
    1. Check if domain types already exist (`ToolCall`, `ApprovalRequest`, etc.)
    2. Embed those types and add only UI-specific concerns
    3. Don't flatten embedded structures for "convenience" - composition is clearer

    Example pattern:
    ```python
    # Domain type (canonical)
    class Order(BaseModel):
        id: str
        items: list[Item]
        total: Decimal

    # UI type (enriched)
    class OrderDisplay(BaseModel):
        order: Order  # Embed, don't duplicate
        selected: bool = False  # UI-specific
        expanded: bool = False  # UI-specific
    ```
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
