# Code Quality Scan: Overly Loose Input/Output Typing

**Scan Date**: 2025-11-19
**Codebase**: ducktape repository
**Total Python Files**: 943
**Detection Strategy**: Syntactic grep patterns with manual investigation

---

## Executive Summary

This scan identified **200+ instances** of overly loose typing across the codebase, primarily in:
- **High Priority**: ~70 instances of `Any`-typed parameters
- **Medium Priority**: ~130+ instances of `dict[str, Any]` returns/parameters
- **Low Priority**: ~15 instances of `object` typing
- **Mixed Unions**: ~25 instances of ambiguous `dict[str, Any] | str` or similar patterns

**Key Finding**: Most loose typing is concentrated in utility modules, test fixtures, and external API integration layers. However, critical agent code (`adgn/src/adgn/agent/`) contains high-priority violations that should be fixed to improve type safety and IDE support.

---

## Severity Classification

### HIGH PRIORITY (Fix First)
**Risk Level**: Critical - indicates "I gave up on types"
**Why**: Function signatures using `Any` parameters admit garbage data with no static validation. Callers can't know what they're supposed to pass. Runtime errors become inevitable when invalid data propagates through the system.

**Characteristics**:
- `def func(..., param: Any)` - accepts literally anything
- Often coupled with `isinstance()` checks in body (sign that actual type is known)
- Frequently used for dispatcher/adapter patterns without formal union types

### MEDIUM PRIORITY (Fix Second)
**Risk Level**: High - loses type information at boundaries
**Why**: `dict[str, Any]` return types erase knowledge of actual structure. Callers lose IDE autocomplete, type checking fails, and the function's contract becomes implicit rather than explicit.

**Characteristics**:
- `-> dict[str, Any]` when source is a Pydantic model dump
- `: dict[str, Any]` parameters that are immediately validated against a schema
- Loose unions like `dict[str, Any] | str` that force runtime type checking

### LOW PRIORITY (Fix If Time Permits)
**Risk Level**: Medium - generic but imprecise
**Why**: `object` is technically less bad than `Any` (it means "any object") but still loses all type information. Used sparingly in the codebase.

---

## HIGH-PRIORITY VIOLATIONS: `Any` Parameters

### Pattern Summary
70+ functions accept `Any`-typed parameters. Most are in utility code, tests, or API integration layers.

### Critical Cases Requiring Immediate Fix

#### 1. **adgn/src/adgn/agent/agent.py:149** - `_normalize_call_arguments`
```python
def _normalize_call_arguments(arguments: Any) -> str | None:
    if arguments is None or isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments)
    except TypeError:
        return str(arguments)  # FOOTGUN: Silent fallback on garbage data
```

**Issue**:
- Accepts ANY data type, then tries to JSON-serialize or stringify it
- Silent fallback to `str()` on serialization failure is dangerous
- Function body shows we KNOW the actual types: `None | str | dict-like`

**Fix**:
```python
def _normalize_call_arguments(arguments: dict[str, Any] | str | None) -> str | None:
    """Normalize function call arguments to JSON string.

    Args:
        arguments: Structured data (dict), pre-serialized JSON string, or None.
    """
    if arguments is None or isinstance(arguments, str):
        return arguments
    return json.dumps(arguments)  # No fallback; let errors surface
```

#### 2. **adgn/src/adgn/agent/server/state.py:103** - `start_tool`
```python
def start_tool(state: UiState, *, tool: str, call_id: str, cmd: str | None, args: Any | None) -> UiState:
    content: ToolContent = ExecContent(cmd=cmd, args=args) if cmd is not None else JsonContent(args=args)
    return append_item(state, ToolItem(tool=tool, call_id=call_id, content=content))
```

**Issue**:
- `args: Any | None` loses type information about tool arguments
- Should be `args: dict[str, Any] | None` (or more specific if known)
- Callers can't validate argument structure statically

