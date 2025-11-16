# Scan Results: Vague Field Names

## Summary

This scan identified **field names that are ambiguous or lack sufficient context** to be self-documenting. The scan focused on Python classes (Pydantic models, dataclasses) looking for generic names like `key`, `id`, `name`, `data`, `value`, and `type` that don't clearly indicate their purpose.

**Total instances found: 19** (excluding acceptable uses like discriminators)

The findings are categorized by severity:
- **High Priority (9)**: Very vague names requiring immediate clarification
- **Medium Priority (10)**: Somewhat clear from context but could be more explicit

## High Priority Findings

These fields are particularly ambiguous and should be renamed for clarity.

### 1. Encryption Key Without Context
**File:** `/home/user/ducktape/experimental/webhook_inbox/webhook_inbox.py`
**Line:** 88
**Current:** `key: str | None`

```python
class Config:
    key: str | None  # ??? What kind of key?

    @property
    def fernet(self):
        return Fernet(self.key) if self.key else None
```

**Issue:** The field `key` is used for Fernet encryption, but this isn't clear from the name.
**Suggested fix:** `encryption_key: str | None` or `fernet_key: str | None`

---

### 2. Cache Key in Commit AI
**File:** `/home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py`
**Line:** 629
**Current:** `key: str`

```python
class ProduceMessageInput:
    repo: pygit2.Repository
    model_name: str
    debug: bool
    deadline: timedelta | None
    passthru: list[str]
    diff: str
    previous_message: str | None
    cache: Cache
    key: str  # ??? What kind of key?
```

**Issue:** Used as `inp.cache.get(inp.key)` - clearly a cache key, but the name doesn't indicate this.
**Suggested fix:** `cache_key: str`

---

### 3. External Expense ID
**File:** `/home/user/ducktape/finance/reconcile/external_system.py`
**Line:** 8
**Current:** `id: str`

```python
@dataclasses.dataclass
class ExternalExpense:
    id: str  # ID of what?
    trade_date: datetime.date
    amount: decimal.Decimal
    description: str
```

**Issue:** While the class name provides some context, `id` could be more specific.
**Suggested fix:** `external_expense_id: str` or `expense_id: str`

---

### 4. Message ID in Claude History
**File:** `/home/user/ducktape/experimental/claude-history/claude_history_reader.py`
**Line:** 40
**Current:** `id: str | None`

```python
class MessageContent(BaseModel):
    """Message from user or assistant"""

    id: str | None = None  # ID of what?
    type: str | None = None
    role: str
    model: str | None = None
    content: str | list[TextContent | dict[str, Any]]
```

**Issue:** Unclear what this ID represents - message ID, session ID, etc.
**Suggested fix:** `message_id: str | None` or `claude_message_id: str | None`

---

### 5. Error Data in Protocol
**File:** `/home/user/ducktape/wt/src/wt/shared/protocol.py`
**Line:** 82
**Current:** `data: object | None`

```python
class Error(BaseModel):
    """JSON-RPC 2.0 error object."""

    model_config = {"extra": "forbid"}

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: object | None = Field(default=None, description="Additional error data")  # Vague
```

**Issue:** Generic `data` doesn't indicate it's error-specific additional information.
**Suggested fix:** `error_data: object | None` or `additional_error_data: object | None`

---

### 6. Environment Type-Specific Data
**File:** `/home/user/ducktape/adgn/src/adgn/inop/engine/models.py`
**Line:** 343
**Current:** `data: dict[str, Any]`

```python
@dataclass
class RunnerEnvironment:
    """Environment information from a runner."""

    type: str  # "docker_container", "workspace_dir", etc.
    data: dict[str, Any]  # Type-specific data  ← Vague

    @property
    def container_id(self) -> str | None:
        """Get Docker container ID if this is a container environment."""
        if self.type == "docker_container":
            return self.data.get("container_id")
        return None
```

**Issue:** `data` is too generic. The comment says "type-specific" but doesn't clarify what kind.
**Suggested fix:** `environment_data: dict[str, Any]` or `type_specific_data: dict[str, Any]`

