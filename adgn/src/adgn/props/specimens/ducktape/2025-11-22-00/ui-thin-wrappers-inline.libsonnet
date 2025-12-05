local I = import '../../lib.libsonnet';

// Merged: thin-wrapper-apply-preset, ui-thin-wrapper-open-method
// Both describe single-use thin wrapper functions that should be inlined

I.issue(
  rationale= |||
    UI components define thin wrapper functions with single or few call sites that add
    no value and should be inlined.

    **Pattern: Unnecessary function abstraction for single-use logic**

    **1. applyPresetFrom (ServersPanel.svelte:185-197)**

    Function finds a preset by ID and applies its fields to component state. Called only
    once (line 257). Simple logic (find + assign) with no transformation.

    Inline the logic in the event handler, or use a Svelte reactive statement
    (`$: if (preset) { ... }`) to automatically apply when preset changes.

    **2. open() wrapper (AgentsSidebar.svelte:136-138)**

    One-line function `open(id)` that only calls `setAgentId(id)`. Called at lines 254,
    255, 257. Other places call `setAgentId()` directly (lines 156, 173, 188, 200),
    creating naming inconsistency.

    Replace `open(a.agent_id)` with `setAgentId(a.agent_id)` at call sites. Remove the
    wrapper function.

    **Problems with thin wrappers:**
    - Indirection without value (no transformation, validation, or side effects)
    - Naming confusion (two names for same action)
    - Maintenance cost (reader must check if wrapper adds behavior)
    - Inconsistent usage (some places call wrapped function directly)
    - False generalization (abstraction for one use case)

    **When wrappers ARE justified:**
    - Multiple operations bundled together
    - Transformation or validation logic
    - Conditional logic before delegation
    - Part of public API / library interface
    - Used from 3+ call sites
    - Testable unit requiring isolation
    - Abstraction hiding implementation details

    **When to inline:**
    - Single call site (or only 2-3 sites)
    - Simple pass-through logic (< 10 lines)
    - No tests needed
    - No reuse planned

    **General principle: Don't prematurely abstract**

    Create abstractions when you have multiple uses, not "in case we need it later."
    Start inline, extract to function when second use appears.

    **Related issue (ServersPanel):**

    The component manually copies fields instead of using types generated from Python
    Pydantic models. TypeScript types can be auto-generated from backend ServerSpec via
    `adgn/scripts/generate_types.py` (commit 7c6cae7ad) to prevent drift between frontend
    and backend type definitions.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [
      [185, 197],  // applyPresetFrom function definition (single caller)
      [257, 257],  // Single call site
    ],
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [
      [136, 138],  // open() wrapper definition
      [254, 257],  // Call sites (inconsistent with direct setAgentId calls elsewhere)
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/components/ServersPanel.svelte'],
    ['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte'],
  ],
)
