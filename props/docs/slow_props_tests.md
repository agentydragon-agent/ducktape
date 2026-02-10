# Props Tests Performance Analysis

Generated: 2026-02-10

## Profiling Results

From `bazel test //props/agents/critic:test_e2e --test_arg=-s --test_arg=--durations=0`:

```
30.16s call     test_critic_zero_issues     (first test: includes image push)
20.82s setup    test_critic_zero_issues     (first test: postgres + db + migrations)
 7.25s call     test_python3_can_import_and_inspect_props
 5.63s call     test_critic_submit_with_issues
 1.22s setup    test_python3_can_import_and_inspect_props
 1.21s setup    test_critic_submit_with_issues
```

**Total: 68.62s for 3 tests on RBE (BuildBuddy)**

**Key findings:**

- First test pays ~51s (21s setup + 30s call with image push)
- Subsequent tests: ~6-8s each (shared postgres container)
- Tests are **hermetic** - run on RBE without internet access

## Root Causes

### 1. First Test Pays All Startup Costs (~18s)

- Loading Bazel-bundled images via `docker load` (~14s for postgres, ~1s for ryuk)
- PostgreSQL testcontainer startup (~2.5s)
- Database creation + Alembic migrations (~0.3s)
- Fixture sync (~0.2s)

**Note:** Container images (postgres, registry, ryuk) are bundled as Bazel tarballs and loaded via `docker load`. No Docker Hub downloads occur at test time - this is fully hermetic.

### 2. RBE Starts Fresh MicroVMs with Empty Docker Cache

BuildBuddy RBE runs each test in a fresh Firecracker microVM. The Docker daemon starts with an **empty image cache**, so `docker load` must fully unpack images every run.

Timing comparison:

- Local (warm cache): `docker load postgres` = **0.9s**
- Local (cold cache): `docker load postgres` = **2.7s**
- RBE (always cold): `docker load postgres` = **14s**

The 14s on RBE is due to cold Docker cache + microVM I/O overhead.

### 3. First Test Pushes Full Image (~30s call time)

From httpx logs, first test calls `crane_push()` which uploads 6 blobs:

- sha256:b951... (1MB)
- sha256:4831... (28MB)
- sha256:4b55... (48MB)
- sha256:0653... (118MB)
- sha256:135c... (10KB)
- sha256:39c7... (1.6KB)

The registry is function-scoped (fresh per test), so each test pushes all blobs. Subsequent tests benefit from Docker layer caching but still pay registry overhead.

### 4. Per-Test Database Recreation

The `synced_db` fixture chain:

```
synced_db → db (function-scoped) → postgres_base_config (session-scoped)
```

Each test creates a fresh database (reusing postgres container). Migrations run every time.

## Optimization Opportunities

### High Impact

1. **Runner recycling** - Preserve microVM state across test runs. BuildBuddy supports recycling runners via exec properties:

   ```python
   # In BUILD.bazel
   py_test(
       name = "test_e2e",
       exec_properties = {
           "test.recycle-runner": "true",
       },
       ...
   )
   ```

   This keeps the Docker daemon and its image cache warm between test invocations, potentially reducing the 14s postgres load to ~1s (warm cache).

2. **Session-scoped image push** - Push images once per pytest session, not per test. Tests can share the registry.

3. **Module-scoped synced database** - For tests that don't conflict, share the synced database.

4. **Split E2E tests into separate Bazel targets** - Each test becomes a parallel RBE job.

### Medium Impact

1. **Lazy blob push** - Only push blobs that changed since last push.

2. **Pre-warmed registry** - Push images during session setup fixture.

3. **Podman instead of Docker** - BuildBuddy's RBE image includes podman. Podman may have faster cold-start performance for container operations since it doesn't require a daemon. Worth benchmarking.

### Low Impact

1. **Lighter base images** - Reduce blob sizes.

## Test Timing by Category

### E2E Tests (container-based, RBE)

| Test                                      | Setup  | Call   | Notes                                  |
| ----------------------------------------- | ------ | ------ | -------------------------------------- |
| test_critic_zero_issues                   | 20.82s | 30.16s | First: postgres + db + full image push |
| test_critic_submit_with_issues            | 1.21s  | 5.63s  | Shared postgres, cached layers         |
| test_python3_can_import_and_inspect_props | 1.22s  | 7.25s  | Simpler fixture chain                  |

### DB Tests (no containers)

From `test_split_based_rls.py`:

- First test: ~30s (postgres + db + migrations + sync)
- Subsequent tests: <1s each (fast queries)

## Recommendations

### Quick Win: Split E2E Tests

Each E2E test in its own `py_test` target allows Bazel to parallelize across RBE:

```python
# BUILD.bazel - instead of one py_test with all tests
py_test(name = "test_critic_zero_issues", srcs = ["test_e2e.py"], ...)
py_test(name = "test_critic_submit_with_issues", srcs = ["test_e2e.py"], ...)
```

### Medium-Term: Session-Scoped Infrastructure

```python
@pytest_asyncio.fixture(scope="session")
async def pushed_images(e2e_registry_url):
    """Push all images once at session start."""
    digests = {}
    for image in [critic_image, grader_image, ...]:
        digests[image.name] = await crane_push(image, e2e_registry_url)
    return digests
```

## Profiling Infrastructure

### Logging with Timestamps

Tests output timestamps via `conftest.py`:

```
HH:MM:SS.mmm LEVEL logger: message
```

Use `bazel run //target -- --durations=0` for per-phase timing breakdown.

### OpenTelemetry Spans

Slow operations are instrumented with OpenTelemetry spans. Traces are exported to `TEST_UNDECLARED_OUTPUTS_DIR/traces.json` at session end.

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("database.recreate"):
    database.recreate()
```

Configure tracing in `props/conftest.py` via `pytest_configure` and `pytest_sessionfinish` hooks.

### Image Loading Timing

`test_util/image_loader.py` logs detailed timing for each `load_image()` call:

```
TIMING: load_image(tarball.tar) took 1.23s total (resolve=0.01s, docker_load=1.22s): Loaded image: postgres:16
```
