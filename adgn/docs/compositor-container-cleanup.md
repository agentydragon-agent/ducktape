# Plan: Compositor Container Cleanup Lifecycle

**Status:** Proposed
**Date:** 2025-12-05
**Problem:** Docker containers created by Compositor-mounted servers are never cleaned up, leading to hundreds of orphaned containers

## Problem Statement

The GEPA workflow (and potentially other properties critic workflows) leaves Docker containers running indefinitely. Investigation revealed **875 containers older than 10 minutes** that needed manual cleanup.

### Root Cause

The lifecycle management chain is broken at the Compositor level:

1. **Container creation** (working ✓):
   - `critic.py` creates a `Compositor` instance
   - Calls `properties_docker_spec()` which returns a `PropertiesDockerWiring` with a server factory
   - `wiring.attach(comp)` mounts the Docker exec server on the Compositor
   - The server's FastMCP lifespan creates an `AsyncExitStack` with the container session
   - Container is started via `_start_container()` with `auto_remove=True`

2. **Container cleanup** (broken ✗):
   - The `AsyncExitStack` holds the container lifespan context manager
   - On `stack.aclose()`, the lifespan's `finally` block runs `container.kill()` + `container.delete()`
   - `Compositor.unmount_server()` properly calls `stack.aclose()` when unmounting
   - **BUT:** Compositor has no lifecycle method to trigger unmount of all servers
   - **Result:** When agent finishes and `Client(comp)` exits, only the Client is cleaned up
   - The Compositor and its mounted servers persist indefinitely
   - Containers remain running until manually killed

### Code References

**Compositor mount** (creates stack): `src/adgn/mcp/compositor/server.py:249-251, 275-277`
```python
stack = AsyncExitStack()
await stack.enter_async_context(base_client)
mount.stack = stack
```

**Compositor unmount** (closes stack): `src/adgn/mcp/compositor/server.py:289-306`
```python
async def unmount_server(self, name: str) -> None:
    # ...
    if mount.stack is not None:
        await mount.stack.aclose()  # ← This cleans up containers
```

**Container lifespan cleanup**: `src/adgn/mcp/_shared/container_session.py:162-172`
```python
finally:
    if container_dict is not None:
        try:
            container = await client.containers.get(container_dict["Id"])
            await container.kill()
            await container.delete(force=True)
```

**Critic usage** (no Compositor cleanup): `src/adgn/props/critic/critic.py:449-493`
```python
comp = Compositor("compositor")
runtime_server = await wiring.attach(comp)
# ...
async with Client(comp) as mcp_client:
    # run agent
    # Client exits here ✓
# Compositor never cleaned up ✗ ← containers leak here
```

## Solution: Add Compositor Lifecycle Management

### Proposed Changes

#### 1. Add async context manager support to Compositor

**File:** `src/adgn/mcp/compositor/server.py`

Add three methods to the `Compositor` class:

```python
async def __aenter__(self):
    """Support async context manager protocol."""
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    """Cleanup all non-pinned servers on exit."""
    await self.close()
    return False

async def close(self):
    """Unmount all non-pinned servers and cleanup their resources.

    Pinned servers (e.g., compositor_meta, resources) are left mounted.
    Logs warnings for cleanup failures but does not raise.
    """
    async with self._lock:
        names = [name for name, mount in self._mounts.items() if not mount.pinned]

    for name in names:
        try:
            await self.unmount_server(name)
        except Exception as e:
            logger.warning(f"Failed to unmount server '{name}' during close: {e}")
```

**Rationale:**
- Async context manager is idiomatic Python for resource cleanup
- Guarantees cleanup even if exceptions occur during agent execution
- Respects pinned servers (compositor_meta, resources, compositor_admin)
- Logs failures instead of raising to ensure best-effort cleanup of all servers

#### 2. Update Compositor usage sites

**Primary site:** `src/adgn/props/critic/critic.py:449-493`

Before:
```python
comp = Compositor("compositor")
runtime_server = await wiring.attach(comp)
# ...
async with Client(comp) as mcp_client:
    # run agent
```

After:
```python
async with Compositor("compositor") as comp:
    runtime_server = await wiring.attach(comp)
    # ...
    async with Client(comp) as mcp_client:
        # run agent
    # Client exits, but Compositor still open
# Compositor.__aexit__ unmounts all servers ← cleanup happens here
```

**Other sites to update:**
- `src/adgn/props/grader/grader.py` (if it uses Compositor)
- `src/adgn/props/prompt_optimizer.py` (if it uses Compositor)
- Any GEPA-related code that creates Compositor instances
- Tests that create Compositor instances

Find all sites with:
```bash
rg "Compositor\(" src/adgn/props --type py
```

### Verification

#### Manual Testing
1. Run a critic on a snapshot:
   ```bash
   adgn-properties run --snapshot ducktape/2025-11-20-00 --structured true
   ```

2. Monitor container count during execution:
   ```bash
   watch -n 1 'docker ps --filter "ancestor=adgn-llm/properties-critic:latest" | wc -l'
   ```

3. After completion, verify containers are cleaned up:
   ```bash
   docker ps --filter "ancestor=adgn-llm/properties-critic:latest"
   ```
   Should show 0 containers (or only actively running ones, none orphaned)

#### Automated Testing
Add integration test to verify cleanup:

