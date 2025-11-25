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

    **Types already exist in types.ts:**

    See `types.ts` for `ExecContent`, `JsonContent`, `ToolContent` (discriminated union),
    and `ToolItem` definitions.

    **The correct approach for ToolExec.svelte:**

    Use a Svelte reactive statement with discriminated union type guard:
    `$: execContent = item.content?.content_kind === 'Exec' ? item.content : null`

    Then access `execContent.cmd`, `execContent.stdout`, etc. without casts. TypeScript
    knows `execContent` is `ExecContent | null`.

    Benefits: type safety, no duplication of casts, autocomplete, typo protection.

    **Problem in ToolJson.svelte:**

    Manual Zod parsing with `(c as any).content_kind` and `(c as any).result` instead
    of using discriminated union type guard. Should check `content_kind === 'Json'`
    first, then TypeScript narrows the type automatically.

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
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [40, 51],   // Repeated (item.content as any) casts
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [33, 33],   // (c as any).content_kind and (c as any).result
    ],
  },
)
