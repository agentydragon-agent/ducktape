local I = import '../../specimens/lib.libsonnet';

// iss-046: GlobalApprovalsList manual JSON parsing should use Zod from Pydantic

I.issueOneOccurrence(
  rationale= |||
    The `GlobalApprovalsList.svelte` component uses manual `JSON.parse()` to parse
    tool call arguments instead of using Zod schemas that could be generated from
    the backend Pydantic models (like `ToolCall`).

    **Problem: Manual JSON parsing without validation**

    **Current implementation (GlobalApprovalsList.svelte, lines 29-36):**
    ```typescript
    /**
     * Parse tool call args_json to object
     */
    function parseArgs(argsJson: string | null): Record<string, unknown> {
      if (!argsJson) return {}
      try {
        return JSON.parse(argsJson)
      } catch {
        return {}  // Silent failure, returns empty object
      }
    }
    ```

    **Also in fetchApprovals (lines 115-121):**
    ```typescript
    try {
      const data = JSON.parse(block.text)
      parsedApprovals.push({
        agent_id: data.agent_id,
        tool_call: data.tool_call,
        timestamp: data.timestamp
      })
    } catch (parseError) {
      console.error('Failed to parse approval block:', parseError, block)
    }
    ```

    **Why this is problematic:**

    1. **No validation**: `JSON.parse()` accepts any valid JSON, doesn't check structure
    2. **Silent failures**: `parseArgs` returns `{}` on error, losing information
    3. **Type unsafe**: `Record<string, unknown>` doesn't match actual shape
    4. **No schema checking**: Can't detect missing/extra fields
    5. **Duplication**: Backend has `ToolCall` Pydantic model, frontend has manual parsing

    **Backend has Pydantic models (types.py, lines 20-25):**
    ```python
    class ToolCall(BaseModel):
        """Tool call information (simple version without discriminator)."""

        name: str = Field(description="Tool name")
        call_id: str = Field(description="Unique call identifier")
        args_json: str | None = Field(None, description="Tool arguments as JSON string")
    ```

    **The correct approach: Use Zod generated from Pydantic**

    **1. Generate Zod schema from Pydantic model:**

    Tools like `pydantic-to-typescript` or custom scripts can generate both TypeScript
    types and Zod schemas from Pydantic models.

    ```typescript
    // Generated from Pydantic ToolCall model
    import { z } from 'zod'

    export const ToolCallSchema = z.object({
      name: z.string(),
      call_id: z.string(),
      args_json: z.string().nullable()
    })

    export type ToolCall = z.infer<typeof ToolCallSchema>

    export const PendingApprovalSchema = z.object({
      agent_id: z.string(),
      tool_call: ToolCallSchema,
      timestamp: z.string()
    })

    export type PendingApproval = z.infer<typeof PendingApprovalSchema>
    ```

    **2. Use Zod for parsing:**

    ```typescript
    import { ToolCallSchema, PendingApprovalSchema } from '../generated/schemas'

    /**
     * Parse tool call args_json with validation
     */
    function parseArgs(argsJson: string | null): Record<string, unknown> | null {
      if (!argsJson) return null

      try {
        // Parse JSON first
        const parsed = JSON.parse(argsJson)
        // Could add schema validation here if we have ArgSchema
        return parsed
      } catch (error) {
        console.error('Failed to parse tool args:', error)
        return null  // Return null instead of empty object to signal failure
      }
    }

    /**
     * Parse approval block with Zod validation
     */
    function parseApprovalBlock(text: string): PendingApproval & { agent_id: string } | null {
      try {
        const data = JSON.parse(text)
        // Validate with Zod
        const validated = PendingApprovalSchema.parse(data)
        return validated
      } catch (error) {
        if (error instanceof z.ZodError) {
          console.error('Invalid approval schema:', error.errors)
        } else {
          console.error('Failed to parse approval:', error)
        }
        return null
      }
    }

    // In fetchApprovals:
    for (const block of contents) {
      if ('text' in block && block.mimeType === 'application/json') {
        const approval = parseApprovalBlock(block.text)
        if (approval) {
          parsedApprovals.push(approval)
        }
      }
    }
    ```

    **Benefits of Zod validation:**

    1. **Type safety**: Schema matches backend Pydantic model exactly
    2. **Runtime validation**: Catches malformed data from backend
    3. **Better errors**: Zod provides detailed validation errors
    4. **No silent failures**: Explicitly handle validation errors
    5. **Single source of truth**: Backend Pydantic → Frontend Zod
    6. **Catch backend changes**: If backend changes model, validation fails

    **User's note: "parsing tool calls should use zod copied from json side
    pydantic (possibly ToolCall?)"**

    Yes, the backend has `ToolCall` Pydantic model in `agent/types.py`. The frontend
    should use a Zod schema generated from this model instead of manual parsing.

    **Workflow for Pydantic → Zod:**

    The existing `adgn/scripts/generate_types.py` (commit 7c6cae7ad) generates TypeScript
    interfaces from Pydantic models. To add Zod support, extend it to also generate Zod
    schemas using `json-schema-to-zod` from the same JSON Schema output.

    Then use `ToolCallSchema.parse(data)` instead of manual `JSON.parse()` to get
    runtime validation with detailed error messages.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [29, 36],    // parseArgs manual JSON.parse
      [115, 121],  // Manual parsing in fetchApprovals
    ],
  },
)