```python
# tests/props/test_compositor_cleanup.py
async def test_compositor_cleans_up_mounted_servers(tmp_path):
    """Verify Compositor unmounts servers and cleans up containers on exit."""
    from adgn.mcp.compositor.server import Compositor
    from adgn.props.docker_env import properties_docker_spec

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Track container count before
    dclient = docker.from_env()
    before_count = len([
        c for c in dclient.containers.list()
        if 'adgn-llm/properties-critic:latest' in c.image.tags
    ])

    # Create and use Compositor with mounted Docker server
    async with Compositor("test-comp") as comp:
        wiring = properties_docker_spec(workspace, ephemeral=False)
        await wiring.attach(comp)
        # Compositor and container are alive here

    # After exit, verify cleanup
    await asyncio.sleep(0.5)  # Allow cleanup to complete
    after_count = len([
        c for c in dclient.containers.list()
        if 'adgn-llm/properties-critic:latest' in c.image.tags
    ])

    assert after_count == before_count, "Containers not cleaned up after Compositor exit"
```

### Migration Path

**Phase 1: Add infrastructure** (backward compatible)
- Add `__aenter__`, `__aexit__`, `close()` to Compositor
- Existing code continues to work (no cleanup, but no breakage)
- Tests pass

**Phase 2: Update critical paths**
- Update `critic.py` to use `async with Compositor(...)`
- Update `grader.py` and other high-usage sites
- Monitor production for container leaks

**Phase 3: Update all sites**
- Grep for all `Compositor(` instantiations
- Update tests
- Add deprecation warning if Compositor used without context manager

**Phase 4: Enforce usage**
- Make `close()` raise if never called (track `_closed` flag)
- Or add `__del__` with warning if cleanup never happened

## Impact Assessment

### Benefits
- **Immediate:** Stops container leak in GEPA and critic workflows
- **Resource usage:** Reduces Docker daemon load and disk usage
- **Reliability:** Prevents "too many containers" failures
- **Cost:** Reduces unnecessary compute/memory consumption

### Risks
- **Breaking changes:** Low - async context manager is backward compatible
- **Performance:** Negligible - cleanup is async and happens after agent finishes
- **Edge cases:** Pinned servers remain mounted (by design)

### Rollback Plan
If issues arise:
1. Revert Compositor changes (remove `__aenter__`, `__aexit__`, `close()`)
2. Update usage sites to explicit cleanup: `await comp.close()` in finally blocks
3. Manual container cleanup script remains available as fallback

## Testing Strategy

### Unit Tests
- `test_compositor_context_manager`: Verify `__aenter__`/`__aexit__` protocol
- `test_compositor_close_unmounts_servers`: Verify close() unmounts non-pinned servers
- `test_compositor_close_preserves_pinned`: Verify pinned servers remain after close()
- `test_compositor_close_handles_failures`: Verify cleanup continues despite errors

### Integration Tests
- `test_critic_cleans_up_containers`: End-to-end test with real Docker containers
- `test_gepa_workflow_cleanup`: Verify GEPA optimizer cleans up containers

### Manual Testing
Run full GEPA optimization with container monitoring:
```bash
# Terminal 1: Run GEPA
adgn-properties optimize --generations 5

# Terminal 2: Monitor containers
watch -n 1 'docker ps --filter "ancestor=adgn-llm/properties-critic:latest" | wc -l'
```

Expected: Container count stays bounded (1-2 active), no accumulation over time.

## Timeline

**Estimated effort:** 2-3 hours
- 30min: Implement Compositor lifecycle methods
- 30min: Update critic.py and other primary usage sites
- 1hr: Write tests
- 30min: Manual testing and verification

**Dependencies:**
- None (self-contained change)

**Blocking:**
- None (can implement immediately)

## Alternative Approaches Considered

### 1. Manual cleanup in finally blocks
```python
comp = Compositor("compositor")
try:
    # ... run agent
finally:
    await comp.close()
```

**Rejected:** More verbose, easy to forget, not idiomatic Python

### 2. Automatic cleanup on Client exit
Modify Client to detect Compositor and trigger cleanup.

**Rejected:** Too magical, tight coupling, doesn't handle non-Client usage

### 3. Ephemeral containers only
Set `ephemeral=True` so containers are auto-removed after each exec.

**Rejected:** Performance impact (container startup overhead per tool call), doesn't solve lifecycle issue

### 4. Docker garbage collection cron
Run periodic cleanup script to kill old containers.

**Rejected:** Band-aid solution, doesn't address root cause, unreliable timing

## Success Criteria

Implementation is successful when:
1. ✅ Compositor has `__aenter__`, `__aexit__`, `close()` methods
2. ✅ All critic/grader/GEPA code uses `async with Compositor(...)`
3. ✅ Integration tests verify container cleanup
4. ✅ Manual testing shows no container accumulation after 10 runs
5. ✅ No regressions in existing functionality

## References

- Issue: Container leak discovered 2025-12-05
- Container cleanup script output: 875 containers killed (>10min old)
- Related: `src/adgn/mcp/compositor/server.py` (Compositor implementation)
- Related: `src/adgn/mcp/_shared/container_session.py` (Container lifespan)
- Related: `src/adgn/props/docker_env.py` (Properties Docker wiring)