---

### 7. Workspace Document ID
**File:** `/home/user/ducktape/tana/src/tana/io/json.py`
**Line:** 12
**Current:** `id: str`

```python
class WorkspaceDoc(BaseModel):
    id: str  # ID of what?
    props: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")
```

**Issue:** Unclear what this ID represents in the workspace context.
**Suggested fix:** `document_id: str` or `workspace_doc_id: str`

---

### 8. PR Cache Data
**File:** `/home/user/ducktape/wt/src/wt/server/pr_service.py`
**Line:** 30
**Current:** `data: PRData`

```python
@dataclass
class PRCacheOk:
    data: PRData  # What kind of data?
    fetched_at: datetime
```

**Issue:** `data` is vague even though it's typed as PRData.
**Suggested fix:** `pr_data: PRData` or `pull_request_data: PRData`

---

### 9. Behavioral Requirement ID and Name
**File:** `/home/user/ducktape/claude/claude_optimizer/graders/generic_graders.py`
**Lines:** 24-25
**Current:** `id: str` and `name: str`

```python
@dataclass
class BehavioralRequirement:
    """A specific behavioral requirement to evaluate against."""

    id: str  # ID of what?
    name: str  # Name of what?
    description: str
    evaluation_criteria: str
    analysis_prompt_template: str
    function_schema: dict[str, Any]
```

**Issue:** While class context helps, more specific names would be clearer.
**Suggested fix:** `requirement_id: str` and `requirement_name: str`

---

## Medium Priority Findings

These fields have some context from their class or usage, but more explicit naming would improve clarity.

### 10. Tana Node ID and Name
**File:** `/home/user/ducktape/tana/src/tana/domain/nodes.py`
**Lines:** 48 (id), 17 (name)
**Current:** `id: NodeId` and `name: str | None`

```python
class Props(BaseModel):
    """Metadata associated with a Tana node."""

    created: int | None = None
    name: str | None = None  # Name of what?
    doc_type: str | None = Field(alias="_docType", default=None)
    # ... more fields

class BaseNode(BaseModel):
    """Common base model for all Tana nodes."""

    id: NodeId  # The NodeId type helps, but still generic
    props: Props
    children: list[NodeId] = Field(default_factory=list)
```

**Issue:** While `NodeId` type annotation helps for `id`, both could be more explicit.
**Suggested fix:** `node_id: NodeId` and `node_name: str | None`

---

### 11. Habitify Area ID and Name
**File:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines:** 76-77
**Current:** `id: str` and `name: str`

```python
class Area(BaseModel):
    """Model for habit area/category."""

    id: str  # ID of what?
    name: str  # Name of what?
    priority: str | None = None
```

**Issue:** Generic field names in a domain model.
**Suggested fix:** `area_id: str` and `area_name: str`

---

### 12. Habitify Habit ID
**File:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Line:** 106
**Current:** `id: str`

```python
class Habit(BaseModel):
    """Model for habit data from the API based on actual response structure."""

    id: str  # ID of what?
    name: str
    is_archived: bool
    start_date: str
```

**Issue:** Should be more explicit about what the ID represents.
**Suggested fix:** `habit_id: str`

---

### 13. Pollutant Info Name
**File:** `/home/user/ducktape/homeassistant/iaqi/custom_components/indoor_aqi/sensor.py`
**Line:** 41
**Current:** `name: str`

```python
@dataclass
class PollutantInfo:
    """
    Metadata for a single air-quality pollutant.

    Attributes
    ----------
    name
        Display name of the pollutant (e.g., "PM2.5")
    ...
    """

    name: str  # Name of what? Pollutant name!
    unit: str
    breakpoints: list[tuple[float, int]]
```

**Issue:** While the docstring clarifies, the field name should be self-documenting.
**Suggested fix:** `pollutant_name: str`

---

### 14. Tree Node Name
**File:** `/home/user/ducktape/difftree/src/difftree/tree.py`
**Line:** 25
**Current:** `name: str`

