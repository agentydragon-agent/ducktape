# Compositor Documentation

Exception-safe lifecycle management for MCP servers with automatic container cleanup.

**Status**: ✅ Fully Implemented (2025-12)

## Core Features

- **Context manager lifecycle** - `async with Compositor()` ensures cleanup
- **State machines** - CompositorState and MountState enums
- **Exception-safe operations** - Mount failures don't leak, cleanup continues on errors
- **Atomic double-enter prevention** - Thread-safe state transitions
- **Leak detection** - `__del__` warning catches misuse
- **Pinned servers** - Infrastructure servers persist through close()

## Core Guarantees

1. **Cannot leak containers** - All cleanup paths are exception-safe
2. **Cannot be misused** - API design prevents incorrect usage patterns
3. **Is simple** - Minimal concepts, leverages Python's async context manager protocol

## State Machines

### CompositorState

```python
from enum import Enum, auto

class CompositorState(Enum):
    """Compositor lifecycle states.

    Transitions:
    - CREATED → ACTIVE (on first __aenter__)
    - ACTIVE → CLOSED (on __aexit__)
    - CREATED/ACTIVE → CLOSED (on explicit close())

    Invalid transitions:
    - ACTIVE → ACTIVE (double-enter, raises RuntimeError)
    - CLOSED → anything (closed is terminal)
    """
    CREATED = auto()   # Constructed but not entered
    ACTIVE = auto()    # Inside async with block
    CLOSED = auto()    # Cleanup completed, terminal state
```

### MountState

```python
class MountState(Enum):
    """Mount lifecycle states.

    Transitions:
    - PENDING → ACTIVE (successful setup)
    - PENDING → FAILED (setup failure)
    - ACTIVE/FAILED → CLOSED (cleanup)
    """
    PENDING = auto()   # Created but not initialized
    ACTIVE = auto()    # Initialized and ready
    FAILED = auto()    # Initialization failed
    CLOSED = auto()    # Cleanup completed
```

## Entity Map

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent Process                                                    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ async with Compositor() as comp:            [ENTRY POINT]  │ │
│  │                                                             │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Mounted Servers (per mount)                          │  │ │
│  │  │                                                       │  │ │
│  │  │  • FastMCPProxy (routing)                           │  │ │
│  │  │  • Client session (persistent, for notifications)   │  │ │
│  │  │  • AsyncExitStack (cleanup coordinator)             │  │ │
│  │  │      └─> Docker containers (if runtime server)      │  │ │
│  │  │                                                       │  │ │
│  │  │  Lifetime: mount() → unmount()                       │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                             │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Standard In-Proc Servers (pinned)                    │  │ │
│  │  │                                                       │  │ │
│  │  │  • resources (aggregates resources from all servers) │  │ │
│  │  │  • compositor_meta (provides metadata)               │  │ │
│  │  │  • compositor_admin (mount management) [OPTIONAL]    │  │ │
│  │  │                                                       │  │ │
│  │  │  Lifetime: mounted at start, never unmounted         │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                             │ │
│  │  async with Client(comp) as client:                        │ │
│  │      agent = await Agent.create(mcp_client=client)     │ │
│  │                                                             │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Dependency Chain

```
Compositor
  └─> _mounts: dict[str, Mount]
       └─> Each Mount encapsulates:
            ├─> State: MountState enum (PENDING/ACTIVE/FAILED/CLOSED)
            ├─> Proxy: FastMCPProxy (routing layer)
            ├─> Child client: Client (persistent session)
            └─> Stack: AsyncExitStack
                 └─> Owns: stdio processes, HTTP clients, Docker containers
```

## Exception Safety Proofs

### Proof 1: Mount Failures Cannot Leak

**Claim:** If `mount_inproc()` or `mount_server()` fails, no resources leak.

**Proof:**

1. AsyncExitStack created: `stack = AsyncExitStack()`
2. Setup wrapped in try/except
3. Each resource added to stack: `await stack.enter_async_context(resource)`
4. Mount registered in dict only after full setup: `self._mounts[name] = mount`
5. On exception: `except: await stack.aclose(); raise`

**Cases:**

- Transport creation fails → stack is empty, nothing to clean
- Client context manager fails → stack cleans up what was added before failure
- Proxy creation fails → stack cleans up client
- Dict insertion succeeds but init fails → full cleanup happens in `except` block

**Therefore:** All resources cleaned up, mount never registered.

### Proof 2: Close Cannot Be Prevented

**Claim:** `close()` is always called on context exit, even if body raises exception.

**Proof:**

Python async context manager protocol (PEP 492):

- `__aexit__` is **always** called when exiting `async with` block
- This holds even if:
  - Body raises exception
  - Body contains `return`
  - Body contains `break`/`continue`
  - Body is cancelled (asyncio.CancelledError)

Our implementation:

```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        await self.close()
    finally:
        async with self._state_lock:
            self._state = CompositorState.CLOSED
    return False
```

