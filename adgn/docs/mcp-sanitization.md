# MCP Server Sanitization

**Status:** Phase 2.7 Complete ✅ | Phase 2.8-2.10 Planned (Eliminate Wiring, Constants, URI literals) | Phase 3-4 Future
**Updated:** 2025-12-10

## Summary

**Goal:** Eliminate string literal constants for tool names and mount prefixes across the MCP stack.

**Completed:**
- ✅ Phase 1: All 21 MCP servers migrated to `EnhancedFastMCP` with typed tool attributes
- ✅ Phase 2.1-2.6: Six compositor recipes implemented (Lint, Critic, Grader, GitCommit, Matrix, AgentContainer)
- ✅ Phase 2.7: `PropertiesDockerWiring` returns `Mounted[T]`; OpenAI strict mode fix for lint models
- ✅ API improvement: `Compositor.mount_inproc()` now returns `Mounted[T]`
- ✅ Infrastructure servers: Base `Compositor` auto-mounts `resources` and `compositor_meta`

**Remaining:**
- Phase 2.8: Replace `PropertiesDockerWiring` with compositor-based pattern
- Phase 2.9: Eliminate mount prefix/tool name constants from `constants.py`
- Phase 2.10: Resource URIs as server instance attributes (SSOT on servers)
- Phase 3: Test fixture migration
- Phase 4: Final cleanup & validation

---

## Core Pattern (Phases 1-2.6 Complete)

**Server Pattern (`EnhancedFastMCP`):**
```python
class MyServer(EnhancedFastMCP):
    my_tool: FunctionTool

    def __init__(self):
        super().__init__("My Server", ...)
        def my_tool(input: MyInput) -> MyOutput: ...
        self.my_tool = self.flat_model()(my_tool)

# Access: server.my_tool.name (no constants)
```

**Compositor Pattern (`Mounted[T]`):**
```python
class MyCompositor(Compositor):
    runtime: Mounted[ContainerExecServer]

    async def __aenter__(self):
        await super().__aenter__()
        self.runtime = await self.mount_inproc("runtime", ContainerExecServer(...), pinned=True)
        return self

# Access: comp.runtime.server.exec_tool.name
# Prefixed: comp.runtime.tool_name(comp.runtime.server.exec_tool)
```

**Key API:** `Compositor.mount_inproc()` returns `Mounted[T]` for fluent DRY mounting.

**Completed Implementations:**
- Phase 1: 21/21 MCP servers (reference: `src/adgn/mcp/git_ro/server.py`)
- Phase 2.1-2.6: Six compositors
  - `LintIssueCompositor` - `src/adgn/props/lint_issue.py`
  - `CriticCompositor` - `src/adgn/props/critic/critic.py`
  - `GraderCompositor` - `src/adgn/props/grader/grader.py`
  - `CommitCompositor` - `src/adgn/git_commit_ai/agent_backend.py`
  - `MatrixBotCompositor` - `src/adgn/agent/matrix_bot.py`
  - `AgentContainerCompositor` - `src/adgn/agent/runtime/container.py`

**Test Infrastructure Exception:**
- Class-level constants on `CriticCompositor`, `GraderCompositor`, `ContainerExecServer` (marked "for test infrastructure only")
- Reason: `run_prompt_optimizer()` spawns dynamic compositor runs; test steps built once, executed across multiple lifecycles
- Production code uses `Mounted[T]` exclusively

---

## Phase 2.6: Agent Container ✅ Complete

**File:** `src/adgn/agent/runtime/container.py`

**Implementation:** Created `AgentContainerCompositor` with 7 typed server attributes

**Servers mounted:**
1. `resources` - Auto-mounted by base Compositor (pinned)
2. `compositor_meta` - Auto-mounted by base Compositor (pinned)
3. `loop: Mounted[LoopServer]` - Loop control (pinned)
4. `policy_reader: Mounted[EnhancedFastMCP]` - Policy reading (pinned)
5. `policy_proposer: Mounted[EnhancedFastMCP]` - Policy proposals (pinned)
6. `ui: Mounted[UiServer] | None` - Conditional on `ui_bus` (pinned if present)
7. `runtime: Mounted[RuntimeServer] | None` - Conditional on `ui_bus` (pinned if present)

