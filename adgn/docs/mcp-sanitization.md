# MCP Server Sanitization

**Status:** Phase 2.10 Complete ✅ | Phase 2.9, 3-4 Future
**Updated:** 2025-12-10

## Summary

**Goal:** Eliminate string literal constants for tool names and mount prefixes across the MCP stack.

**Completed:**
- ✅ Phase 1: All 21 MCP servers migrated to `EnhancedFastMCP` with typed tool attributes
- ✅ Phase 2.1-2.6: Six compositor recipes implemented (Lint, Critic, Grader, GitCommit, Matrix, AgentContainer)
- ✅ Phase 2.7: `PropertiesDockerWiring` returns `Mounted[T]`; OpenAI strict mode fix for lint models
- ✅ Phase 2.8: `PropertiesDockerWiring` eliminated; replaced with `PropertiesDockerCompositor` intermediate class
- ✅ API improvement: `Compositor.mount_inproc()` now returns `Mounted[T]`
- ✅ Infrastructure servers: Base `Compositor` auto-mounts `resources` and `compositor_meta`

**Remaining:**
- Phase 2.9: Eliminate mount prefix/tool name constants from `constants.py`
- Phase 2.10: Resource URIs as server instance attributes (SSOT on servers) - **Partially complete** (ContainerExecServer done, other servers remain)
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

### Phase 2.8: Eliminate `PropertiesDockerWiring` ✅ Complete

**Status:** ✅ Complete - Implementation matches plan

**Goal:** Replace the `PropertiesDockerWiring` helper with a compositor-based pattern that directly handles Docker server mounting.

#### What PropertiesDockerWiring Currently Does

`PropertiesDockerWiring` is a dataclass that encapsulates:
1. **Docker configuration**: Image, binds, environment, working_dir, network mode
2. **Server factory**: `Callable[[], ContainerExecServer]` that creates the Docker exec server
3. **Mounting logic**: `attach(compositor)` method that mounts the server and returns `Mounted[T]`

**Current usage pattern:**
```python
# Setup: Create wiring object with Docker config
wiring = properties_docker_spec(
    workspace_root=Path("/workspace"),
    docker_client=docker_client,
    mount_properties=True,
    db_conn=DbConnectionConfig(...),
)

# Compositor: Pass wiring to constructor, attach in __aenter__
class CriticCompositor(Compositor):
    runtime: Mounted[ContainerExecServer]
    critic_submit: Mounted[CriticSubmitServer]

    def __init__(self, wiring: PropertiesDockerWiring, critic_state: CriticSubmitState):
        super().__init__()
        self._wiring = wiring
        self._critic_state = critic_state

    async def __aenter__(self):
        await super().__aenter__()
        # Mount Docker server via wiring
        self.runtime = await self._wiring.attach(self)
        # Mount additional task-specific servers
        self.critic_submit = await self.mount_inproc("critic_submit", CriticSubmitServer(self._critic_state), pinned=True)
        return self
```

#### What Will Become of It

The wiring concept will be **eliminated** in favor of an **intermediate compositor class** that centralizes Docker runtime mounting.

**Compositor hierarchy:**
1. **Base Compositor** - Auto-mounts `resources`, `compositor_meta`
2. **PropertiesDockerCompositor** (new intermediate class) - Mounts Docker runtime
3. **App-specific compositors** (Critic, Grader, Lint) - Mount task-specific servers

**Target pattern:**
```python
# New intermediate class (replaces PropertiesDockerWiring)
class PropertiesDockerCompositor(Compositor):
    """Base compositor for properties tasks - handles Docker runtime mounting."""

    runtime: Mounted[ContainerExecServer]

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        *,
        mount_properties: bool = True,
        db_conn: DbConnectionConfig | None = None,
    ):
        super().__init__()
        self._workspace_root = workspace_root
        self._docker_client = docker_client
        self._mount_properties = mount_properties
        self._db_conn = db_conn

    async def __aenter__(self):
        await super().__aenter__()  # Mounts resources, compositor_meta

        # Mount Docker runtime (shared by all properties compositors)
        docker_server = self._create_docker_server()
        self.runtime = await self.mount_inproc("runtime", docker_server, pinned=True)

        return self

    def _create_docker_server(self) -> ContainerExecServer:
        """Create ContainerExecServer with standard properties configuration."""
        binds = self._build_binds()
        env = self._build_container_env()

        return ContainerExecServer(
            ContainerOptions(
                image=PROPERTIES_DOCKER_IMAGE,
                working_dir=WORKING_DIR,
                binds=binds,
                environment=env,
                ephemeral=True,
                network_mode="none",
            ),
            self._docker_client,
        )

    def _build_binds(self) -> list[str]:
        """Build Docker volume binds."""
        binds = [f"{self._workspace_root}:/workspace:ro"]
        if self._mount_properties:
            props_root = get_properties_root()
            binds.append(f"{props_root}:/props:ro")
        return binds

    def _build_container_env(self) -> dict[str, str]:
        """Build container environment variables."""
        env = {
            "XDG_CACHE_HOME": "/tmp",
            "RUFF_CACHE_DIR": "/tmp/.ruff_cache",
            # ... standard tool cache vars
        }
        if self._db_conn:
            env.update({
                "PGHOST": self._db_conn.host,
                "PGPORT": str(self._db_conn.port),
                # ... other PG vars
            })
        return env


# App-specific compositor: just add task-specific servers
class CriticCompositor(PropertiesDockerCompositor):
    """Critic compositor - adds critic_submit server to Docker runtime."""

    critic_submit: Mounted[CriticSubmitServer]

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        critic_state: CriticSubmitState,
        *,
        mount_properties: bool = True,
        db_conn: DbConnectionConfig | None = None,
    ):
        super().__init__(workspace_root, docker_client, mount_properties=mount_properties, db_conn=db_conn)
        self._critic_state = critic_state

    async def __aenter__(self):
        await super().__aenter__()  # Mounts resources, compositor_meta, runtime

        # Mount task-specific server
        self.critic_submit = await self.mount_inproc(
            "critic_submit",
            CriticSubmitServer(self._critic_state),
            pinned=True
        )

        return self
```