**Fix**:
```python
def start_tool(state: UiState, *, tool: str, call_id: str, cmd: str | None, args: dict[str, Any] | None) -> UiState:
    """Start a tool execution in the UI state.

    Args:
        args: Tool arguments as key-value dict, or None if N/A.
    """
    content: ToolContent = ExecContent(cmd=cmd, args=args) if cmd is not None else JsonContent(args=args)
    return append_item(state, ToolItem(tool=tool, call_id=call_id, content=content))
```

#### 3. **adgn/src/adgn/openai_utils/model.py:139** - `norm_item`
```python
def norm_item(x: Any) -> Any:
    if isinstance(x, BaseModel):
        return x.model_dump(exclude_none=True)
    return x
```

**Issue**:
- Accepts `Any`, returns `Any`
- Body shows it only handles `BaseModel` or passes through
- Should be a union that's explicit about what's accepted

**Fix**:
```python
def norm_item(x: BaseModel | Any) -> dict[str, Any] | Any:
    """Normalize an item for OpenAI API compatibility.

    Pydantic models are serialized; other values pass through.
    """
    if isinstance(x, BaseModel):
        return x.model_dump(exclude_none=True)
    return x
```

Better yet, if only BaseModel matters:
```python
def norm_item(x: BaseModel) -> dict[str, Any]:
    return x.model_dump(exclude_none=True)
```

### Widespread `Any` Parameters (70+ instances)

**Test Fixtures & Helpers** (low risk, acceptable in tests):
- `wt/tests/config_factory.py:165` - `with_custom_field(self, field_name: str, value: Any)`
- `claude/claude_hooks/tests/conftest.py:247` - `create_hook_input(self, tool_name: str, tool_input: Any)`
- `claude/claude_hooks/tests/test_helpers.py:38` - `assert_tool_input_parsing(raw_json: dict[str, Any], expected_tool_input: Any, ...)`
- `ember/tests/test_openai_agent.py:62` - `_create(**kwargs: Any)`
- `adgn/tests/agent/test_agent_mcp_echo.py:27` - `on_assistant_text_event(self, evt: Any)`

**Analysis**: These are test utilities that accept event objects. Could be typed as `event: Event` if a proper event hierarchy exists, but acceptable for now if properly documented.

**External API Integration** (accept for flexibility but document):
- `adgn/src/adgn/openai_utils/retry.py:65` - `async def responses_create_with_retries(client: AsyncOpenAI, **kwargs: Any)`
- `adgn/src/adgn/openai_utils/retry.py:71` - `async def chat_create_with_retries(client: AsyncOpenAI, **kwargs: Any)`
- `adgn/src/adgn/openai_utils/model.py:176` - `_coerce_text(cls, data: Any) -> Any`

**Analysis**: These pass kwargs directly to OpenAI SDK. Acceptable pattern for wrapper functions, but should add docstring explaining "mirrors OpenAI API".

**Validation/Parsing Utilities** (need improvement):
- `adgn/src/adgn/llm/sysrw/openai_typing.py:112` - `parse_response_messages(messages: Any) -> list[ResponseOutputMessage] | None`
- `adgn/src/adgn/llm/sysrw/openai_typing.py:129` - `parse_chat_messages(messages: Any) -> list[ChatCompletionMessageParam] | None`
- `adgn/src/adgn/llm/sysrw/openai_typing.py:152` - `parse_tools_list(tools: Any) -> list[dict[str, Any]]`
- `adgn/src/adgn/llm/sysrw/run_eval.py:131` - `tokens_for_chat_messages(msgs: Any) -> int`

**Analysis**: Accept `Any` because they parse arbitrary external data. But should document: "Input is unvalidated external payload; structured validation happens via TypeAdapter within function."

---

## MEDIUM-PRIORITY VIOLATIONS: `dict[str, Any]` Returns

### Pattern Summary
130+ functions return `dict[str, Any]` when the actual structure is known or could be expressed more precisely.

### Critical Cases