**Key changes:**
- Base `Compositor` now auto-mounts `resources` and `compositor_meta` in `__aenter__()`
- All manual mounting removed from props compositors (critic, grader, prompt_optimizer)
- Bootstrap helpers accept `Mounted[ResourcesServer]` instead of string constants
- Chat servers inlined into AgentContainerCompositor (was separate helper)
- `_attach_inproc_servers()` method deleted (all mounting in compositor)

**Files modified:** 8 files (container, bootstrap, lint_issue, critic, grader, prompt_optimizer, compositor/server, test)

**Validation:** ✅ All mypy checks pass

---

## Phase 2.7: PropertiesDockerWiring Redesign ✅ Complete

**Implementation Complete**

**Changes Implemented:**

1. ✅ **`src/adgn/props/docker_env.py`**
   - `attach()` now returns `Mounted[ContainerExecServer]`
   - `server_name` property removed
   - `server_factory` type tightened to `Callable[[], ContainerExecServer]`

2. ✅ **3 Compositors** (lint, critic, grader)
   - Direct assignment: `self.runtime = await self._wiring.attach(self)`
   - Type tightened: `runtime: Mounted[ContainerExecServer]`

3. ✅ **Bootstrap helpers** (bootstrap.py, lint_issue.py, prompt_optimizer.py)
   - New `docker_exec_call_mounted()` helper accepts `Mounted[ContainerExecServer]`
   - Updated signatures: `runtime: Mounted[ContainerExecServer]` parameter
   - All call sites updated

4. ✅ **Test fixture** (test_prompt_builder.py)
   - Updated to create proper `ContainerExecServer` instance
   - Lazy import pattern for Docker-free tests

5. ✅ **OpenAI Strict Mode Fix** (src/adgn/props/models/lint.py)
   - Changed all lint finding classes to inherit from `OpenAIStrictModeBaseModel`
   - Removed `Field(discriminator="kind")` from union definition
   - Now uses plain union: `IssueLintFinding = A | B | C | ...`
   - Generates `anyOf` schema (OpenAI strict mode compatible) instead of `oneOf`

**Validation:**
- ✅ Mypy passes on all modified files
- ✅ OpenAI strict mode validation passes (server creation succeeds)
- ✅ All lint model tests pass (7/7)
- ✅ Discriminated union now generates `anyOf` instead of `oneOf`

**Files Modified:** 9 files
- `src/adgn/props/docker_env.py`
- `src/adgn/props/lint_issue.py`
- `src/adgn/props/critic/critic.py`
- `src/adgn/props/grader/grader.py`
- `src/adgn/props/prompt_optimize/prompt_optimizer.py`
- `src/adgn/agent/bootstrap.py`
- `src/adgn/props/cli/shared.py`
- `tests/props/prompts/test_prompt_builder.py`
- `src/adgn/props/models/lint.py`

---

---

## String Literal Audit (2025-12-10)

**Remaining string literal uses (all justified):**

1. **Test infrastructure constants** (allowed per plan):
   - `ECHO_MOUNT_PREFIX`, `ECHO_TOOL_NAME` (`src/adgn/mcp/testing/simple_servers.py`)
   - `DOCKER_TEST_MOUNT_PREFIX`, `EDITOR_TEST_MOUNT_PREFIX` (`tests/support/steps.py`)
   - `EXEC_TEST_TOOL_NAME`, `FAIL_TEST_TOOL_NAME` (`tests/support/steps.py`)
   - Used for mock step builders and test fixtures

2. **Prompt optimizer infrastructure** (documented exception):
   - `ContainerExecServer.EXEC_TOOL_NAME` - class constant
   - `CriticCompositor.SUBMIT_PREFIX` - class constant
   - `CriticSubmitServer.UPSERT_ISSUE_TOOL_NAME` et al. - class constants
   - Used in `tests/props/prompt_eval/test_prompt_optimizer_integration.py`
   - Rationale: Test steps built once, executed across multiple compositor lifecycles

3. **Template rendering** (legitimate use):
   - `src/adgn/mcp/approval_policy/engine.py:383` - Jinja2 template variable
   - Passes `ContainerExecServer.EXEC_TOOL_NAME` to instruction template
   - Not a call site - documentation only

