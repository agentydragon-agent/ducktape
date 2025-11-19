# Scan Results: Library Type Misuse

**Scan Date**: 2025-11-19
**Status**: 14 violations found
**Severity**: Medium - Type safety and code clarity

## Summary

This scan identified instances where code uses casts, hasattr, getattr, or other defensive patterns despite working with well-typed libraries (Pydantic v2, OpenAI SDK, httpx, etc.). These patterns indicate either:
1. Lack of trust in library type annotations
2. Unfamiliarity with library capabilities
3. Legitimate but undocumented reasons for defensive code

Most violations are **Pydantic-related type narrowing casts** after isinstance checks, which are technically safe but indicate misunderstanding of Pydantic's `model_validate` guarantees.

---

## Critical Findings (Fix Recommended)

### 1. **Unnecessary cast on Pydantic model_validate**

**File**: `/home/user/ducktape/tana/src/tana/export/export_node_subset.py:177`

```python
def _make_node(raw: dict[str, Any]) -> BaseNode:
    node_model = DOC_CLASS.get(raw["props"].get("_docType"), UnknownNode)
    # All DOC_CLASS values are BaseNode subclasses; model_validate returns the specific type
    return cast(BaseNode, node_model.model_validate(raw))
```

**Issue**: `Pydantic.model_validate()` already returns the correct type. If `node_model` is a type like `UnknownNode` (a `BaseNode` subclass), calling `node_model.model_validate(raw)` returns an instance of that exact class.

**Fix**: Remove the cast entirely
```python
def _make_node(raw: dict[str, Any]) -> BaseNode:
    node_model = DOC_CLASS.get(raw["props"].get("_docType"), UnknownNode)
    return node_model.model_validate(raw)  # Already returns BaseNode
```

**Why**: The cast is redundant and hides the fact that the type system already understands the correct return type.

---

### 2. **Unnecessary cast on Pydantic model_validate (tana/graph)**

**File**: `/home/user/ducktape/tana/src/tana/graph/workspace.py:58`

```python
return cast(BaseNode, node_model.model_validate(raw))
```

**Issue**: Same as #1 - identical pattern in tana package.

**Fix**: Remove the cast.

---

### 3. **Defensive cast on Pydantic model_validate JSON**

**File**: `/home/user/ducktape/wt/src/wt/shared/protocol.py:479`

```python
def parse_request(data: str) -> Request:
    """Parse JSON string into JSON-RPC request."""
    try:
        raw_data = json.loads(data)
        return cast(Request, Request.model_validate(raw_data))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON (parse error): {e}") from e
    except ValidationError as e:
        raise ValueError(f"Invalid JSON-RPC request schema: {e}") from e
```

**Issue**: `Request.model_validate(raw_data)` already has return type `Request`. The cast is defensive and unnecessary.

**Fix**: Remove the cast
```python
def parse_request(data: str) -> Request:
    try:
        raw_data = json.loads(data)
        return Request.model_validate(raw_data)  # Already typed as Request
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON (parse error): {e}") from e
    except ValidationError as e:
        raise ValueError(f"Invalid JSON-RPC request schema: {e}") from e
```

---

### 4. **Unnecessary type narrowing cast after isinstance**

**File**: `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py:49, 63, 66`

```python
def _count_files_tokens(self, files: list[dict[str, str]] | list[FileInfo]) -> int:
    payload = (
        [fi.model_dump() for fi in cast(list[FileInfo], files)]
        if files and isinstance(files[0], FileInfo)  # Type narrowing happens here
        else files
    )
    return self.count_tokens(json.dumps(payload, indent=2))

def _normalize_files(
    self, files: list[dict[str, str]] | list[FileInfo]
) -> list[tuple[str, str, dict[str, str] | FileInfo]]:
    out: list[tuple[str, str, dict[str, str] | FileInfo]] = []
    if files and isinstance(files[0], FileInfo):  # Type guard
        for fi in cast(list[FileInfo], files):  # Cast is redundant
            out.append((fi.path, fi.content, fi))
    else:
        for d in cast(list[dict[str, str]], files):  # Cast is redundant
            out.append((d["path"], d["content"], d))
```