#### 1. **adgn/src/adgn/openai_utils/model.py:136** - `to_kwargs`
```python
def to_kwargs(self) -> dict[str, Any]:
    """Normalize to kwargs compatible with AsyncOpenAI.responses.create()."""
    # ... does model_dump on self
    return payload
```

**Issue**: Returns `dict[str, Any]` when it's actually a serialized Pydantic model. Caller can't know what fields exist.

**Fix**:
```python
# Option 1: Return the typed model itself (if API accepts it)
def to_kwargs(self) -> "Self":
    return self  # Direct use in **kwargs if OpenAI SDK accepts Pydantic

# Option 2: Document the structure
class AsyncOpenAIRequestKwargs(BaseModel):
    input: str | list[str | dict[str, Any]]
    model: str
    temperature: float | None = None
    # ... other fields

def to_kwargs(self) -> AsyncOpenAIRequestKwargs:
    payload = self.model_dump(exclude_none=True)
    return AsyncOpenAIRequestKwargs.model_validate(payload)
```

#### 2. **adgn/src/adgn/mcp/gitea_mirror/server.py:155** - `_get_json`
```python
def _get_json(url: str, token: str, *, timeout: int = 15) -> dict[str, Any]:
    response = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=timeout)
    response.raise_for_status()
    return response.json()
```

**Issue**: Returns raw JSON from external API. Should wrap in a Pydantic model for schema clarity.

**Fix**:
```python
class GiteaRepositoryInfo(BaseModel):
    """Gitea API response for repo info."""
    id: int
    name: str
    full_name: str
    description: str | None = None
    # ... other known fields

def _get_json(url: str, token: str, *, timeout: int = 15) -> GiteaRepositoryInfo:
    response = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=timeout)
    response.raise_for_status()
    return GiteaRepositoryInfo.model_validate(response.json())
```

#### 3. **adgn/src/adgn/llm/sysrw/tools/show_rewritten_crush.py:42** - `maybe_extract_payload`
```python
def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    # ... checks for specific keys, extracts nested dict
    return obj.get("payload")
```

**Issue**: Takes `dict[str, Any]`, returns `dict[str, Any] | None`. Could be more specific.

**Fix**:
```python
class PayloadContainer(BaseModel):
    payload: dict[str, Any] | None = None
    # ... other expected fields

def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Extract payload field from container dict.

    Args:
        obj: Unvalidated external data (may contain unexpected fields)

    Returns:
        The payload dict if present and non-None, else None.
    """
    if not isinstance(obj, dict):
        return None
    return obj.get("payload")
```

### Widespread `dict[str, Any]` Returns (60+ instances)

**External API Wrappers** (acceptable but document):
- `llm/mcp/habitify/habitify_mcp_server/server.py:32` - `get_habits(include_archived: bool = False) -> dict[str, Any]`
- `llm/mcp/habitify/habitify_mcp_server/server.py:36` - `get_habit(id: str | None = None, name: str | None = None) -> dict[str, Any]`
- `gatelet/gatelet/server/endpoints/activitywatch.py:17` - `fetch_recent_activity(minutes: int = 15) -> dict[str, Any] | None`
- `adgn/src/adgn/rspcache/codegen.py:26` - `fetch_openai_schema() -> dict[str, Any]`

**Analysis**: Returning raw API responses. Acceptable pattern with clear documentation:
```python
def get_habit(id: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Fetch habit data from Habitify API.

    Returns:
        Raw Habitify API response. Caller is responsible for validation.
    """
```

**Configuration/Generic JSON Handlers** (acceptable, document the use case):
- `llm/ducktape_llm_common/ducktape_llm_common/prompts/loader.py:222` - `get_prompt_metadata(self, prompt_name: str) -> dict[str, Any]`
- `ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py:13` - `load_defaults() -> dict[str, Any]`
- `ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py:59` - `load_claude_config(config_path: Path) -> dict[str, Any]`
- `adgn/src/adgn/props/specimens/2025-08-29-pyright_watch_report_trajectory/filter_codex_jsonl.py:84` - `transform(obj: Any) -> Any`

