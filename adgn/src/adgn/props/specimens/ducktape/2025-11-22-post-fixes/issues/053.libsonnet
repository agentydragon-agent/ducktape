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
  properties=['avoid-thin-wrappers', 'inline-trivial-functions', 'consistent-naming'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [
      [136, 138],  // open() definition
      [254, 257],  // Call sites
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-thin-wrappers"**: functions that only call
    another function with no transformation should be inlined.

    Principle: Indirection must add value
    - Wrapper adds logic → justified
    - Wrapper renames → consider, but usually inline
    - Pure passthrough → always inline

    Related to **"inline-trivial-functions"**: one-line functions with no logic
    should be inlined at call sites unless they serve as abstraction points.

    Why thin wrappers are harmful:

    **Cognitive overhead:**
    - Reader: "What does open() do?"
    - Jumps to definition: "Oh, it just calls setAgentId"
    - Wasted time, no information gained

    **Inconsistency:**
    - Some code calls `open()`, other code calls `setAgentId()`
    - Two names for same action confuses readers
    - Refactoring becomes harder (which name to use?)

    **False abstraction:**
    - Wrapper suggests there might be complexity
    - Actually just renames for no clear reason
    - Creates expectation that doesn't match reality

    When wrappers ARE good:

    **Abstraction with future flexibility:**
    ```typescript
    // Hides persistence implementation
    function saveUserPrefs(prefs: Prefs) {
      localStorage.setItem('prefs', JSON.stringify(prefs))
    }
    // Later can switch to IndexedDB without changing call sites
    ```

    **Multiple coordinated operations:**
    ```typescript
    function openAgent(id: string) {
      setAgentId(id)
      scrollToTop()
      clearDraft()
      trackAnalytics('agent_opened', { id })
    }
    ```

    **Transformation/validation:**
    ```typescript
    function openAgent(id: string | null) {
      if (!id) return
      setAgentId(normalizeAgentId(id))
    }
    ```

    **Consistent interface across implementations:**
    ```typescript
    // Different components implement open() differently
    // But all expose same interface
    ```

    But pure renaming wrappers? Inline them.

    Red flags:
    - Function body is single line calling another function
    - No parameters transformed
    - No validation or error handling
    - Inconsistent usage (some call wrapper, some call wrapped)
    - Names differ but mean same thing (`open` vs `setAgentId`)

    Benefits of inlining:
    - Fewer indirection hops
    - Clearer code (see actual operation)
    - Consistent naming
    - Less to maintain
    - Easier to search/grep
  |||,
)
