# FastMCP Subclass Cleanup - Followup Tasks

**Context:** Refactored FastMCP usage patterns across the codebase to establish consistent guidelines for classes vs factory functions.

---

## Completed Work

### ✅ 1. Converted SeatbeltExecMCP to Factory Function

**File:** `adgn/mcp/exec/seatbelt.py`

**Changes:**
- Converted `class SeatbeltExecMCP(NotifyingFastMCP)` → `def make_seatbelt_exec_server() -> NotifyingFastMCP`
- Server construction now uses closure capture instead of instance variables
- Updated all 3 call sites (tests, container, stdio main)

**Rationale:** Server was stateless (policies provided inline), no complex lifecycle management needed.

---

### ✅ 2. Removed Vestigial Parameters from Seatbelt Server

**File:** `adgn/mcp/exec/seatbelt.py`

**Removed parameters:**
- `agent_id: str | None` - Never actually used
- `persistence` - Marked "unused, kept for API compatibility" (server no longer stores policy templates)
- `docker_client: DockerClient` - Marked "unused, kept for API compatibility"

**Updated call sites:**
- `tests/mcp/exec/test_seatbelt.py` - test fixture
- `adgn/mcp/exec/seatbelt.py` - `attach_seatbelt_exec()` wrapper and `main()` stdio entry
- `adgn/agent/runtime/container.py` - compositor mount call

**Impact:** Clearer API matching actual stateless behavior, removed misleading parameters.

---

### ✅ 3. Removed Legacy Inproc Preset from UI

**File:** `adgn/agent/web/src/features/mcp/presets.ts`

**Removed:** Seatbelt Exec inproc preset entry

**Rationale:** Dead code - no backend support for `transport: 'inproc'` with factory strings:
- `MCPServerTypes` union only includes `RemoteMCPServer` and `StdioMCPServer`
- No `InprocMCPServer` type exists
- Compositor's `_fm_transport_from_spec()` only handles remote/stdio
- No dynamic factory loading infrastructure
- Inproc servers mount via direct `mount_inproc(name, fastmcp_instance)` API calls, not specs

---

### ✅ 4. Eliminated FlatModelFastMCP Class

**File:** `adgn/mcp/_shared/fastmcp_flat.py:353`

**Problem:** One-line class combining mixin + base: `class FlatModelFastMCP(FlatModelToolMixin, FastMCP)`
- `NotifyingFastMCP` already has the same mixin
- Notification overhead is negligible
- Created unnecessary class hierarchy variation

**Replaced in 2 locations:**
1. `agent/mcp_bridge/agents.py:104` - `make_agents_server()` factory
2. `agent/runtime/container.py:232` - `make_control_server()` method

**Changed:** `FlatModelFastMCP(name)` → `NotifyingFastMCP(name)`

**Benefits:**
- Uniform server construction across codebase
- One less class to maintain
- No functional loss (notification capability is free)

---

### ✅ 5. Replaced 6 Unnecessary TypeAdapter Usages

**Pattern:** Using `TypeAdapter(ConcreteModel)` where `ConcreteModel.model_validate()` would work.

**Files modified:**

#### `adgn/rspcache/models.py`
```python
# Before:
RESPONSE_ADAPTER: TypeAdapter[OpenAIResponse] = TypeAdapter(OpenAIResponse)
ERROR_ADAPTER: TypeAdapter[ResponseError] = TypeAdapter(ResponseError)
return RESPONSE_ADAPTER.validate_python(event.response)

# After:
return OpenAIResponse.model_validate(event.response)
```

#### `adgn/agent/matrix_bot.py`
```python
# Before:
TypeAdapter(BaseExecResult).validate_python(res.structuredContent or {})

# After:
BaseExecResult.model_validate(res.structuredContent or {})
```

#### `adgn/props/bundles/build_bundle.py`
```python
# Before:
TypeAdapter(SpecimenDoc).validate_python(manifest_data)

# After:
SpecimenDoc.model_validate(manifest_data)
```

#### `adgn/agent/agent.py`
```python
# Before:
TypeAdapter(CallToolResult).validate_json(output)

# After:
CallToolResult.model_validate_json(output)
```

#### `adgn/mcp/_shared/calltool.py`
```python
# Before:
TypeAdapter(mcp_types.CallToolResult).validate_python(payload)

# After:
mcp_types.CallToolResult.model_validate(payload)
```

**Also removed:** Unused `TypeAdapter` and `ResponseError` imports from all affected files.

**Benefits:**
- Simpler, more idiomatic Pydantic usage
- No performance difference
- Clearer intent (validating a specific model, not a generic type)

**Note:** Legitimate TypeAdapter usage remains in `calltool.py` for generic type parameters (line 81).

---