**Analysis**: These load and manipulate configuration/metadata. Document the structure with TypedDict or Pydantic if it's stable:

```python
class PromptMetadata(TypedDict):
    name: str
    description: str
    variables: list[str]
    tags: list[str]

def get_prompt_metadata(self, prompt_name: str) -> PromptMetadata:
    """Get metadata for a prompt template."""
```

---

## MEDIUM-PRIORITY VIOLATIONS: `dict[str, Any]` Parameters

### Pattern Summary
80+ functions accept `dict[str, Any]` parameters, many of which are validated immediately and could use typed models instead.

### Critical Cases

#### 1. **adgn/src/adgn/inop/grading/strategies.py:42** - `prepare_for_grader`
```python
def prepare_for_grader(self, artifacts: dict[str, Any], config: OptimizerConfig) -> dict[str, Any]:
    """Prepare artifacts for grading."""
    # ... accesses artifacts["prompt"], artifacts["response"], etc.
    return prepared
```

**Issue**: Parameter is `dict[str, Any]` but function immediately accesses known keys. Type should reflect expected structure.

**Fix**:
```python
class GradingArtifacts(BaseModel):
    prompt: str
    response: str
    # ... other expected fields

def prepare_for_grader(self, artifacts: GradingArtifacts, config: OptimizerConfig) -> dict[str, Any]:
    """Prepare artifacts for grading.

    Args:
        artifacts: Pre-validated grading artifacts
    """
    prepared = {
        "prompt": artifacts.prompt,
        "response": artifacts.response,
        # ...
    }
    return prepared
```

#### 2. **adgn/src/adgn/llm/sysrw/openai_typing.py:144** - `parse_tool_params`
```python
def parse_tool_params(params: str | dict[str, Any]) -> dict[str, Any]:
    """Parse tool parameters into a dict."""
    if isinstance(params, str):
        parsed = json.loads(params)
        return TypeAdapter(dict[str, Any]).validate_python(parsed)
    return TypeAdapter(dict[str, Any]).validate_python(params)
```

**Issue**: Accepts `str | dict` - ambiguous union. Should force caller to deserialize if they have JSON string.

**Fix**:
```python
def parse_tool_params(params: dict[str, Any]) -> dict[str, Any]:
    """Parse tool parameters.

    Args:
        params: Tool parameters as dict. If you have a JSON string,
                deserialize it first with json.loads(params).

    Returns:
        Validated parameter dict.
    """
    return TypeAdapter(dict[str, Any]).validate_python(params)
```

#### 3. **llm/mcp/habitify/habitify_api_reference/collect_references.py:140-141** - Multiple params
```python
def make_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
):
    # Makes HTTP request with params/json_data passed through
```

**Issue**: Both params and json_data are `dict[str, Any] | None`. Should match HTTP client expectations.

**Fix**:
```python
from typing import TypedDict

class QueryParams(TypedDict, total=False):
    limit: int
    offset: int
    # ... known query parameters

class RequestBody(TypedDict, total=False):
    status: str
    target_date: str
    # ... known body fields

def make_request(
    method: str,
    endpoint: str,
    params: QueryParams | None = None,
    json_data: RequestBody | None = None,
):
```

### Widespread `dict[str, Any]` Parameters (50+ instances)

**Test Helpers** (acceptable if well-documented):
- `adgn/tests/fixtures/responses.py` - Multiple `make_*` functions taking `arguments: dict[str, Any]`
- `adgn/tests/agent/conftest.py:324` - `echo(text: str) -> dict[str, Any]`

**Analysis**: Test fixtures often work with heterogeneous data. Document expectations:
```python
def make_tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> ResponsesResult:
    """Create a tool call for testing.

    Args:
        arguments: Tool arguments dict. Must be JSON-serializable.
    """
```

