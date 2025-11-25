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

    1. **Export Pydantic to JSON Schema:**
       ```python
       from pydantic import BaseModel
       schema = ToolCall.model_json_schema()
       ```

    2. **Generate Zod schema:**
       - Use `json-schema-to-zod` (npm package)
       - Or custom script to convert JSON Schema → Zod

    3. **Use in frontend:**
       ```typescript
       import { ToolCallSchema } from '../generated/schemas'
       const toolCall = ToolCallSchema.parse(data)
       ```

    **Example: Comprehensive parsing with Zod**

    ```typescript
    import { z } from 'zod'

    // Generated from backend Pydantic models
    const ToolCallSchema = z.object({
      name: z.string(),
      call_id: z.string(),
      args_json: z.string().nullable().optional()
    })

    const ApprovalBlockSchema = z.object({
      agent_id: z.string(),
      tool_call: ToolCallSchema,
      timestamp: z.string().datetime()
    })

    type ApprovalBlock = z.infer<typeof ApprovalBlockSchema>

    function parseApprovalSafely(text: string): ApprovalBlock | null {
      try {
        const json = JSON.parse(text)
        return ApprovalBlockSchema.parse(json)
      } catch (error) {
        if (error instanceof z.ZodError) {
          console.error('Approval validation failed:', {
            issues: error.issues,
            data: text
          })
        } else if (error instanceof SyntaxError) {
          console.error('Invalid JSON:', text)
        } else {
          console.error('Unexpected error:', error)
        }
        return null
      }
    }

    // Usage:
    const approval = parseApprovalSafely(block.text)
    if (approval) {
      parsedApprovals.push(approval)
    } else {
      // Handle invalid data explicitly
      metrics.increment('approvals.parse_error')
    }
    ```

    **Why manual parsing happened:**

    1. Pydantic models existed in backend
    2. Frontend types manually created (duplicating structure)
    3. No automated Pydantic → TypeScript/Zod generation
    4. Quick fix: manual `JSON.parse()` instead of proper validation

    **Migration steps:**

    1. Set up Pydantic → JSON Schema export
    2. Generate Zod schemas from JSON Schema
    3. Replace manual parsing with Zod validation
    4. Add error handling for validation failures
    5. Consider metrics/logging for parse errors
  |||,
  properties=['use-platform-primitives', 'schema-validation', 'avoid-manual-parsing', 'type-safe-apis'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [29, 36],    // parseArgs manual JSON.parse
      [115, 121],  // Manual parsing in fetchApprovals
    ],
  },
  gap_note= |||
    This finding illustrates **"schema-validation"**: when parsing data from external
    sources (backend API, user input, files), use schema validation (Zod, Yup, etc.)
    instead of manual parsing.

    Principle: Validate at boundaries
    - API responses: validate with schemas
    - User input: validate before use
    - Config files: validate on load
    - Messages: validate before processing

    Related to **"use-platform-primitives"**: Zod is the TypeScript standard for
    runtime validation. Use it instead of manual `try/catch` around `JSON.parse()`.

    Related to **"type-safe-apis"**: Backend Pydantic models should generate
    frontend types and schemas, ensuring consistency.

    Why schema validation matters:

    **Without validation (manual parsing):**
    ```typescript
    function parse(json: string) {
      try {
        const data = JSON.parse(json)
        // Hope data has the right shape...
        return { name: data.name, id: data.id }
      } catch {
        return null  // What went wrong? Unknown.
      }
    }
    ```

    Problems:
    - No validation (accepts any JSON)
    - Silent coercion (`data.name` might be undefined)
    - No error details
    - TypeScript can't help

    **With schema validation (Zod):**
    ```typescript
    const UserSchema = z.object({
      name: z.string(),
      id: z.string().uuid()
    })

    function parse(json: string) {
      try {
        const data = JSON.parse(json)
        return UserSchema.parse(data)  // Throws if invalid
      } catch (error) {
        if (error instanceof z.ZodError) {
          // Detailed validation errors
          console.error('Validation failed:', error.issues)
        }
        return null
      }
    }
    ```

    Benefits:
    - Runtime validation (catches malformed data)
    - Detailed errors (know exactly what's wrong)
    - Type safety (TypeScript knows validated shape)
    - Documentation (schema is self-documenting)

    **Pydantic → Zod workflow:**

    1. Backend exports Pydantic to JSON Schema
    2. Tool generates Zod from JSON Schema
    3. Frontend uses Zod for parsing/validation

    Tools:
    - `pydantic-to-typescript` (generates TS types + Zod)
    - `json-schema-to-zod` (converts JSON Schema → Zod)
    - `datamodel-code-generator` (Python, generates from Pydantic)

    **Example generation:**

    ```python
    # Backend (Python)
    from pydantic import BaseModel

    class User(BaseModel):
        name: str
        email: str

    # Export JSON Schema
    schema = User.model_json_schema()
    ```

    ```typescript
    // Frontend (generated)
    import { z } from 'zod'

    export const UserSchema = z.object({
      name: z.string(),
      email: z.string().email()
    })

    export type User = z.infer<typeof UserSchema>

    // Usage
    const user = UserSchema.parse(apiResponse)
    ```

    **When to use Zod:**

    - Parsing API responses
    - Validating form input
    - Loading config files
    - Processing message queues
    - Any external/untrusted data

    **When manual parsing OK:**

    - Internal trusted data (same codebase)
    - Performance-critical paths (pre-validated)
    - Schema is trivial (single primitive)
  |||,
)
