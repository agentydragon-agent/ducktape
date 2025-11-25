local I = import '../../specimens/lib.libsonnet';

// iss-043: applyPresetFrom thin wrapper should inline at call site

I.issueOneOccurrence(
  rationale= |||
    The `applyPresetFrom` function in `ServersPanel.svelte` is a thin wrapper that
    finds a preset by ID and applies its fields. This could be inlined at the single
    call site, eliminating the unnecessary indirection.

    **Problem: Thin wrapper function with single caller**

    The `applyPresetFrom` function (lines 185-197) finds a preset by ID and copies its
    fields to component state. It's called only once (line 257).

    **Why this is a thin wrapper:**

    Single caller, simple logic (find + assign), no transformation. Unnecessary
    abstraction for one use.

    **The correct approach:**

    Inline the logic in the event handler, or use a Svelte reactive statement
    (`$: if (preset) { ... }`) to automatically apply when `preset` changes.

    Benefits: less indirection, clearer flow, no false generalization.

    **User also mentioned: "should use schema copying from Python"**

    The user suggests that instead of manually copying fields from `McpPreset` to
    component state, the component should use types generated from Python Pydantic
    models (similar to issue 042).

    **Related: Manual field copying should use generated types**

    The component manually copies fields from `McpPreset` to state (lines showing
    `stdioCommand = p.defaults.stdio.command`, etc.). This duplicates backend Pydantic
    structure.

    Better: Use TypeScript types auto-generated from backend `ServerSpec` Pydantic model
    via the existing `adgn/scripts/generate_types.py` script (commit 7c6cae7ad). This
    ensures frontend and backend types match exactly and prevents drift.

    **When thin wrappers are OK:**

    - Used from multiple places (3+ call sites)
    - Encapsulates complex logic (not just find + assign)
    - Part of public API / library
    - Testable unit (needs isolation)
    - Enables dependency injection

    **When to inline:**

    - Single call site
    - Simple logic (< 10 lines)
    - No tests needed
    - No reuse planned

    **General principle: Don't prematurely abstract**

    Create abstractions when you have multiple uses, not "in case we need it later."
    Start inline, extract to function when second use appears.
  |||,
  properties=['avoid-thin-wrappers', 'inline-single-use', 'type-safe-apis'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ServersPanel.svelte': [
      [185, 197],  // applyPresetFrom function definition
      [257, 257],  // Single call site
    ],
  },
  gap_note= |||
    This finding illustrates **"inline-single-use"**: functions used only once
    should be inlined unless they encapsulate complex logic or are part of a
    public API.

    Related to **"avoid-thin-wrappers"**: don't create function abstractions
    for single-use cases. Extract when second use appears.

    Rule of thumb: YAGNI (You Aren't Gonna Need It)
    - Don't create abstractions "in case we need them later"
    - Inline first, abstract when you have 2-3 uses
    - Extract when logic becomes complex (>15 lines, multiple concerns)

    When to keep single-use functions:
    - Complex logic that benefits from naming
    - Needs unit testing in isolation
    - Part of hook/lifecycle (e.g., Svelte reactive)
    - Callback passed to framework
    - Public API / library export

    When to inline:
    - Simple transformation (< 10 lines)
    - Only one caller
    - Logic is clear inline
    - No testing needed

    Svelte-specific patterns:

    **Inline event handler:**
    ```svelte
    <button on:click={() => { foo = bar; baz() }}>
    ```

    **Reactive statement (for complex derived values):**
    ```svelte
    $: derivedValue = computeSomething(props)
    ```

    **Named function (for reuse or clarity):**
    ```svelte
    <script>
      function handleSubmit() { /* ... */ }
    </script>
    <form on:submit|preventDefault={handleSubmit}>
    ```

    Related to **"type-safe-APIs"** (user's note about schema copying):
    When backend has Pydantic models, generate TypeScript types instead of
    manually duplicating structure. This prevents drift and enables type checking
    across the stack.

    Tools for Pydantic → TypeScript:
    - **Existing script**: `adgn/scripts/generate_types.py` (commit 7c6cae7ad)
      Uses `TypeAdapter.json_schema()` + `json-schema-to-typescript` CLI
    - Alternative tools: `pydantic-to-typescript` (npm), `datamodel-code-generator` (Python)
  |||,
)
