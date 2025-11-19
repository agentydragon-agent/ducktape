# Code Quality Scan: Classes That Should Be Dataclasses or Pydantic Models

**Scan Date**: 2025-11-19
**Repository**: /home/user/ducktape
**Scan Type**: AST-based detection of boilerplate `__init__` methods
**Total Python Files Scanned**: 606 (non-test files)
**Candidates Found**: 4
**Confirmed Violations**: 3

---

## Executive Summary

This scan identified **3 classes with confirmed boilerplate `__init__` methods** that should be refactored to use Python's `@dataclass` decorator. These classes have trivial initialization that just assigns parameters to instance variables, which can be eliminated through dataclass conversion.

### Key Findings

| Violation | Type | Severity | Effort | Impact |
|-----------|------|----------|--------|--------|
| `LocalAgentRuntime` | Plain class → Dataclass | High | Medium | Eliminates 12 lines of boilerplate |
| `MCPInfrastructure` | Plain class → Dataclass | Medium | Low | Eliminates 5 lines of boilerplate |
| `ProgressBar` | Plain class → Dataclass | Medium | Low | Eliminates 7 lines of boilerplate |

One candidate (`GitstatusdService`) was examined but deemed **NOT a violation** due to its dependency injection pattern.

---

## Detailed Findings

### 1. HIGH PRIORITY: LocalAgentRuntime

**Location**: `/home/user/ducktape/adgn/src/adgn/agent/runtime/local_runtime.py` (lines 64-90)

**Issue**: Class with 10 parameters, all assigned trivially in `__init__`

**Current Code**:
```python
class LocalAgentRuntime:
    def __init__(
        self,
        running: RunningInfrastructure,
        model: str,
        client_factory: Callable[[str], OpenAIModelProto],
        system_override: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool = True,
        extra_handlers: Iterable[BaseHandler] | None = None,
        ui_bus = None,
        connection_manager = None,
    ):
        self.running = running
        self.model = model
        self._client_factory = client_factory
        self._system_override = system_override
        self._reasoning_effort = reasoning_effort
        self._reasoning_summary = reasoning_summary
        self._parallel_tool_calls = parallel_tool_calls
        self._extra_handlers = list(extra_handlers or [])  # Mutable default handling
        self._ui_bus = ui_bus
        self._connection_manager = connection_manager

        # Initialized later
        self.session: AgentSession | None = None
        self.agent: MiniCodex | None = None
```

**Analysis**:
- ✅ All 10 assignments are trivial parameter-to-field mappings
- ✅ Only 1 mutable default handling statement (`list(extra_handlers or [])`)
- ✅ Has fields initialized later (session, agent) that can use `field(init=False)`
- ✅ Has complex `async def start()` method that can remain unchanged
- ❌ 12 lines in `__init__` that are pure boilerplate