### ✅ 6. Audited Other Servers

**Searched entire codebase for FastMCP subclasses.**

**Found 2 classes (both should remain as classes):**

1. **`Compositor`** (`adgn/mcp/compositor/server.py:59`)
   - Complex stateful aggregator
   - Extensive internal state: `_mounts`, `_lock`, lifecycle listeners, notification buffers
   - Many methods: `mount_inproc()`, `mount_server()`, `unmount()`, session management
   - **Verdict: Keep as class** - proper abstraction with complex behavior

2. **`NotifyingFastMCP`** (`adgn/mcp/notifying_fastmcp.py:109`)
   - Captures live ServerSession objects after initialize
   - Provides notification broadcasting outside requests
   - Adds real capability: `broadcast()` method
   - **Verdict: Keep as class** - adds capability beyond base FastMCP

**No additional class-to-factory conversions needed.**

---

## Remaining Tasks

### High Priority

#### 1. Document Class vs Factory Function Guidelines

**Action:** Create `adgn/docs/mcp_server_patterns.md`

**Content:** Document when to use classes vs factory functions for MCP servers.

**Guidelines:**

```python
# Use CLASS when:
# - Complex stateful behavior (Compositor: mount/unmount, lifecycle listeners)
# - Additional methods beyond base FastMCP (NotifyingFastMCP: broadcast())
# - Proper abstraction with clear boundaries

class Compositor(FastMCP):
    """Aggregates upstream MCP servers under a single FastMCP surface.

    Design: Class is appropriate because:
    - Extensive mutable state: _mounts, _lock, lifecycle listeners
    - Many methods: mount/unmount operations, session management
    - Complex behavior: tool namespacing, notification relay, state tracking
    - Proper abstraction with clear boundaries
    """

class NotifyingFastMCP(FlatModelToolMixin, FastMCP):
    """FastMCP with notification broadcasting outside requests.

    Design: Class is appropriate because:
    - Captures and manages live ServerSession objects
    - Provides new capability: broadcast() method
    - State: tracks active sessions for notification delivery
    """

# Use FACTORY FUNCTION when:
# - Server is stateless or closure-captured state is sufficient
# - Only registering tools/resources, no complex lifecycle management
# - No need for additional methods beyond base FastMCP
# - Implementation is primarily configuration + tool registration

def make_X_server(...) -> NotifyingFastMCP:
    """Create X MCP server.

    Use factory function when:
    - Server is stateless or closure-captured state is sufficient
    - Only registering tools/resources, no complex lifecycle management
    - No need for additional methods beyond base FastMCP
    - Implementation is primarily configuration + tool registration
    """
    server = NotifyingFastMCP(name, instructions="...")

    @server.flat_model()
    async def tool_name(...):
        # Tool implementation using closure-captured state
        ...

    return server
```

**Examples:**
- Factory pattern: `make_seatbelt_exec_server()`, `make_runtime_server()`, `make_ui_server()`, `make_loop_server()`
- Class pattern: `Compositor`, `NotifyingFastMCP`

**Implementation:**
- Create markdown doc with decision tree/checklist
- Include examples from real codebase
- Reference in AGENTS.md

---

### Medium Priority

#### 2. Clarify MCP Config Spec Support

**Problem:** UI TypeScript types suggest `transport: 'inproc'` with factory strings is supported, but backend only handles stdio/http/sse specs.

**Current confusion:**
- TypeScript schema defines `InprocSpecZ` with factory/args/kwargs
- Form builder has inproc case handling
- Backend `MCPServerTypes` union has no `InprocMCPServer` type
- Compositor only mounts inproc servers via direct `mount_inproc(name, server)` API calls

**Recommendation:**

1. **Add comment to TypeScript schema** (`schema.ts`):
   ```typescript
   // NOTE: Inproc transport is not currently supported by backend via config files.
   // Inproc servers are mounted programmatically via Compositor.mount_inproc().
   // This schema is reserved for future implementation.
   export const InprocSpecZ = z.object({ ... })
   ```

2. **Document in MCP config docs:**
   ```markdown
   ## MCP Server Configuration

   ### Supported Transport Types (Config Files)
   - `stdio`: Subprocess servers via stdio transport
     ```json
     {"command": "server-bin", "args": [], "env": {}}
     ```
   - `http`/`sse`: Remote HTTP servers
     ```json
     {"url": "http://...", "auth": "bearer-token"}
     ```

   ### Programmatic-Only Transports
   - `inproc`: In-process FastMCP servers
     - Must be mounted via `compositor.mount_inproc(name, server)`
     - Cannot be specified in config files
     - UI schema exists for future implementation
   ```