4. **Direct client.call_tool() in tests** (< 10 occurrences):
   - Tests calling tools directly via FastMCP client (not through compositor)
   - Examples: `tests/mcp/enhanced/flat_model/test_decorator.py`
   - Acceptable: These are unit tests of individual servers

**All production code:** Uses typed server attributes (`server.tool.name`) or `build_mcp_function()` helper ✅

---

## Remaining Work

### Phase 2.8: Eliminate `PropertiesDockerWiring` (Future)

**Goal:** Replace the `PropertiesDockerWiring` helper with a compositor layer/module/subclass that directly mounts the Docker server.

**Current pattern:**
```python
# Separate wiring object manages Docker server
wiring = PropertiesDockerWiring(...)
runtime = await wiring.attach(compositor)
```

**Target pattern:**
```python
# Compositor subclass handles Docker mounting directly
class PropsCompositor(Compositor):
    runtime: Mounted[ContainerExecServer]

    async def __aenter__(self):
        await super().__aenter__()
        self.runtime = await self.mount_inproc("runtime", ContainerExecServer(...), pinned=True)
        return self
```

**Rationale:**
- Eliminates intermediate "wiring" concept
- More consistent with compositor pattern used elsewhere
- Direct compositor control over server lifecycle
- Simplifies type flow (no need to pass wiring around)

**Affected files:**
- `src/adgn/props/docker_env.py` - Replace with compositor factory/subclass
- `src/adgn/props/lint_issue.py` - Use new compositor base
- `src/adgn/props/critic/critic.py` - Use new compositor base
- `src/adgn/props/grader/grader.py` - Use new compositor base
- Bootstrap helpers - May need adjustment

### Phase 2.9: Eliminate Mount Prefix/Tool Name Constants (Future)

**Goal:** Remove server mount prefixes and tool name constants from `constants.py`, accessing them only through typed server/mount attributes.

**Current pattern:**
```python
# constants.py
RESOURCES_MOUNT_PREFIX: Final[str] = "resources"
RUNTIME_MOUNT_PREFIX: Final[str] = "runtime"
COMPOSITOR_META_MOUNT_PREFIX: Final[str] = "compositor_meta"

# Usage
from adgn.mcp._shared.constants import RUNTIME_MOUNT_PREFIX
tool_name = build_mcp_function(RUNTIME_MOUNT_PREFIX, "exec")
```

**Target pattern:**
```python
# Compositor holds typed mounts
class MyCompositor(Compositor):
    runtime: Mounted[ContainerExecServer]

# Usage - access prefix from mount
tool_name = comp.runtime.tool_name(comp.runtime.server.exec_tool)
# Or for bootstrap
bootstrap_call = builder.call(comp.runtime.prefix, comp.runtime.server.exec_tool.name, ...)
```

**Rationale:**
- Single source of truth: mount prefix lives with the `Mounted[T]` object
- Type safety: can't use wrong prefix for wrong server
- No central constants file to maintain
- Mount prefix and server are always in sync

**Current constants to eliminate:**
```python
# From src/adgn/mcp/_shared/constants.py
RESOURCES_MOUNT_PREFIX = "resources"
RUNTIME_MOUNT_PREFIX = "runtime"
COMPOSITOR_META_MOUNT_PREFIX = "compositor_meta"
UI_MOUNT_PREFIX = "ui"
COMPOSITOR_ADMIN_SERVER_NAME = "compositor_admin"
POLICY_READER_MOUNT_PREFIX = "policy_reader"
POLICY_PROPOSER_MOUNT_PREFIX = "policy_proposer"
APPROVAL_ADMIN_MOUNT_PREFIX = "approval_admin"
SEATBELT_EXEC_MOUNT_PREFIX = "seatbelt_exec"
```

**Keep in constants.py:**
- Container filesystem paths (e.g., `WORKING_DIR = Path("/workspace")`)
- Process control commands (e.g., `SLEEP_FOREVER_CMD`)

**Move to server modules:**
- URI format strings (e.g., `COMPOSITOR_META_STATE_URI_FMT`) → move to `compositor/meta.py` or respective server module

**Affected areas:**
- All compositors that reference these constants
- Bootstrap helpers that build tool names
- Test fixtures that mock mounts

### Phase 2.10: Resources as Typed Server Attributes (Future)

**Goal:** Make resources typed instance attributes on servers, parallel to how `FunctionTool` works for tools.