#### How to Compose Multiple Servers

**Inheritance hierarchy pattern:**

1. **Compositor** (base) → Auto-mounts `resources`, `compositor_meta`
2. **PropertiesDockerCompositor** (intermediate) → Mounts `runtime` (Docker server)
3. **Task-specific compositors** (Critic, Grader, Lint) → Mount task-specific servers only

**All three properties compositors inherit from PropertiesDockerCompositor:**

**Critic compositor** (inherits runtime, adds critic_submit):
```python
class CriticCompositor(PropertiesDockerCompositor):
    critic_submit: Mounted[CriticSubmitServer]

    def __init__(self, workspace_root, docker_client, critic_state, **kwargs):
        super().__init__(workspace_root, docker_client, **kwargs)
        self._critic_state = critic_state

    async def __aenter__(self):
        await super().__aenter__()  # Gets: resources, compositor_meta, runtime
        self.critic_submit = await self.mount_inproc("critic_submit", CriticSubmitServer(self._critic_state), pinned=True)
        return self
```

**Grader compositor** (inherits runtime, adds grader_submit):
```python
class GraderCompositor(PropertiesDockerCompositor):
    grader_submit: Mounted[GraderSubmitServer]

    def __init__(self, workspace_root, docker_client, grader_state, **kwargs):
        super().__init__(workspace_root, docker_client, **kwargs)
        self._grader_state = grader_state

    async def __aenter__(self):
        await super().__aenter__()  # Gets: resources, compositor_meta, runtime
        self.grader_submit = await self.mount_inproc("grader_submit", GraderSubmitServer(self._grader_state), pinned=True)
        return self
```

**Lint compositor** (inherits runtime, adds lint_submit):
```python
class LintIssueCompositor(PropertiesDockerCompositor):
    lint_submit: Mounted[LintSubmitServer]

    def __init__(self, workspace_root, docker_client, lint_state, **kwargs):
        super().__init__(workspace_root, docker_client, **kwargs)
        self._lint_state = lint_state

    async def __aenter__(self):
        await super().__aenter__()  # Gets: resources, compositor_meta, runtime
        self.lint_submit = await self.mount_inproc("lint_submit", LintSubmitServer(self._lint_state), pinned=True)
        return self
```

**Key benefits:**
- **Docker logic centralized**: All three compositors share the same Docker setup via inheritance
- **No duplication**: `_create_docker_server()`, `_build_binds()`, `_build_container_env()` live in one place
- **Clear hierarchy**: Compositor → PropertiesDockerCompositor → (Critic|Grader|Lint)
- **Type safety**: All servers are pinned, inproc, with typed `Mounted[T]` attributes
- **Consistent prefixes**: `runtime` for Docker, `<task>_submit` for task-specific servers

#### Rationale

- **Eliminates wiring object**: Docker mounting logic moves into compositor hierarchy
- **Centralized Docker setup**: All three compositors share the same base class
- **Proper inheritance**: Clear three-level hierarchy (Compositor → PropertiesDockerCompositor → Task-specific)
- **No duplication**: Docker config, binds, env building lives in one place
- **Type safety preserved**: All mounts remain strongly typed via `Mounted[T]`
- **Follows compositor pattern**: Consistent with agent/matrix/commit compositors
- **Clear responsibilities**: Base compositor handles Docker, subclasses handle task-specific concerns

#### Definition of Done (DoD)

