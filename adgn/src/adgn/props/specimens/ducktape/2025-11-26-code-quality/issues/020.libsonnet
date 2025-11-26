local I = import '../../specimens/lib.libsonnet';

// iss-020: Discriminated union type guards should use proper zod validation

I.issueOneOccurrence(
  rationale= |||
    The code uses manual discriminated union type guards (checking `content_kind === 'Exec'`)
    instead of using proper Zod validation against schemas generated from the Python Pydantic
    models.

    **Current implementation:**

    **ToolExec.svelte:8:**
    ```typescript
    // Use discriminated union type guard for type-safe access
    $: execContent = item.content?.content_kind === 'Exec' ? item.content : null
    ```

    **ToolJson.svelte:9:**
    ```typescript
    // Use discriminated union type guard for type-safe access
    $: jsonContent = item.content?.content_kind === 'Json' ? item.content : null
    ```

    **Problems:**
    1. **String literal comparison**: Checking `content_kind === 'Exec'` is fragile
    2. **No runtime validation**: Type assertion doesn't validate structure
    3. **Type drift risk**: TypeScript types can drift from Python Pydantic models
    4. **Duplicate logic**: Manual type guards instead of generated validators
    5. **Misleading comment**: Says "type-safe" but only does string comparison

    **Correct approach:**
    Use Zod schemas generated from Pydantic discriminated unions:

    ```typescript
    // Generated from Python Pydantic models
    import { ExecContentZ, JsonContentZ } from '../../generated/schemas'

    // Validate with Zod instead of manual type guard
    $: execContent = (() => {
      if (!item.content) return null
      const result = ExecContentZ.safeParse(item.content)
      return result.success ? result.data : null
    })()
    ```

    Or if the UI bus types have proper discriminated union schemas:

    ```typescript
    import { ToolContentZ } from '../../generated/schemas'

    $: execContent = (() => {
      if (!item.content) return null
      const result = ToolContentZ.safeParse(item.content)
      if (!result.success || result.data.content_kind !== 'Exec') return null
      return result.data
    })()
    ```

    **Benefits:**
    1. **Runtime validation**: Ensures content actually matches expected structure
    2. **Single source of truth**: Schemas generated from Python Pydantic models
    3. **No drift**: TypeScript types always match Python models
    4. **Better errors**: Invalid data logged with clear messages
    5. **Type inference**: Zod narrows types correctly

    **Implementation plan:**
    1. **Extend generator for Zod with discriminated union support**: The generator at
       `adgn/scripts/generate_frontend_code.py` currently outputs only TypeScript interfaces.
       It needs to also generate Zod schemas with discriminated union support.

       Zod discriminated unions example:
       ```typescript
       const ToolContentZ = z.discriminatedUnion("content_kind", [
         z.object({ content_kind: z.literal("Exec"), cmd: z.string(), ... }),
         z.object({ content_kind: z.literal("Json"), result: z.unknown(), ... }),
       ])
       ```

    2. **Check discriminated union support**: Verify the pydantic->ts generator can properly
       handle Pydantic discriminated unions (models with `discriminator` field). The UI bus
       types use `content_kind` as the discriminator. If the generator doesn't handle this,
       extend it to detect Pydantic discriminated unions and generate proper Zod discriminatedUnion
       schemas.

    **Same pattern in:**
    - ToolExec.svelte:8 (checking for 'Exec')
    - ToolJson.svelte:9 (checking for 'Json')
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [8, 8],  // Manual type guard for Exec content
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [9, 9],  // Manual type guard for Json content
    ],
  },
)
