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

    **Implementation requirements:**
    The generator at `adgn/scripts/generate_frontend_code.py` (lines 190-250) currently:
    - Uses `TypeAdapter(model).json_schema()` which properly handles Pydantic discriminated unions
    - Outputs only TypeScript interfaces via `json-schema-to-typescript`
    - Does NOT generate Zod schemas

    To implement this fix, extend the generator to output Zod schemas. Two approaches:

    **Option 1: Use json-schema-to-zod package**
    Add `json-schema-to-zod` (npm) to the codegen pipeline. It converts JSON Schema (draft 4+)
    into Zod schema code. Since Pydantic's JSON Schema includes discriminator metadata, the
    converter should handle discriminated unions:
    ```bash
    npx json-schema-to-zod --input schema.json --output schemas.ts
    ```

    **Option 2: Custom generator**
    Detect `discriminator` field in Pydantic's JSON Schema output and emit Zod code directly:
    ```typescript
    const ToolContentZ = z.discriminatedUnion("content_kind", [
      z.object({ content_kind: z.literal("Exec"), cmd: z.string(), ... }),
      z.object({ content_kind: z.literal("Json"), result: z.unknown(), ... }),
    ])
    ```

    Option 1 is simpler and leverages existing tooling. No changes needed to Pydantic model
    parsing - discriminator information is already in the JSON Schema output.

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