**Recommended Fix**: Convert to `@dataclass`

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class LocalAgentRuntime:
    """Consumes RunningInfrastructure's compositor_client and adds:
    - MiniCodex agent (OpenAI Responses API)
    - AgentSession (run/event management)
    - UI integration (WebSocket protocol)
    - Loop control server
    """

    running: RunningInfrastructure
    model: str
    client_factory: Callable[[str], OpenAIModelProto]
    system_override: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    reasoning_summary: ReasoningSummary | None = None
    parallel_tool_calls: bool = True
    extra_handlers: Iterable[BaseHandler] | None = None
    ui_bus: Any = None
    connection_manager: Any = None

    # Initialized by start()
    session: AgentSession | None = field(default=None, init=False)
    agent: MiniCodex | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Convert extra_handlers to list if provided."""
        # Note: This line can be removed if extra_handlers is handled in start()
        # and documented as being required in list form
        pass

    async def start(self) -> None:
        # ... existing implementation ...
```

**Benefits**:
- Eliminates 12 lines of boilerplate assignment
- Auto-generates `__repr__`, `__eq__`, `__hash__`
- Fields are clearly declared at class level
- Type hints are preserved and more explicit
- Maintains complex `async def start()` logic unchanged

**Validation Checklist**:
- [ ] Run tests: `pytest adgn/tests -k LocalAgentRuntime`
- [ ] Type check: `mypy src/adgn/agent/runtime/local_runtime.py`
- [ ] Check that `extra_handlers` default handling still works
- [ ] Verify equality/repr behavior unchanged for tests
- [ ] Ensure no external code relies on specific `__init__` signature

---

### 2. MEDIUM PRIORITY: MCPInfrastructure

**Location**: `/home/user/ducktape/adgn/src/adgn/agent/runtime/infrastructure.py` (lines 80-92)

**Issue**: Class with 5 parameters, all assigned trivially in `__init__`

**Current Code**:
```python
class MCPInfrastructure:
    def __init__(
        self,
        agent_id: AgentID,
        persistence: SQLitePersistence,
        docker_client: DockerClient,
        initial_policy: str | None = None,
        connection_manager: ConnectionManager | None = None,
    ):
        self.agent_id = agent_id
        self.persistence = persistence
        self.docker_client = docker_client
        self.initial_policy = initial_policy
        self._connection_manager = connection_manager
```

**Analysis**:
- ✅ All 5 assignments are trivial parameter-to-field mappings
- ✅ No other statements in `__init__`
- ✅ Has async `start()` method with complex initialization logic
- ❌ 5 lines of boilerplate assignment

**Recommended Fix**: Convert to `@dataclass`

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class MCPInfrastructure:
    """Creates minimal core infrastructure - does NOT include optional sidecars
    (UI, chat, loop, runtime). Those are attached to RunningInfrastructure.
    """

    agent_id: AgentID
    persistence: SQLitePersistence
    docker_client: DockerClient
    initial_policy: str | None = None
    connection_manager: ConnectionManager | None = None

    async def start(self, mcp_config: MCPConfig) -> RunningInfrastructure:
        # ... existing implementation ...
```

**Benefits**:
- Eliminates 5 lines of boilerplate
- Auto-generates `__repr__`, `__eq__`, `__hash__`
- Clearer field declarations
- Minimal change (no complex init logic to move)

**Validation Checklist**:
- [ ] Run tests: `pytest adgn/tests -k MCPInfrastructure`
- [ ] Type check: `mypy src/adgn/agent/runtime/infrastructure.py`
- [ ] Verify async `start()` method works correctly
- [ ] Check equality comparisons in tests still work

---

### 3. MEDIUM PRIORITY: ProgressBar

**Location**: `/home/user/ducktape/difftree/src/difftree/progress_bar.py` (lines 50-69)

**Issue**: Plain class with 7 parameters, all assigned trivially

**Current Code**:
```python
class ProgressBar:
    """Progress bar with RTL or LTR alignment for diff statistics."""

    def __init__(
        self,
        value: int,
        max_value: int,
        blocks: BlockChars,
        align: Literal["left", "right"] = "left",
        style: str = "default",
        max_width: int | None = None,
        min_width: int = 5,
    ):
        self.value = value
        self.max_value = max_value
        self.align = align
        self.style = style
        self.blocks = blocks
        self.max_width = max_width
        self.min_width = min_width
```

**Analysis**:
- ✅ All 7 assignments are trivial parameter-to-field mappings
- ✅ No other statements in `__init__`
- ✅ Has multiple render methods that use fields but don't mutate
- ✅ Could be immutable (frozen=True) since fields are never modified
- ❌ 7 lines of boilerplate assignment

**Recommended Fix**: Convert to `@dataclass(frozen=True)` (immutable)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class ProgressBar:
    """Progress bar with RTL or LTR alignment for diff statistics."""

    value: int
    max_value: int
    blocks: BlockChars
    align: Literal["left", "right"] = "left"
    style: str = "default"
    max_width: int | None = None
    min_width: int = 5

    def _render_bar(self, width: int) -> Text:
        # ... existing implementation ...
```

**Benefits**:
- Eliminates 7 lines of boilerplate
- Makes immutability explicit with `frozen=True`
- Auto-generates `__repr__`, `__eq__`, `__hash__`
- Hashable (can be used as dict key or in sets if needed)
- Minimal change required

**Validation Checklist**:
- [ ] Run tests: `pytest difftree/tests`
- [ ] Type check: `mypy src/difftree/progress_bar.py`
- [ ] Verify no code tries to mutate ProgressBar fields
- [ ] Check render methods work correctly

---

### 4. EXCLUDED: GitstatusdService

**Location**: `/home/user/ducktape/wt/src/wt/server/services.py` (lines 91-106)

**Status**: ✅ Correctly a plain class (no violation)

**Analysis**:
- This class receives callable objects as dependencies (dependency injection pattern)
- It serves as an adapter/wrapper that delegates to those callables
- The pattern is intentional for testability and loose coupling
- ❌ NOT a data container - it's a service adapter

**Explanation**: Even though the `__init__` looks like boilerplate, this class is **not** a data container. It follows the **adapter/wrapper pattern** where:

```python
class GitstatusdService:
    def __init__(
        self,
        get_client: Callable[[Path], GitstatusdListener | None],
        iter_client_paths: Callable[[], Iterable[Path]] | None = None,
        ensure_watcher_for_path: Callable[[Path], Awaitable[object]] | None = None,
        list_watchers: Callable[[], list[DebouncedGitstatusRefresh]] | None = None,
        clear_watchers: Callable[[], None] | None = None,
    ) -> None:
        # Store dependencies
        self._get_client = get_client
        self._iter_client_paths = iter_client_paths
        # ... etc ...
        # Expose one callable directly (wrapper delegation)
        self.get_client = get_client
```

The class is a **service adapter**, not a data container. Converting to dataclass would obscure its true intent (dependency injection + adaptation).

---

## Scan Methodology

### Detection Strategy

1. **AST-based analysis**: Parsed all 606 non-test Python files
2. **Heuristic filters**:
   - Classes with 5+ parameters
   - `__init__` method containing mostly `self.x = x` patterns
   - Few or no other statements in `__init__`
3. **Manual verification**: Reviewed each candidate for:
   - Complex initialization logic
   - Mutable default handling (OK for dataclass)
   - Actual use patterns and relationships
   - Dependency injection vs. data container intent

### Exclusions Applied

- Test files (`tests/` directories)
- Virtual environment files
- Build artifacts
- Files with circular imports or special import patterns

---

## Implementation Guide

### Step 1: Prepare Tests

Before converting, ensure tests pass:
```bash
cd adgn
pytest tests/agent/runtime/test_local_runtime.py -v
pytest tests/agent/runtime/test_infrastructure.py -v
pytest ../difftree/tests -v
```

### Step 2: Convert Each Class

For each violation:

1. Add `from dataclasses import dataclass, field` import
2. Add `@dataclass` decorator above class definition
3. Move `__init__` body to field annotations
4. Handle mutable defaults with `field(default_factory=...)`
5. Use `field(init=False)` for fields set later
6. Remove old `__init__` method

### Step 3: Validation

After each conversion:

```bash
# Type checking
mypy src/adgn/agent/runtime/local_runtime.py

# Run tests
pytest tests/agent/runtime/ -v

# Check for unexpected behavior changes
python -c "
from adgn.agent.runtime.local_runtime import LocalAgentRuntime
# Verify repr works
r = LocalAgentRuntime(...)
print(repr(r))
# Verify equality
r2 = LocalAgentRuntime(...)
print(r == r2)
"
```

### Step 4: Pre-commit and Linting

```bash
cd adgn
ruff format .
ruff check . --fix
mypy --config-file pyproject.toml
pre-commit run -a
```

---

## References

- [Python dataclasses documentation](https://docs.python.org/3/library/dataclasses.html)
- [Real Python: Data Classes](https://realpython.com/python-data-classes/)
- [PEP 557: Data Classes](https://www.python.org/dev/peps/pep-0557/)

---

## Follow-up

After implementing these fixes:

1. **Measure impact**: Count lines of code removed
2. **Test coverage**: Run full test suite
3. **Documentation**: Update any internal docs referencing class construction
4. **Code review**: Have team review dataclass patterns used

---

**Scan completed**: 2025-11-19
**Report location**: `/home/user/ducktape/scan_results/missing-dataclass-pydantic.md`
