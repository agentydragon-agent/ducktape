local I = import '../../specimens/lib.libsonnet';

// Merged: discriminated-union-guards, zod-validation-missing
// Both describe missing Zod validation for Pydantic-derived types in frontend

I.issueOneOccurrence(
  rationale= |||
    Frontend components use manual type guards (`content_kind === 'Exec'`) and type
    assertions (`as AgentList`) instead of runtime validation with Zod schemas generated
    from backend Pydantic models.

    **Problem: No runtime validation for Pydantic-derived types**

    **Pattern 1: Manual discriminated union type guards (ToolExec.svelte, ToolJson.svelte)**
    ```typescript
    // Lines 8-9: Manual string comparison
    if (content_kind === 'Exec') {
      // Type assertion, no runtime validation
    }
    ```

    **Pattern 2: JSON.parse with type assertions (ChatPane.svelte)**
    ```typescript
    // Lines 84-92: Parse with compile-time-only type assertion
    const agentList = JSON.parse(firstContent.text) as AgentList
    ```

    **Why this is problematic:**

    1. **No runtime validation**: Type assertions are compile-time only; invalid JSON causes silent failures or runtime errors
    2. **Type drift**: TypeScript types can diverge from Python Pydantic models
    3. **Fragile**: String literal comparisons don't validate structure
    4. **Duplicate definitions**: Maintaining parallel types is error-prone
    5. **Poor error messages**: Runtime failures give generic errors instead of validation details
    6. **Misleading comments**: Code says "type-safe" but only does string comparison

    **The correct approach: Generate and use Zod schemas**

    Extend `adgn/scripts/generate_frontend_code.py` to output Zod schemas alongside
    TypeScript interfaces. Since the generator already produces JSON Schema via
    `TypeAdapter(model).json_schema()`, use `json-schema-to-zod`
    (https://www.npmjs.com/package/json-schema-to-zod) to convert to Zod schema code.

    Pydantic's JSON Schema includes discriminator metadata, so discriminated unions will
    be handled correctly (e.g., `z.discriminatedUnion("content_kind", [...])`).

    **Usage in components:**

    ```typescript
    // Instead of: JSON.parse(text) as AgentList
    const result = AgentListSchema.safeParse(JSON.parse(text))
    if (!result.success) {
      console.error('Invalid agent list:', result.error)
      return
    }
    const agentList = result.data  // Validated and type-safe

    // Discriminated unions get automatic narrowing:
    if (ContentSchema.safeParse(data).success) {
      // Type automatically narrowed based on discriminator
    }
    ```

    **Benefits:**

    1. **Runtime safety**: Catches malformed data from backend
    2. **Single source of truth**: Backend Pydantic → Frontend Zod (no drift)
    3. **Detailed errors**: Zod provides field-level validation errors
    4. **Type narrowing**: Discriminated unions work correctly
    5. **Automatic**: Changes to Pydantic models regenerate schemas
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [8, 8],  // Manual type guard for Exec content
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [9, 9],  // Manual type guard for Json content
    ],
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [84, 92],  // JSON.parse with loose type assertion
    ],
  },
)