3. **Optional runtime validation:**
   ```python
   # In config loading:
   if hasattr(spec, 'transport') and spec.transport == 'inproc':
       raise ValueError(
           "Inproc transport not supported in config files. "
           "Use Compositor.mount_inproc() programmatically instead."
       )
   ```

**Impact:** Low (UI already has no inproc presets after cleanup). This is documentation-only.

---

#### 3. Remove Inproc Schema from UI (Optional Deep Cleanup)

**Decision needed:** Is inproc config support planned for future or permanently unsupported?

**If permanently unsupported:**

Remove from TypeScript:
- `InprocSpecZ` schema definition in `schema.ts`
- `inproc` case from `buildSpecFromForm()`
- `'inproc'` from transport type unions in `schema.ts` and `presets.ts`
- Inproc-related test cases in `schema.test.ts`
- Form field handling for inproc factory/args/kwargs

**Files to modify:**
- `src/adgn/agent/web/src/features/mcp/schema.ts`
- `src/adgn/agent/web/src/features/mcp/schema.test.ts`
- `src/adgn/agent/web/src/features/mcp/presets.ts`

**If future possibility exists:**
Keep schema with documentation (option 2 from task #2 above).

---

### Low Priority / Nice-to-Have

#### 4. Benchmark NotifyingFastMCP Overhead

**Question:** What's the actual overhead of notification capability vs base FastMCP?

**Purpose:** Validate claim that notification overhead is "negligible" and using NotifyingFastMCP everywhere is "free".

**Test:**
```python
import asyncio
from fastmcp import FastMCP
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

async def bench_base():
    server = FastMCP("test")
    @server.tool()
    def noop(): return "ok"
    # Measure tool call latency over 10000 calls

async def bench_notifying():
    server = NotifyingFastMCP("test")
    @server.tool()
    def noop(): return "ok"
    # Measure tool call latency over 10000 calls
```

**Hypothesis:** Overhead < 10μs per call (negligible for LLM tool use)

**Outcome if confirmed:** Strengthens recommendation to use NotifyingFastMCP as the default base for all factories.

---

#### 5. Consider Unified Server Factory Registry

**Idea:** If we accumulate 5+ factory functions, consider a discovery/registry pattern:

```python
# adgn/mcp/factories.py
SERVER_FACTORIES: dict[str, Callable[..., NotifyingFastMCP]] = {
    "seatbelt": make_seatbelt_exec_server,
    "runtime": make_runtime_server,
    "ui": make_ui_server,
    "loop": make_loop_server,
    # ...
}

def create_server(factory_name: str, **kwargs) -> NotifyingFastMCP:
    factory = SERVER_FACTORIES.get(factory_name)
    if not factory:
        raise ValueError(f"Unknown server factory: {factory_name}")
    return factory(**kwargs)
```

**Benefits:**
- Discoverable list of available servers
- Could enable future dynamic loading if needed
- Testing: can mock registry for testing factory selection

**Drawbacks:**
- Adds indirection
- Most code calls factories directly anyway
- May be premature generalization

**Decision:** Defer until we have 5+ factory functions and see a pattern.

---

## Completion Checklist

- [x] Convert SeatbeltExecMCP to factory function
- [x] Remove vestigial parameters from seatbelt server
- [x] Remove legacy seatbelt inproc preset from UI
- [x] Eliminate FlatModelFastMCP class (2 sites)
- [x] Replace 6 unnecessary TypeAdapter usages
- [x] Audit other potential class-to-factory conversions
- [ ] Document class vs factory guidelines (HIGH)
- [ ] Clarify MCP config spec support in docs (MEDIUM)
- [ ] Decide: Remove or document inproc schema (MEDIUM)
- [ ] (Optional) Benchmark NotifyingFastMCP overhead (LOW)
- [ ] (Optional) Consider unified factory registry if 5+ factories (LOW)

---

## Summary of Current State

### FastMCP Subclasses Remaining
After cleanup, only **2 classes** remain (both appropriate):
1. **Compositor** - Complex stateful aggregator with mount lifecycle
2. **NotifyingFastMCP** - Adds notification broadcasting capability

### Factory Functions
All other MCP servers use factory function pattern:
- `make_seatbelt_exec_server()`
- `make_runtime_server()`
- `make_ui_server()`
- `make_loop_server()`
- `make_agents_server()`
- `make_control_server()` (method on AgentContainer)

### Code Quality
- All unnecessary TypeAdapter usage eliminated
- All vestigial parameters removed
- UI contains no dead presets
- Consistent naming and patterns established

### Remaining Work
**High priority:** Documentation (class vs factory guidelines)
**Medium priority:** Documentation/decision (inproc config support)
**Low priority:** Optional improvements (benchmarking, registry pattern)

**Core refactoring is complete.** Remaining tasks are documentation and optional enhancements.