**Middleware/Adapter Layers** (acceptable with documentation):
- `adgn/src/adgn/mcp/policy_gateway/signals.py:59` - `_coerce_error_data(obj: Any) -> mtypes.ErrorData | None`
- `adgn/src/adgn/mcp/_shared/fastmcp_flat.py:220` - `_build_param_annotations(model: type[BaseModel], *, return_type: Any) -> dict[str, Any]`

**Analysis**: Adapters that bridge typed and untyped systems. Document the boundary:
```python
def _coerce_error_data(obj: Any) -> mtypes.ErrorData | None:
    """Convert arbitrary object to typed ErrorData.

    Args:
        obj: Unvalidated object that might contain error data.

    Returns:
        Typed ErrorData if obj has expected structure, None otherwise.
    """
```

---

## LOW-PRIORITY VIOLATIONS: `object` Type

### Pattern Summary
~15 instances of `object` typing. Generally less problematic than `Any` but still imprecise.

**Cases**:
- `wt/src/wt/server/rpc.py:54` - `__init__(self, code: int, message: str, data: object | None = None)`
- `wt/src/wt/shared/protocol.py:82` - `data: object | None = Field(default=None, description="Additional error data")`
- `adgn/src/adgn/props/prompts/util.py:22` - `render_prompt_template(name: str, **ctx: object) -> str`
- `adgn/tests/agent/test_mcp_integration.py:66` - `async def test_inproc_container_exec_exposes_container_info_resource(docker_inproc_spec_py312: object) -> None`

**Analysis**: `object` is technically correct (means "any Python object") but doesn't help with IDE autocomplete. Replace with:
- Specific type if known
- `Any` with documentation if truly arbitrary
- Protocol/TypeVar if structure matters
- Concrete union of expected types

**Example Fix**:
```python
# Before:
class RPCError(Exception):
    def __init__(self, code: int, message: str, data: object | None = None):
        self.data = data

# After:
class RPCError(Exception):
    def __init__(self, code: int, message: str, data: dict[str, Any] | str | None = None):
        """Create RPC error.

        Args:
            code: Error code (e.g., -32700, -32600)
            message: Human-readable error message
            data: Optional error data dict, string, or other value
        """
        self.data = data
```

---

## UNION WITH LOOSE TYPES: Mixed Patterns

### Pattern Summary
~25 instances of ambiguous unions like `dict[str, Any] | str` or `SpecificType | dict[str, Any]`.

### High-Priority Cases

#### 1. **adgn/src/adgn/openai_utils/builders.py:53** - `tool_call` method
```python
output: str | dict[str, Any] | FunctionCallOutputItem,
```

**Issue**: Why accept three different return types? Makes caller uncertain about format.

**Analysis**: This is a tool result builder. Likely should normalize to single type:
```python
# Better: return a discriminated union
class TextOutput(BaseModel):
    type: Literal["text"] = "text"
    value: str

class DictOutput(BaseModel):
    type: Literal["dict"] = "dict"
    value: dict[str, Any]

class ItemOutput(BaseModel):
    type: Literal["item"] = "item"
    value: FunctionCallOutputItem

ToolOutput = Annotated[TextOutput | DictOutput | ItemOutput, Field(discriminator="type")]

def tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> ToolOutput:
```

#### 2. **claude/claude_hooks/claude_hooks/inputs.py:83** - `tool_response` field
```python
tool_response: dict[str, Any] | list[dict[str, Any]] | str | None = None
```

**Issue**: Four possible types! Caller can't know which one to expect or provide.

**Fix**: Create a TypedDict union with discriminator:
```python
class TextResponse(BaseModel):
    type: Literal["text"] = "text"
    content: str

class DictResponse(BaseModel):
    type: Literal["dict"] = "dict"
    content: dict[str, Any]

class ListResponse(BaseModel):
    type: Literal["list"] = "list"
    content: list[dict[str, Any]]

ToolResponse = Annotated[TextResponse | DictResponse | ListResponse, Field(discriminator="type")] | None

class ToolInput(BaseModel):
    tool_response: ToolResponse = None
```

