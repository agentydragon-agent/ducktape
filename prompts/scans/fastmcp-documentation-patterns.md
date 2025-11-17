# Scan: FastMCP Documentation Patterns

## Context
@../shared-context.md

## Pattern 1: Missing Field Descriptions in Response Models

### Good Example: adgn/mcp/gitea_mirror/server.py

```python
class TriggerMirrorSyncResponse(BaseModel):
    owner: str = Field(description="Gitea owner (username) of the mirror repository")
    repo: str = Field(description="Repository name (auto-generated from URL)")
    mirror_path: str = Field(
        description="Path to mirror for cloning: 'owner/repo.git' (use with docker_exec bind mount)"
    )
    mirror_updated: str = Field(
        description="Timestamp BEFORE sync started. Poll get_mirror_status() until this changes to detect completion."
    )
    sync_triggered: bool = Field(description="Always true on success (sync was triggered)")
```

### Bad Example

```python
# BAD: No field descriptions - clients only see field names in schema
class MyToolResponse(BaseModel):
    result: str
    status: str
    timestamp: str
    model_config = ConfigDict(extra="forbid")
```

**Why it matters**:
- FastMCP exposes full Pydantic schemas to MCP clients via JSON Schema
- Field descriptions appear in the schema clients receive
- Helps LLM agents understand how to use the response fields
- No ambiguity about field purpose or format

**Detection**:
```bash
# Find response models without Field descriptions
rg --type py "class.*Response.*BaseModel" -A10 | rg -v "Field\(description="
```

## Pattern 2: Redundant Schema Documentation in Docstrings

### Bad Example

```python
# BAD: Repeating schema in docstring
@server.flat_model()
def get_status(input: GetStatusArgs) -> GetStatusResponse:
    """Get current status.

    Returns:
        status: Current status string
        timestamp: ISO 8601 timestamp of last update
        is_ready: Boolean indicating readiness
    """
    ...
```

### Good Example

```python
# GOOD: Schema documented in Pydantic models, docstring focuses on behavior
@server.flat_model()
def get_status(input: GetStatusArgs) -> GetStatusResponse:
    """Get current status.

    Poll this endpoint to check when the system becomes ready.
    Compare timestamp with initial value to detect changes.
    """
    ...

class GetStatusResponse(BaseModel):
    status: str = Field(description="Current status string")
    timestamp: str = Field(description="ISO 8601 timestamp of last update")
    is_ready: bool = Field(description="Boolean indicating readiness")
```

**Why it matters**:
- FastMCP automatically exposes Pydantic schemas to clients
- Docstring duplication leads to drift when schemas change
- Field descriptions in Pydantic models are the single source of truth
- Docstrings should focus on usage patterns, not schema structure

**Detection**:
```bash
# Find docstrings with "Returns:" sections listing fields
rg --type py -A10 "@server\.(flat_model|tool)" | rg "Returns:"
```

## Pattern 3: Missing Context in Field Descriptions

### Bad Example

```python
# BAD: Descriptions are just rephrasing of field names
class SyncResponse(BaseModel):
    repo: str = Field(description="The repository")
    updated: str = Field(description="Updated timestamp")
```

### Good Example

```python
# GOOD: Descriptions include usage context and format details
class SyncResponse(BaseModel):
    repo: str = Field(description="Repository name (auto-generated from URL)")
    updated: str = Field(
        description="Timestamp BEFORE sync started. Poll get_status() until this changes to detect completion."
    )
```

**Why it matters**:
- Field names alone don't convey usage patterns
- LLM agents need context about how to use values (polling, format, relationships)
- Include formats (ISO 8601, URLs, paths) when relevant
- Explain relationships between fields when applicable

## Pattern 4: Missing Recommended Polling Guidance

### Bad Example

```python
# BAD: No guidance on polling patterns
@server.flat_model()
def get_status(input: GetStatusArgs) -> GetStatusResponse:
    """Get current status."""
    ...
```

### Good Example

```python
# GOOD: Includes polling recommendations
@server.flat_model()
def get_status(input: GetStatusArgs) -> GetStatusResponse:
    """Get current status.

    Use this to poll for completion after calling start_process().
    Compare the returned timestamp with the initial value.

    Recommended polling: Every 2-5 seconds until timestamp changes.
    """
    ...
```

**Why it matters**:
- LLM agents need guidance on polling intervals to avoid rate limiting
- Helps agents implement efficient retry logic
- Prevents excessive API calls
- Documents expected completion time ranges

## Detection Strategy

**Primary Method**: Manual code reading of MCP server implementations.

**Discovery aids**:

```bash
# Find response models without Field descriptions
rg --type py "class.*Response.*BaseModel" -A10 adgn/src/adgn/mcp/

# Find tools with redundant schema documentation
rg --type py -B2 -A15 "@server\.(flat_model|tool)" adgn/src/adgn/mcp/ | rg "Returns:"

# Find MCP server implementations
fd -e py "server\.py$" adgn/src/adgn/mcp/
```

**Manual review focus**:
1. Check all response model fields have Field(description=...)
2. Verify descriptions provide context, not just field name rephrasing
3. Ensure docstrings don't duplicate schema structure
4. Check for polling guidance in relevant tool docstrings

## Fix Strategy

1. **Add Field descriptions to response models**:
   ```python
   from pydantic import Field

   field_name: str = Field(description="Helpful description with context")
   ```

2. **Remove redundant "Returns:" sections** from tool docstrings

3. **Enhance field descriptions** with:
   - Expected formats (ISO 8601, URL, path patterns)
   - Usage context (how to use this value)
   - Relationships to other fields
   - Polling patterns when applicable

4. **Add polling guidance** to tool docstrings:
   - Recommended polling intervals
   - What to compare to detect completion
   - Typical completion time ranges

## References

- [Pydantic Field Documentation](https://docs.pydantic.dev/latest/concepts/fields/)
- [JSON Schema Description](https://json-schema.org/understanding-json-schema/reference/generic.html#annotations)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