```python
@dataclass
class TreeNode:
    """Node in a hierarchical tree of file changes.

    This is a pure data structure - no view concerns like path collapsing.
    Stats (additions, deletions) are aggregated from children.
    """

    name: str  # Component name (e.g., "foo.py" not "dir/foo.py")
    is_file: bool
    additions: int = 0
    deletions: int = 0
```

**Issue:** Comment explains it's a "component name" - that should be the field name.
**Suggested fix:** `component_name: str` or `file_name: str`

---

### 15. Worktree Name
**File:** `/home/user/ducktape/wt/src/wt/server/types.py`
**Line:** 36
**Current:** `name: str`

```python
@dataclass
class Worktree:
    """Filesystem-discovered worktree instance (daemon-internal).

    wtid must be provided by the minting point; do not derive here.
    """

    path: Path
    name: str  # Name of what? Worktree name!
    wtid: WorktreeID
    discovered_at: datetime = field(default_factory=_now, compare=False)
```

**Issue:** Context is somewhat clear, but explicit would be better.
**Suggested fix:** `worktree_name: str`

---

### 16-19. API Key Event IDs and Names
**File:** `/home/user/ducktape/adgn/src/adgn/rspcache/events.py`
**Lines:** 34-35, 41
**Current:** `id: str` and `name: str`

```python
class APIKeyCreatedEvent(EventBase):
    type: Literal["api_key_created"] = "api_key_created"
    id: str  # ID of what?
    name: str  # Name of what?
    upstream_alias: str

class APIKeyRevokedEvent(EventBase):
    type: Literal["api_key_revoked"] = "api_key_revoked"
    id: str  # ID of what?
```

**Issue:** Event-specific IDs and names should be explicit.
**Suggested fix:** `api_key_id: str` and `api_key_name: str`

---

## Acceptable Uses (Not Flagged)

These instances were **NOT** flagged as problematic because they follow standard patterns:

### Discriminator Fields
Many `type` fields with `Literal` values serving as discriminators for unions:
- `/home/user/ducktape/adgn/src/adgn/rspcache/events.py` (lines 12, 16, 24, 33, 40)
- `/home/user/ducktape/wt/src/wt/shared/protocol.py` (lines 197, 202, 207, 379, 384)
- `/home/user/ducktape/gatelet/gatelet/server/config.py` (lines 19, 25)

These are standard discriminated union patterns and are acceptable.

### Status Fields with Type Annotations
Many `status` fields using enums or Literal types:
- `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py` - using `Status` enum
- `/home/user/ducktape/ember/src/ember/app.py` - using Literal types

These are acceptable because the type annotation provides clarity.

---

## Recommendations

### Immediate Actions

1. **Rename high-priority fields** (9 instances) to include context:
   - `key` → `encryption_key`, `cache_key`, etc.
   - `id` → `<entity>_id` (e.g., `expense_id`, `message_id`)
   - `data` → `<type>_data` (e.g., `error_data`, `environment_data`)
   - `name` → `<entity>_name` (e.g., `requirement_name`)

2. **Update call sites** after renaming to maintain consistency throughout the codebase.

3. **Consider medium-priority improvements** (10 instances) during future refactoring.

### Benefits of Fixing

✅ **Self-documenting** - Code readers don't need to infer from context
✅ **Searchable** - `cache_key` is much easier to grep than `key`
✅ **Less ambiguity** - Clear what each field represents
✅ **Better IDE support** - More specific names group logically in autocomplete

### When Vague Names Are Acceptable

- **Function parameters** where the function name provides context (e.g., `def get_user_by_id(id: int)`)
- **Loop variables** with short scope (e.g., `for key, value in items`)
- **Standard conventions** (e.g., discriminator `type` fields with Literal values)
- **Very small, focused classes** where context is immediately obvious

---

## References

- Scan prompt: `/home/user/ducktape/prompts/scans/vague-field-names.md`
- [Google Python Style Guide - Naming](https://google.github.io/styleguide/pyguide.html#s3.16-naming)
- [PEP 8 - Descriptive Naming Styles](https://peps.python.org/pep-0008/#descriptive-naming-styles)
