local I = import '../../specimens/lib.libsonnet';

// iss-053: AgentsSidebar open() thin wrapper should inline setAgentId() calls

I.issueOneOccurrence(
  rationale= |||
    The `AgentsSidebar` component defines a one-line wrapper function `open(id)`
    that only calls `setAgentId(id)`. This adds no value and should be inlined at
    call sites.

    **Problem: Unnecessary indirection**

    **Definition (line 136-138):**
    Function `open(id)` wraps `setAgentId(id)` with no additional logic.

    **Call sites (lines 254, 255, 257):**
    Three click/keyboard handlers call `open(a.agent_id)`.

    **Why this is problematic:**

    1. **Indirection without value**: No transformation, validation, or side effects
    2. **Naming confusion**: `open` vs `setAgentId` - two names for same action
    3. **Maintenance cost**: Reader must check if wrapper adds behavior
    4. **Inconsistent usage**: Other places call `setAgentId()` directly (lines 156, 173, 188, 200)

    **The correct approach: Inline at call sites**

    Replace `open(a.agent_id)` with `setAgentId(a.agent_id)` at lines 254, 255, 257.
    Remove the `open()` function definition.

    **Why inline is better:**

    - **Direct**: Reader sees actual action without checking wrapper
    - **Consistent**: All code uses same function name
    - **Less code**: Three fewer lines
    - **Clearer intent**: `setAgentId` is more descriptive than `open`

    **When wrappers ARE justified:**

    - **Multiple operations**: `open(id) { setAgentId(id); logAnalytics(); scrollToTop(); }`
    - **Transformation**: `open(id) { setAgentId(normalizeId(id)) }`
    - **Conditional logic**: `open(id) { if (!loading) setAgentId(id) }`
    - **Abstraction**: Hiding implementation details for future flexibility

    None of these apply here - it's a pure pass-through.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [
      [136, 138],  // open() definition
      [254, 257],  // Call sites
    ],
  },
)