**Current pattern:**
```python
# constants.py
COMPOSITOR_META_STATE_URI_FMT: Final[str] = "resource://compositor-meta/servers/{server}/state"
CONTAINER_INFO_URI: Final[str] = "resource://runtime/container/info"

# Usage - string literals everywhere
from adgn.mcp._shared.constants import CONTAINER_INFO_URI
content = await client.read_resource(CONTAINER_INFO_URI)
```

**Target pattern:**
```python
# Server class defines resource attributes using @resource decorator
# (parallel to @tool decorator returning FunctionTool)
class ContainerExecServer(EnhancedFastMCP):
    # Typed resource attributes
    container_info: Resource  # Analogous to FunctionTool

    def __init__(self, ...):
        super().__init__(...)

        # @resource decorator returns Resource object (like @tool returns FunctionTool)
        @self.resource("resource://runtime/container/info")
        def container_info() -> str:
            """Docker container information"""
            return json.dumps(self._get_container_info())

        self.container_info = container_info

class CompositorMetaServer(EnhancedFastMCP):
    # ResourceTemplate for parameterized URIs (contains {param} placeholders)
    server_state: ResourceTemplate

    def __init__(self, ...):
        super().__init__(...)

        # Parameterized resource URI → returns ResourceTemplate
        @self.resource("resource://compositor-meta/servers/{server}/state")
        def server_state(server: str) -> str:
            """Server state for a given server"""
            return json.dumps(self._get_server_state(server))

        self.server_state = server_state

# Usage - access via typed attribute
uri = runtime_server.container_info.uri  # str: "resource://runtime/container/info"
name = runtime_server.container_info.name  # str: "container_info"

# For parameterized resources (ResourceTemplate)
uri_template = meta_server.server_state.uri_template  # str: "resource://compositor-meta/servers/{server}/state"
# Can match specific URIs
params = meta_server.server_state.matches("resource://compositor-meta/servers/foo/state")
# params = {"server": "foo"}

# From compositor (via Mounted[T])
uri = compositor.runtime.server.container_info.uri
uri_template = compositor.compositor_meta.server.server_state.uri_template
```

**Rationale:**
- **Parallel to tools**: `@self.resource()` decorator returns `Resource | ResourceTemplate` (like `@self.tool()` returns `FunctionTool`)
- **Type safety**: `Resource` / `ResourceTemplate` types, not raw strings
- **Single source of truth**: URI lives with server instance, not in constants
- **Discoverability**: IDE autocomplete shows available resources
- **No string literals**: Access via `server.my_resource.uri`
- **Consistent pattern**: Same decorator approach for both tools and resources
- **FastMCP native**: Uses built-in FastMCP resource API (no custom infrastructure needed)

**Example URIs to migrate:**
```python
# Compositor meta server URIs
COMPOSITOR_META_STATE_URI_FMT = "resource://compositor-meta/servers/{server}/state"
COMPOSITOR_META_INSTRUCTIONS_URI_FMT = "resource://compositor-meta/servers/{server}/instructions"
COMPOSITOR_META_CAPABILITIES_URI_FMT = "resource://compositor-meta/servers/{server}/capabilities"
COMPOSITOR_META_URI_PREFIX = "resource://compositor-meta/"

# Runtime/exec server URIs
CONTAINER_INFO_URI = "resource://runtime/container/info"

# Approval policy URIs
POLICY_RESOURCE_URI = "resource://approval-policy/policy.py"

# UI server URIs
UI_STATUS_URI = "resource://ui/status"
```

**Affected areas:**
- Server implementations (add URI properties/methods)
- Code that reads resources (use server instance URIs)
- Bootstrap helpers that build resource calls
- Resource subscription logic

### Phase 3: Test Fixture Migration (3-5h)
- Update test fixtures to use compositor subclasses where beneficial
- Convert remaining manual mock setups to typed compositors
- Should be straightforward after Phase 2.7

### Phase 4: Final Validation & Cleanup (2-3h)
```bash
# Run full test suite
pytest tests/ -v -m "not live_llm"

# Type check everything
mypy src/adgn

# Verify no new string literals introduced
rg 'build_mcp_function\(' --type py | grep '"' | grep -v '\.name'
```

**Expected outcome:** All production code uses typed server access; test infrastructure constants documented and justified.