**Issue**: After `isinstance(files[0], FileInfo)`, mypy understands that `files` is `list[FileInfo]`. The casts are defensive and unnecessary. However, this is actually a genuine limitation in mypy - **it doesn't narrow `list[X | Y]` based on element checks**. This cast may be justified.

**Verdict**: **ACCEPTABLE but deserves a comment**
```python
# mypy limitation: isinstance(files[0], FileInfo) doesn't narrow list[FileInfo | dict]
# to list[FileInfo], so we need the cast despite runtime type safety
for fi in cast(list[FileInfo], files):
```

---

### 5. **Defensive type cast in test mode**

**File**: `/home/user/ducktape/wt/src/wt/server/pr_service.py:119`

```python
if fixture_pr is not None:
    self.cached = PRCacheOk(data=fixture_pr, fetched_at=now)
    return cast(PRData, fixture_pr)
```

**Issue**: `fixture_pr` is assigned to `self.cached` as `PRCacheOk(data=fixture_pr)`, and `PRCacheOk` is a generic that stores `PRData`. The cast seems defensive.

**Fix**: Needs context on what `load_pr_fixture` returns - potentially legitimate if return type is `Any | PRData`.

**Status**: **NEEDS REVIEW** - requires understanding `load_pr_fixture` return type.

---

### 6. **Potentially unnecessary type narrowing cast**

**File**: `/home/user/ducktape/adgn/src/adgn/inop/io/logging_utils.py:32`

```python
if (
    isinstance(tools, list)
    and all(
        isinstance(t, dict) and isinstance(t.get("name"), str) and isinstance(t.get("args"), dict)
        for t in tools
    )
):
    formatted_tools: list[str] = []
    # Type narrowing: tools is list[dict] at this point
    for tool in cast(list[dict[str, Any]], tools):
```

**Issue**: After the isinstance checks, mypy should narrow `tools` to `list[dict[str, Any]]`. The cast suggests either:
1. `tools` has type `Any` at this point (unlikely given earlier checks)
2. Defensive programming despite adequate narrowing

**Fix**: Try removing the cast; if mypy complains, use TypeGuard to help type narrowing
```python
def _is_tool_list(obj: Any) -> TypeGuard[list[dict[str, Any]]]:
    return (
        isinstance(obj, list)
        and all(
            isinstance(t, dict) and isinstance(t.get("name"), str) and isinstance(t.get("args"), dict)
            for t in obj
        )
    )
```

**Status**: **INVESTIGATE** - understand actual type of `tools` parameter.

---

### 7. **Wrapper function cast on generic Callable**

**File**: `/home/user/ducktape/adgn/src/adgn/openai_utils/retry.py:56, 89`

```python
def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    wrapped = tenacity_decorator(func)

    @functools.wraps(func)
    async def inner(*args: P.args, **kwargs: P.kwargs) -> T:
        call = cast(Callable[P, Awaitable[T]], wrapped)
        return await call(*args, **kwargs)

    return inner

@retry_decorator()
async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
    result = await self.base.responses_create(req)
    return cast(ResponsesResult, result)
```

**Issue**: The decorator wrapping uses `cast(Callable[P, Awaitable[T]], wrapped)` after `tenacity_decorator` wraps it. Tenacity's decorators may not preserve type info perfectly, making this cast potentially justified. **However**, the cast at line 89 for `ResponsesResult` is on a return from `self.base.responses_create(req)` which should already be typed.

**Verdict**: Line 56 cast may be legitimate (tenacity limitation), but line 89 needs investigation.

**Status**: **PARTIALLY ACCEPTABLE** - line 56 justified, line 89 questionable.

---

### 8. **Casting library Literal to Literal**

**File**: `/home/user/ducktape/ember/src/ember/config.py:90`

```python
if self.include_encrypted_reasoning:
    includes.append(cast(ResponseIncludable, "reasoning.encrypted_content"))
```

