local I = import '../../specimens/lib.libsonnet';

// iss-042: Repeated type casting to any instead of using typed content models

I.issueOneOccurrence(
  rationale= |||
    The `ToolExec.svelte` and `ToolJson.svelte` components repeatedly cast
    `item.content` to `any` instead of using the proper typed TypeScript models
    (`ExecContent`, `JsonContent`) that already exist.

    **Problem: Repeated `(item.content as any)` loses type safety**

    **Current implementation (ToolExec.svelte, lines 39-51):**
    ```svelte
    <div class="terminal-body">
      {#if item.content && (item.content as any).cmd}
        <pre class="term-line">$ {(item.content as any).cmd}</pre>
      {/if}
      ... same if-pattern repeated N times ...
      {#if item.content && (item.content as any).is_error}
        <div class="term-error">[error]</div>
      {/if}
    </div>
    ```

    **Why this is problematic:**

    1. **Lost type safety**: `as any` bypasses TypeScript checking
    2. **Duplication**: `(item.content as any)` repeated 8 times in 13 lines
    3. **Typo vulnerability**: Misspelling `exit_code` won't be caught
    4. **Unclear types**: Reader doesn't know what fields exist on content
    5. **No autocomplete**: IDE can't suggest available fields
    6. **Types already exist**: `ExecContent` and `JsonContent` are already defined in `types.ts`

    **Types already exist (types.ts):**
    ```typescript
    export type ExecContent = {
      content_kind: 'Exec'
      cmd?: string | null
      args?: unknown | null
      stdout?: string | null
      stderr?: string | null
      exit_code?: number | null
      is_error?: boolean | null
    }

    export type JsonContent = {
      content_kind: 'Json'
      args?: unknown | null
      result?: unknown | null
      is_error?: boolean | null
    }

    export type ToolContent = ExecContent | JsonContent

    export type ToolItem = {
      kind: 'Tool'
      id: string
      ts: string
      tool: string
      call_id: string
      decision?: ApprovalKind | null
      content: ToolContent
    }
    ```

    **The correct approach for ToolExec.svelte:**

    Use a discriminated union type guard:
    ```svelte
    <script lang="ts">
      import type { ToolItem } from '../shared/types'
      import JsonDisclosure from './JsonDisclosure.svelte'

      export let item: ToolItem

      // Type-safe content access with discriminated union
      $: execContent = item.content?.content_kind === 'Exec' ? item.content : null

      function copyText(text: string) {
        if (!text) return
        if (navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(text).catch(() => {})
        } else {
          const ta = document.createElement('textarea')
          ta.value = text
          document.body.appendChild(ta)
          ta.select()
          try { document.execCommand('copy') } finally { document.body.removeChild(ta) }
        }
      }

      function copyExec() {
        if (!execContent) return
        const parts: string[] = []
        if (execContent.cmd) parts.push(`$ ${execContent.cmd}`)
        if (execContent.stdout) parts.push(String(execContent.stdout))
        if (execContent.stderr) parts.push(String(execContent.stderr))
        copyText(parts.join('\n'))
      }
    </script>

    <div class="terminal">
      <div class="kind">{item.tool} {#if item.decision}<span class="term-approval">[{item.decision}]</span>{/if}
        <button class="copy" title="Copy output" on:click={copyExec}>Copy</button>
      </div>
      {#if typeof item.tool === 'string' && item.tool.endsWith('__sandbox_exec')}
        <JsonDisclosure label="SBPL Policy" value={execContent?.args?.policy} persistKey={`sbpl:${item.id}`} />
        <JsonDisclosure label="Raw output (JSON)" value={item.content} persistKey={`execraw:${item.id}`} />
      {/if}
      <div class="terminal-body">
        {#if execContent?.cmd}
          <pre class="term-line">$ {execContent.cmd}</pre>
        {/if}
        {#if execContent?.stdout}
          <pre class="term-stdout">{execContent.stdout}</pre>
        {/if}
        {#if execContent?.stderr}
          <pre class="term-stderr">{execContent.stderr}</pre>
        {/if}
        {#if execContent?.exit_code !== null && execContent?.exit_code !== undefined}
          <div class="term-exit">[exit {execContent.exit_code}]</div>
        {/if}
        {#if execContent?.is_error}
          <div class="term-error">[error]</div>
        {/if}
      </div>
    </div>
    ```

    **Benefits:**

    1. **Type safety**: TypeScript knows `execContent` is `ExecContent | null`
    2. **No duplication**: One cast via reactive statement `$: execContent = ...`
    3. **Autocomplete**: IDE suggests `cmd`, `stdout`, `stderr`, etc.
    4. **Typo protection**: Misspelling fields causes compile error
    5. **Clearer code**: Explicit about content type being checked
    6. **Single source of truth**: Uses types from `types.ts`

    **Problem in ToolJson.svelte:**

    Similar issue with manual Zod parsing instead of using TypeScript types:

    **Current implementation (ToolJson.svelte, lines 24-42):**
    ```typescript
    // Prefer structured_content when present (FastMCP CallToolResult)
    import { z } from 'zod'
    const CallToolResultZ = z.object({ structured_content: z.unknown().optional() }).passthrough()
    const StructuredOutZ = z.object({
      error: z.string().optional(),
      ok: z.boolean().optional(),
      rationale: z.string().optional(),
    }).passthrough()

    function pickDisplayResult(): unknown {
      const c = item?.content
      const res: unknown = (c && (c as any).content_kind === 'Json') ? (c as any).result : undefined
      if (res && typeof res === 'object') {
        const parsed = CallToolResultZ.safeParse(res)
        if (parsed.success && parsed.data.structured_content !== undefined) {
          return parsed.data.structured_content
        }
      }
      return res
    }
    ```

    **Why this is problematic:**

    1. **Type cast to any**: `(c as any).content_kind`, `(c as any).result`
    2. **Manual Zod parsing**: Duplicates what TypeScript types already provide
    3. **Lost type checking**: `content_kind === 'Json'` not type-safe

    **The correct approach:**

    Use TypeScript discriminated unions:
    ```typescript
    function pickDisplayResult(): unknown {
      if (item?.content?.content_kind !== 'Json') return undefined
      // TypeScript now knows content is JsonContent
      const jsonContent = item.content
      const res = jsonContent.result

      if (res && typeof res === 'object') {
        // If CallToolResult has structured_content, use it
        const parsed = CallToolResultZ.safeParse(res)
        if (parsed.success && parsed.data.structured_content !== undefined) {
          return parsed.data.structured_content
        }
      }
      return res
    }
    ```

    Or even better, define TypeScript types for CallToolResult:
    ```typescript
    type CallToolResult = {
      structured_content?: unknown
      // ... other fields
    }

    function pickDisplayResult(): unknown {
      if (item?.content?.content_kind !== 'Json') return undefined
      const result = item.content.result as CallToolResult | undefined
      return result?.structured_content ?? result
    }
    ```

    **User mentioned "pretty mechanism for parsing Pydantic models":**

    The project should have (or should create) a tool to generate TypeScript types from
    Pydantic models:
    - Export Pydantic models to JSON Schema
    - Generate TypeScript types from JSON Schema
    - Use those types instead of manual `as any` or Zod schemas

    Tools like `pydantic-to-typescript`, `json-schema-to-typescript`, or custom scripts
    can automate this.

    **Why duplication happened:**

    1. Pydantic types exist in Python
    2. TypeScript types manually created in `types.ts`
    3. Components weren't updated to use the TypeScript types
    4. Quick fix: `as any` to bypass type errors
    5. Copy-paste: `as any` pattern spread across components

    **How to prevent:**

    1. **Generate types**: Automate Pydantic → TypeScript type generation
    2. **Code review**: Flag `as any` in review (especially repeated casts)
    3. **Linting**: Configure ESLint/TSConfig to warn on `as any`
    4. **Type guards**: Use discriminated unions with type guards
    5. **Reactivity**: Use Svelte reactive statements (`$:`) for derived typed values

    **Related cleanups needed:**

    1. ToolExec.svelte: Replace all `(item.content as any)` with typed `execContent`
    2. ToolJson.svelte: Replace `(c as any)` with proper type guards
    3. Consider generating TypeScript types from Pydantic models
    4. Add ESLint rule to discourage `as any`
  |||,
  properties=['type-safe-apis', 'avoid-type-casting', 'use-platform-primitives', 'avoid-duplication'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [40, 51],   // Repeated (item.content as any) casts
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [33, 33],   // (c as any).content_kind and (c as any).result
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-type-casting"**: repeated `as any` casts
    indicate missing type guards or improperly used types.

    Principle: Use discriminated unions + type guards
    - TypeScript discriminated unions (tagged unions) enable type narrowing
    - Type guard: `if (content.content_kind === 'Exec') { /* content is ExecContent */ }`
    - Avoid: `(content as any).field`

    Related to **"type-safe-APIs"**: when backend types exist (Pydantic models),
    frontend should use matching TypeScript types, not ad-hoc parsing.

    Related to **"use-platform-primitives"**: TypeScript's discriminated unions
    are the idiomatic way to handle variant types. Don't bypass with `as any`.

    Patterns for discriminated unions:

    **Good - Type guard with discriminated union:**
    ```typescript
    type ExecContent = { kind: 'Exec'; cmd: string }
    type JsonContent = { kind: 'Json'; result: unknown }
    type Content = ExecContent | JsonContent

    function handle(content: Content) {
      if (content.kind === 'Exec') {
        // TypeScript knows: content is ExecContent
        console.log(content.cmd)
      } else {
        // TypeScript knows: content is JsonContent
        console.log(content.result)
      }
    }
    ```

    **Good - Reactive statement in Svelte:**
    ```svelte
    <script lang="ts">
      export let item: ToolItem
      $: execContent = item.content.kind === 'Exec' ? item.content : null
    </script>
    {#if execContent}
      <pre>{execContent.cmd}</pre>
    {/if}
    ```

    **Bad - Repeated type casts:**
    ```svelte
    {#if (item.content as any).cmd}
      <pre>{(item.content as any).cmd}</pre>
    {/if}
    {#if (item.content as any).stdout}
      <pre>{(item.content as any).stdout}</pre>
    {/if}
    ```

    **Automation: Pydantic to TypeScript**

    Tools to generate TypeScript from Pydantic:
    - `pydantic-to-typescript` (npm package)
    - `datamodel-code-generator` (Python, generates from JSON Schema)
    - `json-schema-to-typescript` (from Pydantic's JSON Schema output)

    Workflow:
    1. Export Pydantic models to JSON Schema: `model.model_json_schema()`
    2. Generate TypeScript types: `json2ts schema.json > types.ts`
    3. Use generated types in frontend

    Benefits:
    - Single source of truth (Pydantic models)
    - No manual type duplication
    - Automatic updates when backend changes
    - Type safety across backend/frontend boundary

    Red flags in code review:
    - `as any` repeated multiple times
    - Same field accessed with multiple casts
    - Manual Zod schemas duplicating existing types
    - Type casts instead of type guards
  |||,
)
