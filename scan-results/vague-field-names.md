# Scan Results: Vague Field Names

## Summary

This scan identified instances where field names lack sufficient context to clarify their purpose, based on semantic analysis of the ducktape codebase. The focus was on cases where:
- Container names don't provide full context for generic field names
- Multiple similar entities exist in the same scope
- Field names are documented because they're vague (indicating the type should be clearer)

**Total instances found: 1**

## Findings

### 1. RunnerEnvironment.data - Generic type-specific data dict

**Location:** `/home/user/ducktape/adgn/src/adgn/inop/engine/models.py:343`

**Class definition:**
```python
@dataclass
class RunnerEnvironment:
    """Environment information from a runner."""

    type: str  # "docker_container", "workspace_dir", etc.
    data: dict[str, Any]  # Type-specific data

    @property
    def container_id(self) -> str | None:
        """Get Docker container ID if this is a container environment."""
        if self.type == "docker_container":
            return self.data.get("container_id")
        return None

    @property
    def workspace_path(self) -> str | None:
        """Get workspace path if this is a directory environment."""
        if self.type == "workspace_dir":
            return self.data.get("path")
        return None
```

**Context issue:**
The `data` field is documented as "Type-specific data" which is vague and doesn't clarify what the field actually contains. The comment is a red flag - if a field needs documentation to explain what it is, the type/name should be more specific.

**Why this is vague:**
- The field name `data` is extremely generic
- The comment "Type-specific data" doesn't help - it just states the obvious
- The actual contents vary based on `type` (container_id, path, etc.) suggesting this should be a discriminated union
- Developers must read the property methods to understand what `data` might contain

**Suggested fix:**
Either:
1. Use a discriminated union: `DockerEnvironment | WorkspaceEnvironment` with properly typed fields
2. Rename to something more specific like `environment_config` or `environment_details`

---

## Not Vague (Examples of Acceptable Usage)

The following were examined but deemed acceptable due to sufficient context:

### ClientAPIKey.id, ClientAPIKey.name
**File:** `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py:57-58`

These fields are clear because the class name `ClientAPIKey` provides full context - `id` is obviously the API key's ID, `name` is the API key's name.

### Response.response_id, Response.model
**File:** `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py:105,107`

While `model` could be considered borderline, the context of a Response cache for OpenAI API calls makes it reasonably clear this is the AI model name. The class is specific enough (Response cache for API calls) that `model` is acceptable.

### Error.data
**File:** `/home/user/ducktape/wt/src/wt/shared/protocol.py:82`

This follows the JSON-RPC 2.0 specification where `data` is a standard field name for additional error information. When following an external spec/standard, the field names should match the spec.

### ToolResult.result
**File:** `/home/user/ducktape/adgn/src/adgn/inop/engine/models.py:276`

The class name `ToolResult` makes it obvious that `result` is the result of the tool execution. This is not vague.

### merge_configs(user_cfg, local_cfg, fix)
**File:** `/home/user/ducktape/llm/ducktape_llm_common/ducktape_llm_common/claude_linter/config.py:32`

Both config parameters have specific names (`user_cfg` and `local_cfg`) that distinguish them, so this is acceptable.

---

## Recommendations

1. **RunnerEnvironment.data → discriminated union**: Replace dict with typed DockerEnvironment | WorkspaceEnvironment

This change would make the code more self-documenting and reduce the cognitive load on developers reading the code.