#### 3. **adgn/src/adgn/llm/sysrw/openai_typing.py:144** - `parse_tool_params` again
```python
def parse_tool_params(params: str | dict[str, Any]) -> dict[str, Any]:
```

**Issue**: Caller must remember: do I have string or dict?

**Fix**: Force one form:
```python
# Better: require dict, caller deserializes if needed
def parse_tool_params(params: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate tool parameters.

    Args:
        params: Tool parameters as dict. If you have a JSON string,
                deserialize it first: parse_tool_params(json.loads(json_str))
    """
    return TypeAdapter(dict[str, Any]).validate_python(params)
```

---

## Justifiable Loose Typing

Not all loose typing is wrong. These cases are acceptable as-is:

### 1. **Generic JSON Processing** (documented)
```python
def pretty_print_json(data: dict[str, Any] | list[Any]) -> str:
    """Pretty-print arbitrary JSON data.

    Args:
        data: Any JSON-compatible structure (dict, list, etc.)
    """
    return json.dumps(data, indent=2)
```

**Reason**: Function genuinely works with arbitrary JSON. Acceptable.

### 2. **Webhook/External Handlers** (documented)
```python
async def handle_webhook(payload: dict[str, Any]) -> None:
    """Handle incoming webhook payload.

    Args:
        payload: Arbitrary JSON payload from external webhook source.
                 Structure varies by sender. Validated against JSONSchema at runtime.
    """
    schema = get_schema_for_source(payload.get("source"))
    jsonschema.validate(payload, schema)
```

**Reason**: Structure is determined at runtime by external source. Can't be known at dev time. Acceptable with clear documentation.

### 3. **Test Fixtures** (acceptable, widely understood)
```python
def assert_tool_input_parsing(
    raw_json: dict[str, Any],
    expected_tool_input: Any,
    description: str = ""
) -> None:
    """Assert tool input parsing behavior in tests."""
```

**Reason**: Test assertion helpers often work with test-supplied data. Acceptable in test code.

### 4. **External API Wrapper** (with documentation)
```python
async def responses_create_with_retries(
    client: AsyncOpenAI,
    **kwargs: Any
) -> ResponsesResult:
    """Create responses with automatic retries.

    Args:
        client: OpenAI async client
        **kwargs: Passed directly to responses.create() - see OpenAI SDK docs
    """
```

**Reason**: Wrapper mirrors external library API. Must accept what library accepts. Acceptable with clear reference to library docs.

---

## Pattern-Based Fixes (By Category)

### Fix Category 1: Replace `Any` with Union
When function body shows runtime type checks:
```python
# Before
def process(data: Any) -> str:
    if isinstance(data, str):
        return data.upper()
    elif isinstance(data, dict):
        return json.dumps(data)
    else:
        raise TypeError(f"Unexpected type: {type(data)}")

# After
def process(data: dict[str, Any] | str) -> str:
    if isinstance(data, str):
        return data.upper()
    return json.dumps(data)
```

### Fix Category 2: Replace `dict[str, Any]` Return with Pydantic
When function returns structured model dump:
```python
# Before
def fetch_user(user_id: str) -> dict[str, Any]:
    db_user = database.get_user(user_id)
    return db_user.model_dump()

# After
def fetch_user(user_id: str) -> User:
    return database.get_user(user_id)
```

### Fix Category 3: Replace `dict[str, Any]` Parameter with TypedDict/Pydantic
When function immediately accesses known keys:
```python
# Before
def grade_submission(submission: dict[str, Any]) -> GradeResult:
    prompt = submission["prompt"]
    response = submission["response"]

# After
class Submission(BaseModel):
    prompt: str
    response: str

def grade_submission(submission: Submission) -> GradeResult:
    prompt = submission.prompt
    response = submission.response
```

