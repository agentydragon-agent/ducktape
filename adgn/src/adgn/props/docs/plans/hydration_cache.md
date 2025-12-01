# Hydration Cache Plan

## Problem Statement

Currently, each `SpecimenRegistry.load_and_hydrate()` call:
1. Extracts tarball from archive cache (~/.cache/adgn-llm/specimens/)
2. Yields hydrated content root
3. Deletes extracted directory on exit

**Issue**: Repeated operations on same specimen → repeated extract/delete cycles.

Example from prompt_optimizer.py:
```python
# Pre-hydrates once and keeps alive
for slug in train_specimens:
    hydrated = await stack.enter_async_context(SpecimenRegistry.load_and_hydrate(slug))
    specimen_paths[slug] = hydrated.content_root
# ... operates on all specimens ...
# Cleanup when stack exits
```

But in other places (critic.py, grader.py), we hydrate per-operation:
```python
async with SpecimenRegistry.load_and_hydrate(specimen_slug) as hydrated:
    # Single operation
    pass
# Immediately deletes
```

## Current Caching Layers

### Layer 1: Archive Cache (Already Exists)
- **Location**: `~/.cache/adgn-llm/specimens/{repo}/{name}-{commit}.tar.gz`
- **Purpose**: Avoid re-downloading/re-cloning from GitHub/Git
- **Lifecycle**: Persistent across processes (file lock prevents concurrent creation)
- **Invalidation**: Manual (delete cache file) or commit SHA change

### Layer 2: Hydrated Cache (Proposed)
- **Location**: TBD (tmpdir, ~/.cache/adgn-llm/hydrated/, or in-memory map?)
- **Purpose**: Avoid repeated extraction from archive
- **Lifecycle**: TBD (per-session, ref-counted, explicit?)
- **Invalidation**: TBD (session end, ref-count zero, manual?)

## Design Options

### Option A: Session-Scoped Cache (Simplest)

**Concept**: One cache per logical session, cleanup at session end.

```python
class HydrationCache:
    """Session-scoped cache of hydrated specimens."""

    def __init__(self, registry: SpecimenRegistry):
        self._registry = registry
        self._hydrated: dict[str, HydratedSpecimen] = {}
        self._exit_stack = AsyncExitStack()

    async def get(self, slug: str) -> HydratedSpecimen:
        """Get hydrated specimen (from cache or hydrate on demand)."""
        if slug not in self._hydrated:
            # Hydrate and keep alive until cache cleanup
            hydrated = await self._exit_stack.enter_async_context(
                self._registry.load_and_hydrate(slug)
            )
            self._hydrated[slug] = hydrated
        return self._hydrated[slug]

    async def close(self):
        """Cleanup all hydrated specimens."""
        await self._exit_stack.aclose()
        self._hydrated.clear()

# Usage at entry point
async def optimize(budget: float, ...):
    registry = SpecimenRegistry()
    cache = HydrationCache(registry)

    try:
        # All operations use cache
        hydrated1 = await cache.get("ducktape/2025-11-20-00")
        hydrated2 = await cache.get("ducktape/2025-11-20-00")  # Same instance!

        await run_critic(..., cache=cache)
        await run_grader(..., cache=cache)
    finally:
        await cache.close()  # Cleanup all at once
```

**Pros**:
- Simple lifecycle (explicit begin/end)
- No ref-counting complexity
- Works well for batch operations (prompt optimizer)
- Easy to reason about

**Cons**:
- Holds all hydrated specimens until session end (disk space)
- Not suitable for long-running servers (unless periodic cleanup)
- Need to thread `cache` instead of `registry`

---

### Option B: Ref-Counted Cache (More Complex)

**Concept**: Track how many contexts are using each specimen, cleanup when unused.

```python
class RefCountedHydrationCache:
    """Ref-counted cache of hydrated specimens."""

    def __init__(self, registry: SpecimenRegistry):
        self._registry = registry
        self._entries: dict[str, CacheEntry] = {}

    @asynccontextmanager
    async def load(self, slug: str) -> AsyncIterator[HydratedSpecimen]:
        """Load specimen (hydrate on demand, ref-count, cleanup when unused)."""
        # Acquire entry (increment ref count)
        entry = await self._acquire(slug)
        try:
            yield entry.hydrated
        finally:
            # Release entry (decrement ref count, cleanup if zero)
            await self._release(slug)

    async def _acquire(self, slug: str) -> CacheEntry:
        if slug not in self._entries:
            # First use: hydrate now
            hydrated = await self._hydrate(slug)
            self._entries[slug] = CacheEntry(hydrated=hydrated, ref_count=1)
        else:
            # Already cached: increment ref count
            self._entries[slug].ref_count += 1
        return self._entries[slug]

    async def _release(self, slug: str):
        entry = self._entries[slug]
        entry.ref_count -= 1
        if entry.ref_count == 0:
            # Last user released: cleanup now
            await self._cleanup(slug)
            del self._entries[slug]

# Usage (same API as current load_and_hydrate)
async def run_critic(..., cache: RefCountedHydrationCache):
    async with cache.load(specimen_slug) as hydrated:
        # Use hydrated
        pass
    # Cleanup happens automatically when ref count hits zero
```