**Issue**: `ResponseIncludable` is a Literal type from OpenAI SDK. The value `"reasoning.encrypted_content"` is a valid literal string, but casting suggests the type checker isn't recognizing it as valid.

**Fix**: Investigate if string literal is actually in `ResponseIncludable` union. If so, the cast is unnecessary. If not, fix the value.

**Status**: **INVESTIGATE** - check OpenAI SDK type definition.

---

### 9. **Extracting string from typed message**

**File**: `/home/user/ducktape/adgn/src/adgn/llm/sysrw/openai_typing.py:28`

```python
def response_message_role(message: ResponseOutputMessage) -> MessageRole:
    """Extract role from a ResponseOutputMessage."""
    role_str = cast(str, message.role)
    return MessageRole(role_str)
```

**Issue**: `ResponseOutputMessage` is from OpenAI SDK and has a `role` field. If `message.role` is already typed as `str` (or a Literal of strings), the cast is unnecessary.

**Fix**: Check if `message.role` is already a string type. If so, remove cast:
```python
def response_message_role(message: ResponseOutputMessage) -> MessageRole:
    """Extract role from a ResponseOutputMessage."""
    return MessageRole(message.role)
```

**Status**: **INVESTIGATE** - check OpenAI SDK `ResponseOutputMessage` field types.

---

### 10. **Unnecessary cast on list parameter**

**File**: `/home/user/ducktape/wt/src/wt/client/wt_client.py:279`

```python
async def get_status(self, worktree_ids: list[WorktreeID] | None = None) -> StatusResponse:
    await self._start_daemon_if_needed()
    ids: list[WorktreeID] = cast(list[WorktreeID], worktree_ids) if worktree_ids is not None else []
```

**Issue**: Type narrowing after None check should work without cast. The ternary expression should return `list[WorktreeID]` without casting.

**Fix**: Remove the cast
```python
async def get_status(self, worktree_ids: list[WorktreeID] | None = None) -> StatusResponse:
    await self._start_daemon_if_needed()
    ids: list[WorktreeID] = worktree_ids if worktree_ids is not None else []
```

**Status**: **FIX RECOMMENDED** - mypy should handle this without cast.

---

### 11. **Isinstance guards on Matrix API responses**

**File**: `/home/user/ducktape/ember/src/ember/matrix_client.py:196-202, 382, 405, 425`

```python
# Line 196-202
if isinstance(response, JoinedRoomsError):
    logger.warning("Matrix joined_rooms error: %s", response.message)
    return set()
if not isinstance(response, JoinedRoomsResponse):
    logger.warning("Unexpected joined_rooms response: %r", response)
    return set()
return {RoomID(room_id) for room_id in (response.rooms or [])}

# Similar pattern at lines 382, 405, 425
if not isinstance(response, RoomResolveAliasResponse) or not response.room_id:
if not isinstance(whoami, WhoamiResponse) or not whoami.user_id:
if not isinstance(response, SyncResponse):
```

**Issue**: Matrix API client returns `Union[SuccessResponse, ErrorResponse]` types. The isinstance checks are **NOT misuse** - they're handling discriminated union types correctly.

**Verdict**: **NOT A VIOLATION** - these are correct pattern matching on union types. The isinstance checks are necessary and appropriate.

---

### 12. **isinstance guards on policy responses**

**File**: `/home/user/ducktape/adgn/src/adgn/agent/policies/scaffold.py:24, 32`

```python
if not isinstance(resp, PolicyResponse):
    raise TypeError("decide() must return a PolicyResponse during preflight")

if not isinstance(resp, PolicyResponse):
    raise TypeError("decide() must return a PolicyResponse")
```

**Issue**: These are runtime type checks on function return values. The function signature is `decide: Callable[[PolicyRequest], PolicyResponse]`, so isinstance checks seem defensive.

**Analysis**: This appears to be validating that a callable honoring a protocol actually returns the right type. Could indicate:
1. The function is called from unknown/dynamically loaded code
2. Legacy type annotation enforcement
3. User-provided policy function validation