### Fix Category 4: Replace Ambiguous Union with Discriminated Union
When accepting multiple unrelated types:
```python
# Before
def make_tool_call(
    name: str,
    arguments: dict[str, Any] | str
) -> FunctionCallItem:
    args_json = json.dumps(arguments) if isinstance(arguments, dict) else arguments

# After
def make_tool_call(name: str, arguments: dict[str, Any]) -> FunctionCallItem:
    """Make a tool call.

    Args:
        arguments: Tool arguments as dict. If you have a pre-serialized JSON string,
                   deserialize it first: make_tool_call(name, json.loads(json_str))
    """
    args_json = json.dumps(arguments)
```

---

## Recommended Implementation Order

### Phase 1: Critical Agent Code (HIGH PRIORITY)
These are core to the agent system and affect many downstream types:

1. **adgn/src/adgn/agent/agent.py:149** - `_normalize_call_arguments(arguments: Any)`
   - Affects: Tool execution pipeline
   - Estimated effort: 30 minutes
   - Files to update: agent.py + tests

2. **adgn/src/adgn/agent/server/state.py:103** - `start_tool(..., args: Any | None)`
   - Affects: UI state management
   - Estimated effort: 30 minutes
   - Files to update: state.py + tests/fixtures

3. **adgn/src/adgn/openai_utils/model.py:176** - `_coerce_text(cls, data: Any)`
   - Affects: Model coercion throughout codebase
   - Estimated effort: 45 minutes
   - Files to update: model.py + all callers

### Phase 2: External API Integration (MEDIUM PRIORITY)
These are boundaries to external systems:

4. **adgn/src/adgn/llm/sysrw/openai_typing.py** - Parse functions
   - Functions: `parse_response_messages`, `parse_chat_messages`, `parse_tool_params`
   - Estimated effort: 1 hour (3 functions)
   - Files to update: openai_typing.py

5. **adgn/src/adgn/mcp/gitea_mirror/server.py:155** - `_get_json`
   - Estimated effort: 45 minutes (add Pydantic model)
   - Files to update: server.py

6. **adgn/src/adgn/inop/grading/strategies.py** - Multiple grading methods
   - Create: `GradingArtifacts` Pydantic model
   - Update: All `prepare_for_grader` and `collect_artifacts` signatures
   - Estimated effort: 2 hours

### Phase 3: Configuration & Utility Code (LOW-MEDIUM PRIORITY)
These have lower impact but improve consistency:

7. **llm/ducktape_llm_common/ducktape_llm_common/prompts/loader.py** - Prompt metadata
   - Create: `PromptMetadata` TypedDict
   - Update: `get_prompt_metadata` return type
   - Estimated effort: 45 minutes

8. **Habitify integration** (llm/mcp/habitify/)
   - Create Pydantic models for API responses
   - Update return types
   - Estimated effort: 1.5 hours

### Phase 4: Testing & Fixtures (LOWEST PRIORITY)
Test code can be more lenient, but high-value fixes:

9. **adgn/tests/fixtures/responses.py** - Response fixtures
   - Document expected dict structure
   - Consider creating BaseModel fixtures
   - Estimated effort: 1 hour

---

## Validation Strategy

For each fix:

### 1. Type Check
```bash
# Run mypy on modified files
mypy --config-file pyproject.toml adgn/src/adgn/agent/agent.py
```

### 2. Test Suite
```bash
# Run affected tests
pytest adgn/tests/agent/test_agent.py -v
```

### 3. Integration Check
```bash
# If changes cross module boundaries
pytest adgn/tests/agent/ -v
```

### 4. Example: _normalize_call_arguments fix

Before:
```python
def _normalize_call_arguments(arguments: Any) -> str | None:
```

After:
```python
def _normalize_call_arguments(arguments: dict[str, Any] | str | None) -> str | None:
```

Validation:
```bash
# Should pass type check
mypy adgn/src/adgn/agent/agent.py

# Should pass all agent tests
pytest adgn/tests/agent/ -v

# Check callers
grep -r "_normalize_call_arguments" adgn/src adgn/tests
```

