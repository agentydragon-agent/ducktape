local I = import '../../lib.libsonnet';

// Merged: discriminated-union-guards, zod-validation-missing
// Both describe missing Zod validation for Pydantic-derived types in frontend

I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/components/ToolExec.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ToolJson.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ChatPane.svelte'],
  ],
  rationale= |||
    Frontend components use manual type guards and type assertions instead of runtime
    validation with Zod schemas.

    **Pattern 1 (ToolExec.svelte, ToolJson.svelte lines 8-9):** Manual string comparison
    `if (content_kind === 'Exec')` without validating structure.

    **Pattern 2 (ChatPane.svelte lines 84-92):** `JSON.parse(text) as AgentList` uses
    compile-time-only type assertion.

    **Problems:**
    - Type assertions don't validate at runtime; invalid JSON causes silent failures
    - TypeScript types can drift from Python Pydantic models
    - Poor error messages (generic instead of field-level validation details)
    - Maintaining parallel type definitions is error-prone

    **Fix:** Extend `adgn/scripts/generate_frontend_code.py` to output Zod schemas
    alongside TypeScript types. Generator already produces JSON Schema via
    `TypeAdapter(model).json_schema()`; use `json-schema-to-zod`
    (https://www.npmjs.com/package/json-schema-to-zod) to convert to Zod code.

    Replace `JSON.parse(text) as Type` with `TypeSchema.safeParse(JSON.parse(text))`;
    check `result.success` and use `result.data`. Discriminated unions will validate
    and narrow correctly via `z.discriminatedUnion()`.

    Benefits: runtime safety, single source of truth (Pydantic → Zod), detailed
    validation errors, automatic regeneration on schema changes.
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