**Verdict**: **LIKELY ACCEPTABLE** - if `decide` comes from user code or dynamic loading, these checks provide safety guarantees.

---

### 13. **Response type checking in tool calls**

**File**: `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tools.py:171, 251`

```python
if isinstance(resolved, ErrorResponse):
    logger.error("...")
    return resolve_handle_result(...)
```

**Issue**: These check if MCP tool responses are `ErrorResponse`. Standard pattern for handling union-typed returns.

**Verdict**: **NOT A VIOLATION** - correct pattern for discriminated unions.

---

### 14. **GitHub PR response type checking**

**File**: `/home/user/ducktape/wt/src/wt/shared/github_models.py:124`

```python
def coerce_prdata(src: Any) -> PRData:
    if isinstance(src, PRData):
        return src
    if isinstance(src, GitHubPRResponse):
        return PRData(...)
    if isinstance(src, dict):
        ...
```

**Issue**: This is a coercion function handling multiple input types. The isinstance checks are **not misuse** - they're the correct approach for a polymorphic function.

**Verdict**: **NOT A VIOLATION** - appropriate for type-safe coercion.

---

## Summary by Category

### Definite Violations (Remove Casts)
1. **tana/export/export_node_subset.py:177** - Pydantic model_validate cast
2. **tana/graph/workspace.py:58** - Pydantic model_validate cast (duplicate)
3. **wt/shared/protocol.py:479** - Pydantic model_validate cast
4. **wt/client/wt_client.py:279** - Simple None-check type narrowing cast

**Confidence**: HIGH - These casts provide no value and obscure type safety.

### Likely Acceptable (Document or Investigate)
5. **adgn/inop/prompting/truncation_utils.py:49, 63, 66** - mypy limitation with union narrowing
6. **adgn/openai_utils/retry.py:56** - tenacity decorator type preservation
7. **adgn/inop/io/logging_utils.py:32** - isinstance-based narrowing
8. **wt/server/pr_service.py:119** - test fixture return type

**Confidence**: MEDIUM - May have legitimate reasons but deserve comments.

### Requires Investigation
9. **ember/config.py:90** - OpenAI SDK literal type
10. **adgn/llm/sysrw/openai_typing.py:28** - OpenAI SDK message role type

**Confidence**: MEDIUM-HIGH - Likely unnecessary but need SDK inspection.

### Not Violations (Correct Patterns)
- Matrix response unions (proper discriminated union matching)
- Policy response checks (runtime validation for external code)
- Tool response error checking (standard union handling)
- GitHub response coercion (polymorphic function)

---

## Recommendations

### Priority 1: Remove Obvious Casts
1. Remove casts from `tana/` package (2 instances)
2. Remove cast from `wt/shared/protocol.py`
3. Remove cast from `wt/client/wt_client.py`

**Expected Impact**: Better type clarity, no behavioral changes.

### Priority 2: Add Documentation
For casts that may be justified:
```python
# Cast needed: mypy cannot narrow list[A | B] based on isinstance(elem, A) check
for item in cast(list[FileInfo], files):
    ...

# Cast needed: tenacity decorator doesn't preserve type info
call = cast(Callable[P, Awaitable[T]], wrapped)
```

### Priority 3: Investigate SDK Interactions
1. Check OpenAI SDK for `ResponseIncludable` literal values
2. Check OpenAI SDK for `ResponseOutputMessage.role` type

---

## Validation Steps

```bash
# Remove casts and run type checker
mypy --strict adgn tana wt ember

# Run tests to ensure behavioral equivalence
pytest adgn/tests tana/tests wt/tests ember/tests -xvs

# Use reveal_type to understand actual types
# mypy will show: "Revealed type is ..."
```

---

## Related Issues

- **Type Safety**: These casts may hide real type errors elsewhere in the codebase
- **Maintenance**: Future developers may assume libraries lack good types
- **IDE Support**: Less accurate IDE inference and autocompletion

---

**Report Generated**: November 19, 2025
**Scan Tool**: Library Type Misuse Scanner
**Next Step**: Address Priority 1 violations, then review Priority 2 with stakeholders.