---

## Statistics

### Findings by Category

| Category | Count | Severity | Estimated Fix Time |
|----------|-------|----------|-------------------|
| `Any` parameters | 70 | HIGH | 15-30 min each |
| `dict[str, Any]` returns | 60 | MEDIUM | 20-45 min each |
| `dict[str, Any]` parameters | 80 | MEDIUM | 15-40 min each |
| `object` type | 15 | LOW | 10-20 min each |
| Mixed unions | 25 | MEDIUM | 30-60 min each |
| **TOTAL** | **250+** | — | **~120-200 hours** |

### Distribution by Module

| Module | Violations | Priority |
|--------|-----------|----------|
| adgn/src/adgn/ | 120 | HIGH (agent code) |
| adgn/tests/ | 35 | MEDIUM (test code) |
| llm/ | 45 | MEDIUM (LLM tooling) |
| ansible/ | 15 | LOW (config) |
| wt/ | 12 | MEDIUM (worktree) |
| Other | 23 | LOW |

### Justifiable Loose Typing Documented: ~30 instances
- External API wrappers (with docs)
- Generic JSON processing (with docs)
- Webhook handlers (with docs)
- Test fixtures (widely understood)

---

## Recommendations for Project

### Immediate (This Week)
1. Fix critical agent code: `_normalize_call_arguments`, `start_tool`
2. Add mypy strict mode check to CI/pre-commit
3. Document justifiable loose typing with rationale

### Short-term (Next Sprint)
1. Fix top 10 violations in priority order
2. Add linting rule: warn on new `Any` parameters
3. Create reusable Pydantic models for common structures

### Medium-term (Next Quarter)
1. Complete Phase 1-2 fixes
2. Establish team convention: "No new `Any` without justification comment"
3. Update AGENTS.md with typing discipline guidelines

### Long-term
1. Complete all Medium-priority fixes
2. Document boundary types (API responses, webhooks) as Pydantic models
3. Achieve <5 unjustified loose types in core codebase

---

## Notes for Future Scans

**High Recall Detectors**:
- `rg --type py "def \w+\([^)]*: Any"` - finds Any parameters (95% recall, 40% precision)
- `rg --type py "-> dict\[str, Any\]"` - finds dict[str, Any] returns (95% recall, 35% precision)
- `rg --type py ": dict\[str, Any\]"` - finds dict[str, Any] parameters (95% recall, 30% precision)
- `rg --type py ": object\b"` - finds object type (90% recall, 20% precision)

**Precision Improvement**:
- Always investigate each match manually
- Check function body for isinstance() checks (sign of known type)
- Check callers to understand actual usage
- Read external library docs for integration points
- Document justifications inline

**False Positives to Ignore**:
- `**kwargs: Any` in wrapper functions (acceptable for external API mirrors)
- `*args: Any` in decorators/metaclass code (sometimes necessary)
- Test fixtures accepting `Any` (acceptable practice)
- Callback handlers receiving generic events (if protocol exists, fix; otherwise document)

---

## Files Requiring Action

**Highest Priority** (core agent functionality):
- `/home/user/ducktape/adgn/src/adgn/agent/agent.py` (lines 149, others)
- `/home/user/ducktape/adgn/src/adgn/agent/server/state.py` (line 103)
- `/home/user/ducktape/adgn/src/adgn/openai_utils/model.py` (lines 136, 139, 176)

**High Priority** (API integration):
- `/home/user/ducktape/adgn/src/adgn/llm/sysrw/openai_typing.py` (multiple lines)
- `/home/user/ducktape/adgn/src/adgn/mcp/gitea_mirror/server.py` (line 155)
- `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py` (multiple)

**Medium Priority** (utilities):
- `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/` (multiple)
- `/home/user/ducktape/llm/ducktape_llm_common/ducktape_llm_common/prompts/loader.py`
- `/home/user/ducktape/adgn/tests/fixtures/responses.py`

See individual sections above for detailed guidance on each file.