**Phase 2.8 complete when:**
1. ✅ `PropertiesDockerCompositor` class created (new intermediate compositor)
2. ✅ `PropertiesDockerWiring` class deleted
3. ✅ `properties_docker_spec()` function deleted (no longer needed)
4. ✅ All compositors (Critic, Grader, Lint) inherit from `PropertiesDockerCompositor`
5. ✅ All compositors only mount task-specific servers (runtime inherited)
6. ✅ Docker server creation logic (`_create_docker_server`, `_build_binds`, `_build_container_env`) lives only in `PropertiesDockerCompositor`
7. ✅ All tests updated to use new compositor API
8. ✅ No references to `wiring.attach()` in codebase
9. ✅ Mypy passes on all modified files
10. ✅ All props tests pass

**Affected files:**
- `src/adgn/props/docker_env.py` - Add PropertiesDockerCompositor, delete PropertiesDockerWiring
- `src/adgn/props/critic/critic.py` - CriticCompositor inherits from PropertiesDockerCompositor
- `src/adgn/props/grader/grader.py` - GraderCompositor inherits from PropertiesDockerCompositor
- `src/adgn/props/lint_issue.py` - LintIssueCompositor inherits from PropertiesDockerCompositor
- `src/adgn/props/prompt_optimize/prompt_optimizer.py` - Update callers (pass Docker config directly)
- `src/adgn/props/cli/shared.py` - Update CLI wiring to create compositors directly
- All test files using these compositors

### Phase 2.9: Eliminate Mount Prefix/Tool Name Constants (In Progress)

**Status:** 🔄 Partially Started - Limited progress, needs refactoring strategy
**Updated:** 2025-12-10

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

**Progress so far:**
- ✅ `auto_attach.py` - Inlined DEFAULT_AUTO_SERVER_NAMES tuple (literals acceptable for filtering)
- ✅ `agent/runtime/container.py` - Removed SEATBELT_EXEC_MOUNT_PREFIX (uses default from helper)
- ✅ `approval_policy/clients.py` - Removed unused local aliases

**Files requiring refactoring (initialization order reorganization):**
- `agent/server/reducer.py` - UI tool name checks
  - **Analysis:** `reduce_ui_state()` called from `AgentSession._apply_ui_event()` and `history.py`
  - `AgentSession` has `approval_engine` but not compositor
  - **Proposed refactor:** Reorganize initialization order to mount UI server first, then pass UI tool names to reducer callers
  - **Pattern:** `reduce_ui_state(state, evt, ui_send_tool_name, ui_end_tool_name)` or store on AgentSession
  - **Feasibility:** MEDIUM - requires initialization order change but no major architectural refactoring
- `agent/policies/default_policy.py` - Standalone policy program
  - **Analysis:** Executes in Docker isolation, no compositor available
  - **Recommendation:** Constants acceptable here (document rationale)
- `mcp/compositor/clients.py` - CompositorAdminClient
  - **Analysis:** Created in `AgentContainer` (container.py:515, 567, 573) which HAS `self._compositor`
  - **Feasibility:** HIGH - can easily receive admin server instance
  - **Proposed refactor:** `CompositorAdminClient(client, admin_server: Mounted[AdminServer])`
  - Call site: `CompositorAdminClient(self._compositor_client, self._compositor.compositor_admin)`
- `approval_policy/engine.py` - Template rendering, test tool names
  - **Analysis:** Two uses:
    1. `_load_instructions()` - renders template with `RUNTIME_MOUNT_PREFIX` (called during init, before mounts)
    2. `self_check()` - constructs test tool name for validation
  - **Recommendation:** Keep constants (PolicyEngine created before servers mounted, test data usage)
- Tests - Many test files reference constants

**Files with compositor access (can be updated immediately):**
- `mcp/compositor/server.py` - Docstrings and auto-mount logic
- `mcp/ui/server.py` - attach_ui helper
- `mcp/runtime/server.py` - attach_runtime helper

**Affected areas:**
- All compositors that reference these constants
- Bootstrap helpers that build tool names
- Test fixtures that mock mounts (~20-30 files)

#### Definition of Done (DoD)

**Phase 2.9 complete when:**
1. ✅ All `*_MOUNT_PREFIX` constants deleted from `constants.py`
2. ✅ All `*_SERVER_NAME` constants deleted from `constants.py`
3. ✅ `COMPOSITOR_ADMIN_SERVER_NAME` moved to `compositor/admin.py` or eliminated
4. ✅ All mount prefix access via `compositor.server_mount.prefix` (from `Mounted[T]`)
5. ✅ All tool name access via `compositor.server_mount.server.tool.name`
6. ✅ Bootstrap helpers use `Mounted[T]` attributes (no string constants)
7. ✅ Only filesystem/process constants remain in `constants.py`:
   - `WORKING_DIR = Path("/workspace")`
   - `SLEEP_FOREVER_CMD = ["/bin/sh", "-lc", "sleep infinity"]`
