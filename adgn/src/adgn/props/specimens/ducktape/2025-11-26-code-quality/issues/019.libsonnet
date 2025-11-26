local I = import '../../specimens/lib.libsonnet';

// iss-019: Use pydantic->ts generator with zod instead of JSON.parse with loose types

I.issueOneOccurrence(
  rationale= |||
    The code uses `JSON.parse()` with TypeScript type assertions (`as AgentList`) instead
    of using the pydantic->ts generator to create Zod schemas and proper runtime validation.

    **Current implementation (ChatPane.svelte:84-92):**
    ```typescript
    // Parse the resource contents
    if (Array.isArray(contents) && contents.length > 0) {
      const firstContent = contents[0]
      if (firstContent.type === 'text' && firstContent.text) {
        const agentList = JSON.parse(firstContent.text) as AgentList
        const agentInfo = agentList.agents.find(a => a.agent_id === id)
        agentMode = agentInfo?.mode ?? null
      }
    }
    ```

    **Problems:**
    1. **No runtime validation**: `as AgentList` is just a type assertion (compile-time only)
    2. **Silent failures**: Invalid JSON structure will cause runtime errors or wrong data
    3. **Type drift**: TypeScript types can drift from actual Python Pydantic models
    4. **Duplicate definitions**: Maintaining parallel type definitions is error-prone
    5. **Missing Zod generation**: We have a pydantic->ts generator (`adgn/scripts/generate_frontend_code.py`)
       that generates TypeScript interfaces, but it needs to be extended to also generate Zod schemas

    **Correct approach:**
    Replace `JSON.parse(text) as AgentList` with Zod validation:
    ```typescript
    import { AgentListZ } from '../generated/schemas'  // Generated from Pydantic

    const result = AgentListZ.safeParse(JSON.parse(firstContent.text))
    if (!result.success) { /* handle error */ }
    const agentInfo = result.data.agents.find(...)
    ```

    **Benefits:**
    1. **Runtime safety**: Invalid data caught immediately with clear error messages
    2. **Single source of truth**: Types generated from Pydantic models
    3. **No drift**: TypeScript types always match Python models
    4. **Better errors**: Zod provides detailed validation errors
    5. **Type inference**: Zod infers TypeScript types from schemas

    **Implementation plan:**
    1. **Extend generator for Zod**: The generator at `adgn/scripts/generate_frontend_code.py`
       currently outputs only TypeScript interfaces to `adgn/src/adgn/agent/web/src/generated/types.ts`.
       It needs to also generate Zod schemas to `adgn/src/adgn/agent/web/src/generated/schemas.ts`.

       Tools to use:
       - The generator already uses `model_json_schema()` to get JSON Schema from Pydantic
       - Use `json-schema-to-zod` npm package to convert JSON Schema → Zod schemas
       - Or use `ts-to-zod` to generate Zod from the TypeScript interfaces

    2. **Apply pattern**: Replace all `JSON.parse(text) as Type` with `TypeZ.safeParse(JSON.parse(text))`
       throughout the codebase.

    **Note:** This pattern should be applied to ALL JSON.parse calls that expect
    structured data from the backend. Use Zod schemas generated from Pydantic models
    wherever possible.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [84, 92],  // JSON.parse with loose type assertion
    ],
  },
)