**Pros**:
- Automatic cleanup when no longer needed
- Works for long-running servers
- Memory/disk efficient (only keeps what's in use)
- Drop-in replacement for `load_and_hydrate()`

**Cons**:
- Ref-counting complexity (potential bugs if acquire/release mismatched)
- Concurrent access needs locking (asyncio.Lock per slug)
- Cleanup timing less predictable

---

### Option C: Explicit Pre-Hydration (Already Partially Done)

**Concept**: Caller explicitly hydrates upfront and manages cleanup.

```python
# Current approach in prompt_optimizer.py
async def hydrate_train_specimens(registry: SpecimenRegistry, slugs: list[str]):
    async with AsyncExitStack() as stack:
        specimen_paths = {}
        for slug in slugs:
            hydrated = await stack.enter_async_context(registry.load_and_hydrate(slug))
            specimen_paths[slug] = hydrated.content_root
        yield specimen_paths
        # Cleanup when exiting context

# Usage
async with hydrate_train_specimens(registry, ["ducktape/2025-11-20-00", ...]) as paths:
    # All operations use pre-hydrated paths
    await run_critic(..., content_root=paths[specimen_slug])
```

**Pros**:
- Explicit control over lifecycle
- Already implemented in one place
- No new abstractions needed
- Clear begin/end boundaries

**Cons**:
- Caller must know all specimens upfront
- Not suitable for on-demand hydration
- Duplicated pattern across entry points

---

## Recommendation: Start with Option A (Session-Scoped)

**Rationale**:
1. **Simplest to implement**: No ref-counting, no complex lifecycle
2. **Fits existing patterns**: prompt_optimizer.py already does this manually
3. **Easy to thread**: Pass `cache` instead of `registry` to operations
4. **Explicit cleanup**: Caller controls when to release resources
5. **Testable**: Easy to inject mock cache in tests

**Evolution path**:
- Start: Option A for batch operations (CLI commands)
- Later: Add Option B if we need long-running servers with on-demand hydration
- Keep Option C as a low-level building block

## Proposed API

### Layer 1: SpecimenRegistry (Entry Point)
```python
class SpecimenRegistry:
    """Specimen metadata, manifest loading, archive management."""

    def __init__(self, *, base: Path | None = None, cache_dir: Path | None = None):
        self._base = base or find_specimens_base()
        self._cache_dir = cache_dir or _xdg_cache_base()

    @asynccontextmanager
    async def load_and_hydrate(self, slug: str) -> AsyncIterator[HydratedSpecimen]:
        """Load and hydrate specimen (single-use, cleanup on exit)."""
        # Current implementation (extract -> yield -> delete)
        ...

    def ensure_archive(self, manifest: SpecimenDoc, manifest_path: Path) -> Path:
        """Ensure tar.gz archive exists in cache."""
        ...

    def create_cache(self) -> HydrationCache:
        """Create a session-scoped hydration cache."""
        return HydrationCache(self)
```

### Layer 2: HydrationCache (Session-Scoped Caching)
```python
class HydrationCache:
    """Session-scoped cache of hydrated specimens.

    Hydrates on-demand and keeps all hydrated specimens alive until close().
    Use for batch operations where multiple operations use same specimens.
    """

    def __init__(self, registry: SpecimenRegistry):
        self._registry = registry
        self._hydrated: dict[str, HydratedSpecimen] = {}
        self._exit_stack = AsyncExitStack()

    async def get(self, slug: str) -> HydratedSpecimen:
        """Get hydrated specimen (from cache or hydrate on first access)."""
        ...

    async def close(self):
        """Cleanup all hydrated specimens."""
        ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
```

## Usage Patterns

### Pattern 1: Single Operation (No Caching)
```python
# CLI command that operates on one specimen
@app.command()
async def check(specimen: str):
    registry = SpecimenRegistry()

    # Use registry directly (hydrate -> use -> cleanup)
    async with registry.load_and_hydrate(specimen) as hydrated:
        await run_critic(..., hydrated=hydrated)
```

### Pattern 2: Batch Operations (With Caching)
```python
# CLI command that operates on multiple specimens
@app.command()
async def optimize(budget: float):
    registry = SpecimenRegistry()

    async with registry.create_cache() as cache:
        # Multiple operations, cache prevents re-hydration
        for specimen in train_specimens:
            hydrated = await cache.get(specimen)
            await run_critic(..., hydrated=hydrated)

        for specimen in train_specimens:
            hydrated = await cache.get(specimen)  # From cache!
            await run_grader(..., hydrated=hydrated)
    # All cleanup happens here
```

### Pattern 3: Pre-Hydrate for Docker Mounts
```python
# Prompt optimizer needs persistent paths for Docker volumes
@app.command()
async def optimize(budget: float):
    registry = SpecimenRegistry()

    async with registry.create_cache() as cache:
        # Pre-hydrate all specimens
        specimen_paths = {}
        for slug in train_specimens:
            hydrated = await cache.get(slug)
            specimen_paths[slug] = hydrated.content_root

        # Mount paths stay valid until cache closes
        await run_prompt_optimizer(..., specimen_paths=specimen_paths)
```

## Threading Changes

**Current (classmethods)**:
```python
async with SpecimenRegistry.load_and_hydrate(slug) as hydrated:
    ...
```

**Proposed (explicit threading)**:

**Option 1: Thread registry, use direct hydration**
```python
async def run_critic(..., *, registry: SpecimenRegistry):
    async with registry.load_and_hydrate(specimen_slug) as hydrated:
        ...

# Call site
await run_critic(..., registry=registry)
```

**Option 2: Thread cache, use cached hydration**
```python
async def run_critic(..., *, cache: HydrationCache):
    hydrated = await cache.get(specimen_slug)
    # Use hydrated (stays alive until cache closes)
    ...

# Call site (batch operations)
async with registry.create_cache() as cache:
    await run_critic(..., cache=cache)
    await run_grader(..., cache=cache)
```

**Option 3: Caller hydrates, thread HydratedSpecimen**
```python
async def run_critic(..., *, hydrated: HydratedSpecimen):
    # Just use the already-hydrated specimen
    ...

# Call site decides hydration strategy
async with registry.load_and_hydrate(slug) as hydrated:
    await run_critic(..., hydrated=hydrated)

# Or with cache
hydrated = await cache.get(slug)
await run_critic(..., hydrated=hydrated)
```

**Recommendation**: Start with Option 3 (thread HydratedSpecimen). It's the most flexible:
- Caller controls hydration strategy (direct, cached, pre-hydrated)
- Functions don't care about caching
- Easy to test (mock HydratedSpecimen)

## Migration Strategy

### Phase 1: Add HydrationCache (non-breaking)
1. Add `HydrationCache` class to `specimens/registry.py`
2. Add `SpecimenRegistry.create_cache()` method
3. Keep existing `load_and_hydrate()` classmethod working

### Phase 2: Promote registry to instance-based
1. Add instance methods to `SpecimenRegistry`
2. Thread `registry` through all entry points
3. Update functions to accept `registry` parameter

### Phase 3: Update batch operations to use cache
1. Identify commands that operate on multiple specimens
2. Use `registry.create_cache()` instead of repeated `load_and_hydrate()`
3. Measure performance improvement

### Phase 4: Consider threading HydratedSpecimen
1. Change function signatures to accept `hydrated: HydratedSpecimen`
2. Move hydration responsibility to caller
3. Simplifies function signatures (no registry/cache parameter)

## Open Questions

1. **Cache location for hydrated specimens**: Should we use ~/.cache/adgn-llm/hydrated/ instead of tmpdir?
   - **Pro**: Persists across processes, can reuse between runs
   - **Con**: Need explicit cleanup strategy, disk space management
   - **Recommendation**: Start with tmpdir (current), consider persistent later

2. **Cache size limits**: Should HydrationCache have a max size?
   - **Pro**: Prevents disk space issues
   - **Con**: Adds complexity (LRU eviction)
   - **Recommendation**: No limit for session-scoped (short-lived), consider for persistent

3. **Concurrent access**: Do we need locking for concurrent operations?
   - **Pro**: Safe for asyncio concurrent operations
   - **Con**: Adds complexity
   - **Recommendation**: No locking for session-scoped (single owner), add if needed for shared cache

4. **Interface choice**: Thread `registry`, `cache`, or `HydratedSpecimen`?
   - **registry**: Caller decides hydration per-operation
   - **cache**: Caller creates cache, functions hydrate on-demand
   - **hydrated**: Caller handles all hydration, functions just use it
   - **Recommendation**: Start with `hydrated` (most flexible, simplest functions)

## Performance Considerations

**Typical specimen sizes**:
- Small: ~1-5 MB compressed, ~5-20 MB extracted
- Medium: ~5-20 MB compressed, ~20-100 MB extracted
- Large: ~20-50 MB compressed, ~100-500 MB extracted

**Extraction time** (rough estimates):
- Small: ~0.1-0.3 seconds
- Medium: ~0.3-1 seconds
- Large: ~1-5 seconds

**Benefit of caching**:
- Prompt optimizer with 5 train specimens, 3 operations each:
  - Without cache: 15 extractions (~5-15 seconds overhead)
  - With cache: 5 extractions (~1-5 seconds overhead)
  - **Savings**: 4-10 seconds per optimization run

**Disk space**:
- Session cache with 10 specimens: ~200-500 MB disk usage (temporary)
- Acceptable for batch operations, manageable for CLI commands

## Next Steps

1. **Implement Option A (HydrationCache)** in specimens/cache.py
2. **Update prompt_optimizer.py** to use cache instead of manual AsyncExitStack
3. **Measure performance improvement** on prompt optimization runs
4. **Consider threading HydratedSpecimen** to simplify function signatures
5. **Evaluate persistent cache** if we see repeated hydration across process invocations
