local I = import '../../specimens/lib.libsonnet';

// iss-043: applyPresetFrom thin wrapper should inline at call site

I.issueOneOccurrence(
  rationale= |||
    The `applyPresetFrom` function in `ServersPanel.svelte` is a thin wrapper that
    finds a preset by ID and applies its fields. This could be inlined at the single
    call site, eliminating the unnecessary indirection.

    **Problem: Thin wrapper function with single caller**

    **Current implementation (ServersPanel.svelte, lines 185-197):**
    ```typescript
    function applyPresetFrom(id: string) {
      const p = MCP_PRESETS.find((it) => it.id === id)
      if (!p) return
      transport = p.transport
      if (p.defaultName && !newName) newName = p.defaultName
      if (p.transport === 'stdio' && p.defaults.stdio) {
        stdioCommand = p.defaults.stdio.command
        stdioArgs = JSON.stringify(p.defaults.stdio.args ?? [], null, 2)
        stdioEnv = JSON.stringify(p.defaults.stdio.env ?? {}, null, 2)
      } else if (p.transport === 'inproc' && p.defaults.inproc) {
        inprocFactory = p.defaults.inproc.factory
        // ... more field assignments
      }
    }
    ```

    **Single call site (ServersPanel.svelte, line 257):**
    ```svelte
    <select id="preset-select" bind:value={preset} on:change={(e) => applyPresetFrom((e.target as HTMLSelectElement).value)}>
    ```

    **Why this is a thin wrapper:**

    1. **Single caller**: Only used once in the entire component
    2. **Simple logic**: Just finds preset and copies fields
    3. **No reuse**: Not called from multiple places
    4. **Direct mapping**: Preset fields → component state, no transformation
    5. **Unnecessary abstraction**: Adds function call overhead for no benefit

    **The correct approach:**

    Inline the logic at the call site:
    ```svelte
    <select
      id="preset-select"
      bind:value={preset}
      on:change={(e) => {
        const id = (e.target as HTMLSelectElement).value
        const p = MCP_PRESETS.find((it) => it.id === id)
        if (!p) return
        transport = p.transport
        if (p.defaultName && !newName) newName = p.defaultName
        if (p.transport === 'stdio' && p.defaults.stdio) {
          stdioCommand = p.defaults.stdio.command
          stdioArgs = JSON.stringify(p.defaults.stdio.args ?? [], null, 2)
          stdioEnv = JSON.stringify(p.defaults.stdio.env ?? {}, null, 2)
        } else if (p.transport === 'inproc' && p.defaults.inproc) {
          inprocFactory = p.defaults.inproc.factory
          // ... more field assignments
        }
      }}
    >
    ```

    **Or use a reactive statement if the logic is complex:**
    ```svelte
    <script>
      let preset = ''

      // Reactive: apply preset whenever it changes
      $: if (preset) {
        const p = MCP_PRESETS.find((it) => it.id === preset)
        if (p) {
          transport = p.transport
          if (p.defaultName && !newName) newName = p.defaultName
          // ... field assignments
        }
      }
    </script>

    <select id="preset-select" bind:value={preset}>
      <option value="">Custom</option>
      {#each MCP_PRESETS as p}
        <option value={p.id}>{p.label}</option>
      {/each}
    </select>
    ```

    **Benefits:**

    1. **Less indirection**: No function call, logic is visible at use site
    2. **Clearer flow**: Reader sees what happens on change without jumping to function
    3. **Fewer lines**: Remove function definition, inline at use
    4. **Better for single use**: No false generalization

    **User also mentioned: "should use schema copying from Python"**

    The user suggests that instead of manually copying fields from `McpPreset` to
    component state, the component should use types generated from Python Pydantic
    models (similar to issue 042).

    **Current manual field copying:**
    ```typescript
    // Manual extraction of preset fields
    stdioCommand = p.defaults.stdio.command
    stdioArgs = JSON.stringify(p.defaults.stdio.args ?? [], null, 2)
    stdioEnv = JSON.stringify(p.defaults.stdio.env ?? {}, null, 2)
    ```

    **Better with generated types:**

    If `McpPreset` TypeScript type was auto-generated from Python `ServerSpec` Pydantic
    model, the structure would match exactly and field copying would be type-safe:

    ```typescript
    // Import generated types from Pydantic models
    import type { ServerSpec } from '../shared/generated-types'

    // Type-safe assignment
    const spec: ServerSpec = {
      transport: p.transport,
      stdio: p.defaults.stdio,
      // TypeScript ensures all required fields present
    }
    ```

    **Why manual field copying is problematic:**

    1. **Duplication**: Backend has `ServerSpec` Pydantic model, frontend has `McpPreset`
    2. **Drift risk**: Backend changes fields, frontend not updated
    3. **Type mismatch**: No guarantee frontend types match backend
    4. **Manual JSON.stringify**: Should be automatic serialization

    **Recommended approach:**

    1. Export Pydantic `ServerSpec` to JSON Schema
    2. Generate TypeScript types from JSON Schema
    3. Use generated types in frontend
    4. Apply presets by constructing `ServerSpec` instances

    This ensures frontend and backend share exact same type structure.

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
    - `pydantic-to-typescript` (npm)
    - `datamodel-code-generator` (Python)
    - Custom script: `model.model_json_schema()` → `json-schema-to-typescript`
  |||,
)
