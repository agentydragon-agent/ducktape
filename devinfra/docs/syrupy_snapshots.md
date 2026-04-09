# Syrupy Snapshot Workflow

## What snapshots are

Snapshot tests use [syrupy](https://github.com/syrupy-project/syrupy) to compare
test output against stored `.ambr` files in `__snapshots__/` directories. The `.ambr`
files must be listed in the test target's `data` attribute.

## Updating snapshots today (local execution)

```bash
bb test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results \
  --remote_executor="" --config=nolint
```

Local execution creates runfiles as **symlinks into the source tree**. Syrupy
modifies the `.ambr` file in-place, which writes through the symlink directly
into the source tree. No copy step needed. Commit the updated `.ambr` files.

## Why this doesn't work on RBE

On RBE, the test runs on a remote worker. Syrupy writes the updated `.ambr` to
the worker's sandbox filesystem. From Bazel's perspective the `.ambr` is a **test
input** (declared in `data`), not a **declared output** — so Bazel doesn't capture
the modification. The updated file is lost when the action finishes.

`--remote_download_regex` can't help either: it downloads declared build/test
outputs matching a regex, but the `.ambr` file isn't a declared output.

## Goal: make snapshot updates work on RBE

Copy updated `.ambr` files to `$TEST_UNDECLARED_OUTPUTS_DIR` after syrupy writes
them. Bazel always downloads undeclared test outputs to
`bazel-testlogs/<target>/test.outputs/`, even with `--remote_download_minimal`.

The retrieval workflow would be:

```bash
# 1. Run snapshot update on RBE
bb-remote test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results

# 2. Copy updated snapshots from undeclared outputs back to source tree
cp bazel-testlogs/path/to/snapshot_test/test.outputs/__snapshots__/snapshot_test.ambr \
   path/to/__snapshots__/snapshot_test.ambr
```

## Syrupy's pytest plugin hooks

Syrupy registers as a pytest plugin with these hooks (from `syrupy/__init__.py`):

| Hook                              | Timing             | Purpose                                                   |
| --------------------------------- | ------------------ | --------------------------------------------------------- |
| `pytest_addoption`                | Startup            | Registers `--snapshot-update`, `--snapshot-details`, etc. |
| `pytest_sessionstart`             | Before collection  | Creates `SnapshotSession` on `config._syrupy`             |
| `pytest_collection_modifyitems`   | After collection   | Feeds collected items to session                          |
| `pytest_collection_finish`        | After modification | Selects final items                                       |
| `pytest_runtest_logreport`        | After each phase   | Records pass/fail outcome per nodeid                      |
| `pytest_sessionfinish` (tryfirst) | After all tests    | Calls `session.finish()` → `flush_snapshot_write_queue()` |
| `pytest_terminal_summary`         | Terminal output    | Prints snapshot report (updated/created/unused counts)    |

### Key internal: `_queued_snapshot_writes`

During test execution, syrupy buffers snapshot writes in
`SnapshotSession._queued_snapshot_writes` — a `defaultdict` keyed by
`(extension_class, snapshot_location)` where `snapshot_location` is the
**absolute path** to the `.ambr` file. `flush_snapshot_write_queue()` iterates
this dict, calls `extension_class.write_snapshot(...)` for each entry, then
**clears the queue**.

## Options for the copy shim

### Option A: `pytest_sessionfinish` hook in `conftest.py`

Add a hook (without `tryfirst`) to the root `conftest.py`. It runs after
syrupy's `tryfirst` hook has flushed writes to disk. Glob for `.ambr` files
under `rootdir` and copy to `$TEST_UNDECLARED_OUTPUTS_DIR`.

```python
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    outputs_dir = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    if not outputs_dir or not getattr(session.config.option, "snapshot_update", False):
        return
    rootdir = Path(session.config.rootpath)
    for ambr_file in rootdir.rglob("__snapshots__/*.ambr"):
        relative = ambr_file.relative_to(rootdir)
        dest = Path(outputs_dir) / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ambr_file, dest)
```

**Pros:**

- Simple, no syrupy internals dependency
- Uses standard pytest hook ordering

**Cons:**

- Copies ALL `.ambr` files, not just updated ones (harmless but wasteful)
- Requires the test to depend on `//:conftest` — need to verify this is
  universal (many tests already do, but not all)
- Globbing may be slow if `rootdir` is large (unlikely in Bazel sandbox)

**Open question:** First attempt didn't produce undeclared outputs on RBE.
Possible causes:

1. Test didn't depend on `//:conftest`, so the hook never loaded
2. `rootdir` on RBE pointed somewhere unexpected (not where `.ambr` files live)
3. Sandbox restrictions prevented writing to `$TEST_UNDECLARED_OUTPUTS_DIR`

Debugging: run with `--test_output=streamed --test_arg=-s` and add print
statements to the hook to verify it fires and what paths it sees.

### Option B: Monkeypatch `flush_snapshot_write_queue` to record written files

In `pytest_sessionstart`, wrap syrupy's `flush_snapshot_write_queue()` to
capture which `(extension_class, snapshot_location)` pairs are written. In
`pytest_sessionfinish`, copy only those specific files.

```python
def pytest_sessionstart(session: pytest.Session) -> None:
    syrupy_session = getattr(session.config, "_syrupy", None)
    if not syrupy_session:
        return
    original_flush = syrupy_session.flush_snapshot_write_queue
    syrupy_session._written_locations: list[str] = []

    def patched_flush():
        for (_, snapshot_location), queued in syrupy_session._queued_snapshot_writes.items():
            if queued:
                syrupy_session._written_locations.append(snapshot_location)
        original_flush()

    syrupy_session.flush_snapshot_write_queue = patched_flush
```

**Pros:**

- Copies only files that syrupy actually wrote (precise)
- No filesystem globbing

**Cons:**

- Depends on syrupy internal API (`_queued_snapshot_writes`, method signature)
- Fragile across syrupy version upgrades
- Monkeypatching is harder to reason about

### Option C: Custom syrupy extension

#### Extension class hierarchy

```
SnapshotSerializer          (ABC: serialize())
SnapshotCollectionStorage   (ABC: read/write/delete snapshots, get_location, dirname)
SnapshotReporter            (diff rendering)
SnapshotComparator          (matches())
    └── AbstractSyrupyExtension  (combines all four)
            └── AmberSnapshotExtension  (file_extension="ambr", uses AmberDataSerializer)
```

#### Key methods on `SnapshotCollectionStorage` (the write path)

| Method                                           | Type                           | Purpose                                                                                            |
| ------------------------------------------------ | ------------------------------ | -------------------------------------------------------------------------------------------------- |
| `write_snapshot(snapshot_location, snapshots)`   | `@classmethod`, **final**      | Groups snapshots into a `SnapshotCollection`, calls `write_snapshot_collection()`                  |
| `write_snapshot_collection(snapshot_collection)` | `@classmethod @abstractmethod` | Actually writes to disk. Amber impl calls `AmberDataSerializer.write_file(collection, merge=True)` |
| `get_location(test_location, index)`             | `@classmethod`                 | Returns absolute path to `.ambr` file                                                              |
| `dirname(test_location)`                         | `@classmethod`                 | Returns `__snapshots__/` dir path                                                                  |

`write_snapshot` is marked "final, do not override" in its docstring. The
intended override point is `write_snapshot_collection`.

#### How syrupy calls extensions during flush

```
SnapshotSession.flush_snapshot_write_queue()
  → for (extension_class, snapshot_location), queued_writes in _queued_snapshot_writes.items():
      → extension_class.write_snapshot(snapshot_location=..., snapshots=...)    # classmethod
          → cls.write_snapshot_collection(snapshot_collection=...)              # classmethod
              → AmberDataSerializer.write_file(collection, merge=True)         # writes .ambr
```

All methods in the write path are **classmethods**. The `extension_class` stored
in `_queued_snapshot_writes` is the class itself (not an instance). This means
the extension subclass must be the class that syrupy stores — controlled either
by `--snapshot-default-extension` CLI flag or `snapshot.use_extension()`.

#### Subclass approach

Override `write_snapshot_collection` (the intended extension point, not
the "final" `write_snapshot`):

```python
from syrupy.extensions.amber import AmberSnapshotExtension

class BazelAmberExtension(AmberSnapshotExtension):
    @classmethod
    def write_snapshot_collection(cls, *, snapshot_collection):
        super().write_snapshot_collection(snapshot_collection=snapshot_collection)
        outputs_dir = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
        if not outputs_dir:
            return
        location = Path(snapshot_collection.location)
        dest = Path(outputs_dir) / location.name
        shutil.copy2(location, dest)
```

#### Wiring options

1. **`--snapshot-default-extension` CLI flag**: Pass
   `--test_arg=--snapshot-default-extension=path.to.module.BazelAmberExtension`
   when running with `--snapshot-update`. No fixture changes needed — applies
   globally. Can be added only for update runs, not normal test runs.

2. **Override the `snapshot` fixture** in `conftest.py`:

   ```python
   @pytest.fixture
   def snapshot(snapshot):
       return snapshot.use_extension(BazelAmberExtension)
   ```

   Pros: automatic for all tests that use the `snapshot` fixture.
   Cons: always active (not just during `--snapshot-update`), and the
   conftest must depend on the extension module.

3. **Conditional override**: Combine both — fixture checks
   `config.option.update_snapshots` and only swaps the extension when updating:

   ```python
   @pytest.fixture
   def snapshot(request, snapshot):
       if request.config.option.update_snapshots and os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR"):
           return snapshot.use_extension(BazelAmberExtension)
       return snapshot
   ```

**Pros:**

- Uses the intended extension point (`write_snapshot_collection`)
- Precise: only copies files that are actually written
- No monkeypatching, no globbing
- CLI flag approach requires zero code changes to tests

**Cons:**

- `write_snapshot_collection` is `@abstractmethod` on the base but the
  docstring for `write_snapshot` says "final, do not override" — the boundary
  between public/private API isn't perfectly clear
- CLI flag approach requires passing extra `--test_arg` flags
- Fixture override approach needs conftest dep wiring

## Plan: Option C via `py_test` macro

Option C is cleanest — uses the intended extension point, precise (only copies
written files), and can be wired automatically via the existing `py_test` macro
in `//devinfra/python:defs.bzl`.

### Components

**1. `BazelAmberExtension`** (`util/testing/bazel_snapshot_extension.py`)

```python
import os
import shutil
from pathlib import Path

from syrupy.extensions.amber import AmberSnapshotExtension


class BazelAmberExtension(AmberSnapshotExtension):
    """Amber extension that copies written snapshots to undeclared test outputs."""

    @classmethod
    def write_snapshot_collection(cls, *, snapshot_collection):
        super().write_snapshot_collection(snapshot_collection=snapshot_collection)
        outputs_dir = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
        if not outputs_dir:
            return
        src = Path(snapshot_collection.location)
        if not src.exists():
            return
        dest = Path(outputs_dir) / src.name
        shutil.copy2(src, dest)
```

The copy is a flat filename (`snapshot_test.ambr`) into
`$TEST_UNDECLARED_OUTPUTS_DIR`. No relative-path gymnastics needed since
each `py_test` target typically has one `.ambr` file.

Only active when `TEST_UNDECLARED_OUTPUTS_DIR` is set (Bazel test sandbox).
The extension is always the Amber extension — same serialization format,
same `.ambr` files — just with a post-write copy hook.

**2. `py_test` macro change** (`devinfra/python/defs.bzl`)

Add `uses_snapshots = False` parameter:

```starlark
def py_test(name, size = "small", requires_docker = False,
            uses_snapshots = False, tags = None, imports = None,
            args = None, deps = None, **kwargs):
    ...
    if uses_snapshots:
        args = (args or []) + [
            "--snapshot-default-extension=util.testing.bazel_snapshot_extension.BazelAmberExtension",
        ]
        deps = (deps or []) + [
            "//util/testing:bazel_snapshot_extension",
        ]
    ...
```

This injects the extension class path via syrupy's
`--snapshot-default-extension` CLI flag. Syrupy calls
`import_module_member(value)` on this string to load the class.

**3. Migrate existing snapshot tests**

Find all `py_test` targets with `data = [...*.ambr...]` and add
`uses_snapshots = True`. Could be done by gazelle or a one-off script.
There are only a handful of snapshot tests in the repo.

### Resulting workflow

**Tested and verified end-to-end on 2026-04-08.**

#### RBE (preferred for large tests / Docker tests)

```bash
# 1. Run snapshot update on RBE with toplevel download
#    Flag order matters: --remote_download_outputs=toplevel must come AFTER
#    --config=rbe to override --remote_download_minimal. Use bb (not bb-remote)
#    for flag ordering control.
bb test --config=rbe --remote_download_outputs=toplevel \
  //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results

# 2. Copy from undeclared outputs back to source tree
cp bazel-testlogs/path/to/snapshot_test/test.outputs/snapshot_test.ambr \
   path/to/__snapshots__/snapshot_test.ambr
```

**Why not `bb-remote`?** `bb-remote` appends `--config=rbe` after user args,
so `--remote_download_outputs=toplevel` gets overridden by
`--remote_download_minimal` from `--config=rbe`. Use `bb test --config=rbe`
directly to control flag ordering.

#### Local (simpler, no copy step)

```bash
bb test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results \
  --remote_executor="" --config=nolint
```

Syrupy writes through runfiles symlinks directly into the source tree.

**4. Snapshot mismatch hint**

When a snapshot test fails (assertion mismatch without `--snapshot-update`),
print the update command so the user knows how to fix it. This can be done
via `pytest_terminal_summary` in the root `conftest.py` or in the extension
itself. Check `session.config._syrupy.report` for assertion failures:

```python
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    syrupy_session = getattr(config, "_syrupy", None)
    if not syrupy_session or not syrupy_session.report:
        return
    if syrupy_session.report.num_updated or syrupy_session.report.num_created:
        return  # was an update run, no hint needed
    # Check for failed assertions (snapshot mismatches)
    failed = [r for r in syrupy_session.report.assertions if not r.success]
    if not failed:
        return
    target = os.environ.get("TEST_TARGET", "<target>")
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"To update snapshots, run:"
    )
    terminalreporter.write_line(
        f"  bb-remote test {target} --test_arg=--snapshot-update --nocache_test_results"
    )
    terminalreporter.write_line(
        f"Then copy from: bazel-testlogs/.../{Path(target).name}/test.outputs/"
    )
```

`TEST_TARGET` is set by Bazel in the test sandbox (e.g.,
`//mcp_infra/display:test_max_height`), so the hint includes the exact
target label.

### Why this is better than A/B

- **No globbing** — only copies files that syrupy actually wrote
- **No monkeypatching** — uses `write_snapshot_collection` override point
- **No conftest dep issues** — extension is wired via `py_test` `args`/`deps`
- **Zero test code changes** — existing `snapshot` fixture works unchanged,
  syrupy swaps the extension class via `--snapshot-default-extension`
- **Harmless when not updating** — the extension just adds a post-write copy;
  during normal test runs syrupy reads snapshots the same way (read path is
  inherited from `AmberSnapshotExtension` unchanged)