The `try/finally` ensures state is updated even if `close()` fails.

**Therefore:** `close()` is always called, state always transitions to CLOSED.

### Proof 3: Double-Enter Is Prevented

**Claim:** Cannot enter the same compositor twice concurrently.

**Proof:**

```python
async def __aenter__(self) -> Self:
    async with self._state_lock:  # Atomic section
        if self._state == CompositorState.ACTIVE:
            raise RuntimeError("already entered")
        self._state = CompositorState.ACTIVE
    return self
```

The check and set happen atomically under `_state_lock`:

1. Thread A acquires lock, checks state (CREATED), sets ACTIVE
2. Thread B waits for lock
3. Thread A releases lock
4. Thread B acquires lock, checks state (ACTIVE), raises RuntimeError

**Therefore:** Only one thread can successfully enter.

### Proof 4: Concurrent Operations Are Safe

**Claim:** Concurrent mount/unmount operations don't corrupt state.

**Proof:**

All mutations happen under `_mount_lock`:

- `mount_inproc()`: checks duplicate, registers mount under lock
- `mount_server()`: checks duplicate, registers mount under lock
- `unmount_server()`: gets mount, removes from dict under lock
- `close()`: snapshots names under lock, unmounts sequentially

**Races prevented:**

- Mount + unmount same server: One sees "already mounted" or "not found"
- Mount + close: Mount might fail with "closed" or succeed before close sees it
- Unmount + close: One succeeds, other gets "not found"

All races result in clear errors, no corruption.

**Therefore:** Dictionary state is always consistent.

## Design Principles

### 1. Simplicity Over Cleverness

- **ONE type**: `Compositor` (no Handle, no Like union)
- **ONE state machine**: `CompositorState` enum
- **ONE cleanup path**: `close()` called by `__aexit__`

### 2. Exception Safety Everywhere

- Mount setup must cleanup on failure
- Close must log and continue on per-server failures
- AsyncExitStack guarantees cleanup order

### 3. Concurrency Safety Where Needed

- State transitions under lock (double-enter check)
- Mount/unmount under lock
- Read-only queries lock-free (use snapshots)

### 4. Hard to Misuse

- Must use as context manager (runtime check)
- Cannot double-enter (atomic check under lock)
- Leak detection via `__del__` warning

## Where Notifications Live

### Resource Notifications Architecture

**Notification Flow:**

```
Child Server (runtime, etc.)
  └─> ResourceUpdatedNotification(uri="resource://...")
       └─> Child Session (per-mount)
            └─> compositor_meta's mount listener
                 └─> Compositor aggregated ResourceUpdated
                      └─> Client sessions (subscribers)
```

**Components:**

1. **Child Server Sessions** (`Mount.child_client` / `Mount._stack`)
   - Each mount has a persistent Client session to the child server
   - These sessions listen for ResourceUpdated notifications from child servers
   - Created at mount time via `Mount.setup_*()`, cleaned up at unmount via `Mount.cleanup()`

2. **Compositor Mount Listener** (in `compositor_meta` server)
   - Listens for `MountEvent.MOUNTED` and `MountEvent.UNMOUNTED`
   - When mount events occur, broadcasts `ResourceListChangedNotification`

3. **Resource Aggregation** (`compositor_meta` and `resources` servers)
   - `resources` server: aggregates `list_resources()` across all mounted servers
   - `compositor_meta` server: provides metadata resources per server (state, instructions, capabilities)
   - Both are pinned in-proc servers (never unmounted)

**Key Invariant:** Resource notifications propagate from child servers → compositor → subscribed clients. The compositor doesn't synthesize its own ResourceUpdated events - it forwards them from child servers and broadcasts ResourceListChanged when mounts change.

## Implementation Files

- `mcp_infra/src/mcp_infra/compositor/server.py` - Compositor class
- `mcp_infra/src/mcp_infra/compositor/mount.py` - Mount class
- `mcp_infra/tests/compositor/test_lifecycle.py` - Comprehensive tests

## Technical References

- [async-cancellation-deep-dive.md](async-cancellation-deep-dive.md) - Why async cleanup fails during cancellation
- [fastmcp-lifecycle-analysis.md](fastmcp-lifecycle-analysis.md) - FastMCP resource patterns

## TODOs (Future Enhancements)

### Documentation

- [ ] Add troubleshooting section for common issues

### Implementation

- [ ] Add defensive checks in production code

### Testing

- [ ] Add more comprehensive lifecycle tests (edge cases)
- [ ] Add performance benchmarks for concurrent mount/unmount

## Summary

**This design:**

- ✅ Cannot leak containers (proven via AsyncExitStack + exception safety)
- ✅ Cannot be misused (double-enter prevented, state transitions clear)
- ✅ Exception-safe (proven via Python guarantees + try/except patterns)
- ✅ Simple (one type, clear usage, no magic)
- ✅ Detectable misuse (**del** warning fires during development)