8. ✅ Mypy passes on all modified files
9. ✅ All tests pass (agent + mcp + props)

### Phase 2.10: Resources as Typed Server Attributes (In Progress)

**Status:** 🔄 In Progress - ContainerExecServer complete, other servers remain

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
from typing import cast
from fastmcp.resources import FunctionResource, FunctionResourceTemplate

class ContainerExecServer(EnhancedFastMCP):
    # Typed resource attributes (use _resource suffix to distinguish from function)
    container_info_resource: FunctionResource  # Static URI (analogous to FunctionTool)

    def __init__(self, ...):
        super().__init__(...)

        # @resource decorator returns FunctionResource for static URIs
        # Need cast because decorator signature is Resource | ResourceTemplate
        async def container_info_json(ctx: Context) -> dict[str, Any]:
            """Docker container information"""
            return self._get_container_info()

        container_info_json.__annotations__["ctx"] = Context
        self.container_info_resource = cast(
            FunctionResource,
            self.resource(
                "resource://runtime/container/info",
                mime_type="application/json",
                name="container.info",
                title="Container session metadata",
                description="Docker container details for this session",
            )(container_info_json),
        )

class CompositorMetaServer(EnhancedFastMCP):
    # Typed resource attributes
    servers_list_resource: FunctionResource  # Static URI
    server_state_resource: FunctionResourceTemplate  # Parameterized URI (contains {param} placeholders)

    def __init__(self, ...):
        super().__init__(...)

        # Static resource
        async def servers_list() -> list[str]:
            """List all servers"""
            return list(self._compositor.servers.keys())

        self.servers_list_resource = cast(
            FunctionResource,
            self.resource("compositor://servers")(servers_list),
        )

        # Parameterized resource URI → returns FunctionResourceTemplate
        async def server_state(server: str) -> str:
            """Server state for a given server"""
            return json.dumps(self._get_server_state(server))

        self.server_state_resource = cast(
            FunctionResourceTemplate,
            self.resource("compositor://{server}/state")(server_state),
        )

# Usage - access via typed attribute

# Static resources: use .uri
uri = runtime_server.container_info_resource.uri  # str: "resource://runtime/container/info"
name = runtime_server.container_info_resource.name  # str: "container.info"

# Parameterized resources: use .uri_template
uri_template = meta_server.server_state_resource.uri_template  # str: "compositor://{server}/state"
# Can match specific URIs
params = meta_server.server_state_resource.matches("compositor://foo/state")
# params = {"server": "foo"}

# From compositor (via Mounted[T])
uri = compositor.runtime.server.container_info_resource.uri
uri_template = compositor.compositor_meta.server.server_state_resource.uri_template
```

**Rationale:**
- **Parallel to tools**: `@self.resource()` decorator returns `FunctionResource` or `FunctionResourceTemplate` (like `@self.tool()` returns `FunctionTool`)
- **Type safety**: Precise types (`FunctionResource` for static, `FunctionResourceTemplate` for parameterized), not raw strings
- **Single source of truth**: URI/template lives with server instance, not in constants
- **Discoverability**: IDE autocomplete shows available resources and their types
- **No string literals**: Access via `server.my_resource_resource.uri` or `.uri_template`
- **Consistent pattern**: Same decorator approach for both tools and resources
- **FastMCP native**: Uses built-in FastMCP resource API (no custom infrastructure needed)
- **Cast needed**: Decorator signature is `Resource | ResourceTemplate`, cast to specific subclass based on whether URI is parameterized
  - Static URI (`"resource://foo"`) → cast to `FunctionResource` → access via `.uri`
  - Parameterized URI (`"resource://foo/{id}"`) → cast to `FunctionResourceTemplate` → access via `.uri_template`

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

**Implementation notes:**
- Use `_resource` suffix for resource attributes to distinguish from function names
- Type as `FunctionResource` (the actual return type from decorator)
- Use `cast(FunctionResource, ...)` because decorator signature is `Resource | ResourceTemplate`
- Access via `server.container_info_resource.uri` pattern

**Example implementation (ContainerExecServer):**
- Added `container_info_resource: FunctionResource` instance attribute
- Stashed result of `@self.resource()` decorator with cast
- Removed `CONTAINER_INFO_URI` class constant (no longer needed)
- Added `AgentContainer.runtime_server` property to expose server instance
- Updated `status_shared.py` to access via `c.runtime_server.container_info_resource.uri`

**Files modified:**
- `src/adgn/mcp/exec/docker/server.py` - Added resource attribute pattern
- `src/adgn/agent/runtime/container.py` - Added `runtime_server` property
- `src/adgn/agent/server/status_shared.py` - Updated to use server instance URI
- `src/adgn/props/lint_issue.py` - Already using `compositor.runtime.server.container_info_resource.uri`

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
