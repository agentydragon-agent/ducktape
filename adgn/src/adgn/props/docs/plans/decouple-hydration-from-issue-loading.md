# Decouple Source Hydration from Issue Loading

## Problem

The current architecture has TWO ways to evaluate jsonnet, both accessible through friendly public APIs:

1. **`SnapshotRegistry.load_and_hydrate()`** - evaluates jsonnet + hydrates source
2. **`FilesystemLoader`** - evaluates jsonnet, returns Pydantic models

Both violate the intended architecture:
- **One-time setup**: `adgn-properties db sync` evaluates jsonnet → writes to database
- **All subsequent operations**: Read issues from `TruePositive`/`FalsePositive` ORM tables
- **Hydration**: Only extracts source code, never touches issue data

### Current Architecture Violations

#### Violation 1: SnapshotRegistry.load_and_hydrate()

```python
# snapshot_registry.py:677-738
async def load_and_hydrate(self, slug: SnapshotSlug) -> AsyncIterator[HydratedSnapshot]:
    """⚠️ PROBLEM: This method does TWO things:
    1. Evaluates jsonnet to load issues (lines 702-733)
    2. Extracts source code to disk (line 711)

    Every caller re-evaluates jsonnet, defeating the purpose of db sync.
    """
    # Evaluate jsonnet EVERY TIME (200+ times in GEPA run)
    result = _jsonnet_evaluate_all(snapshot_dir)  # ❌ jsonnet evaluation
    raw_issues, raw_fps = result

    # Hydrate source
    hydrated_root = resolve_source_root(man, snapshot_path)

    # Build record from jsonnet (not DB!)
    rec = SnapshotRecord(
        true_positives={...},  # ❌ From jsonnet
        false_positives={...}, # ❌ From jsonnet
    )

    yield HydratedSnapshot(record=rec, content_root=hydrated_root)
```

#### Violation 2: FilesystemLoader (Public API)

```python
# loaders/filesystem.py
class FilesystemLoader:
    """Public API that internally evaluates jsonnet."""

    def load_issues_for_snapshot(self, slug: SnapshotSlug):
        """⚠️ PROBLEM: Friendly public method that evaluates jsonnet internally."""
        issue_dict = evaluate_single_issue_file(issue_file)  # ❌ jsonnet evaluation
        # Returns Pydantic TruePositive/FalsePositive models
```

**Impact:** Anyone using `FilesystemLoader` (tests, GEPA, training examples) is indirectly evaluating jsonnet.

### Scale of Violation

**Components that violate the "load from DB" principle:**

1. **GEPA optimization** (gepa_adapter.py):
   - Lines 343-350: Uses FilesystemLoader to get TrainingExamples
   - Lines 372-385: Uses SnapshotRegistry.load_and_hydrate() for SnapshotInputs
   - **Result**: ~200 jsonnet evaluations per optimization run

2. **TrainingExample** (models/training_example.py):
   - Uses Pydantic `TruePositive`/`FalsePositive` models from FilesystemLoader
   - These models come from jsonnet, not DB

3. **Critic/Grader execution**:
   - Both use SnapshotRegistry.load_and_hydrate()
   - 1 jsonnet eval per run

4. **CLI commands**: 15+ call sites across cmd_snapshot.py, cmd_detector.py, main.py

5. **Tests**: ~20 test files call load_and_hydrate() or FilesystemLoader

### Pydantic Model Usage Audit

**Where Pydantic `TruePositive`/`FalsePositive` are used:**

1. **models/true_positive.py** (Pydantic definitions)
   - `TruePositive`, `FalsePositive`, `TruePositiveOccurrence`, `FalsePositiveOccurrence`

2. **FilesystemLoader** (sync path)
   - Returns Pydantic models from jsonnet evaluation

3. **TrainingExample** (models/training_example.py)
   - Fields: `true_positives: list[TruePositive]`, `false_positives: list[FalsePositive]`
   - Used by GEPA for dataset generation

4. **db/sync.py** (transport layer)
   - Uses FilesystemLoader to get Pydantic models → converts to ORM → writes to DB

5. **Grader/Critic models** (imports `Occurrence`)
   - Use `Occurrence` type from models.true_positive

**Separate models in snapshot_registry.py:**
- `TruePositiveIssue` (Pydantic wrapper)
- `KnownFalsePositive` (Pydantic wrapper)
- These are what GEPA's SnapshotInput actually uses (via hydration)

**ORM models (db/models.py):**
- `TruePositive` (SQLAlchemy)
- `FalsePositive` (SQLAlchemy)
- `Snapshot` (SQLAlchemy) - exists but has no relationships!

**Finding:** Pydantic models are ONLY used in sync path (FilesystemLoader → DB) and as intermediates in TrainingExample. They can be made private to the sync module.

## Solution Design

### Architecture Principles

1. **Physical isolation**: All jsonnet code in `db/sync/` directory (not just `_sync_internal.py`)
2. **Type-driven safety**: ORM models are the public API; Pydantic models are private sync transports
3. **No friendly wrappers**: FilesystemLoader is private; no public API that internally calls jsonnet
4. **ORM-first**: TrainingExample, GEPA, all runtime code uses ORM models
5. **SnapshotRegistry elimination**: Replace with ORM `Snapshot` model + methods

### New Architecture

```python
# After migration:

# 1. Sync path (private, in db/sync/)
db/sync/
  __init__.py          # Public: sync_snapshots(), sync_issues()
  _jsonnet.py          # Private: evaluate_snapshot_issues(), evaluate_single_issue_file()
  _loader.py           # Private: FilesystemLoader (sync machinery only)
  _transport.py        # Private: Pydantic TruePositive/FalsePositive (for jsonnet→DB only)

# 2. ORM models (public, in db/models.py)
class Snapshot(Base):
    """Snapshot ORM model with relationships."""
    slug = Column(String, primary_key=True)
    true_positives = relationship("TruePositive", back_populates="snapshot")
    false_positives = relationship("FalsePositive", back_populates="snapshot")

    @asynccontextmanager
    async def hydrate(self) -> AsyncIterator[HydratedSnapshot]:
        """Hydrate source code only (no issue loading)."""
        # Extract source to temp dir
        # Yield HydratedSnapshot with this Snapshot's ORM relationships
        pass

class TruePositive(Base):
    """ORM model for true positives."""
    snapshot_slug = Column(String, ForeignKey("snapshots.slug"))
    snapshot = relationship("Snapshot", back_populates="true_positives")

class FalsePositive(Base):
    """ORM model for false positives."""
    snapshot_slug = Column(String, ForeignKey("snapshots.slug"))
    snapshot = relationship("Snapshot", back_populates="false_positives")

# 3. Runtime usage (no jsonnet!)
session = get_session()
snapshot = session.query(Snapshot).filter_by(slug="ducktape/2025-11-26-00").one()

# Hydrate source
async with snapshot.hydrate() as hydrated:
    # Access ORM relationships (already loaded from DB)
    tps = snapshot.true_positives  # ORM query, NOT jsonnet
    fps = snapshot.false_positives

    # Create training example from ORM models
    example = TrainingExample(
        snapshot_slug=snapshot.slug,
        true_positives=tps,  # ORM models
        false_positives=fps,
    )
```

### Phase 1: Physical Isolation

**STATUS:** ✅ COMPLETE

**Create sync directory structure:**

```bash
src/adgn/props/db/sync/
  __init__.py          # Public API: sync_snapshots(), sync_issues()
  _sync.py             # Private: sync_snapshots_to_db(), sync_issues_to_db()
  _jsonnet.py          # Private: jsonnet evaluation only
  _loader.py           # Private: FilesystemLoader (moved from loaders/)
```

**Move radioactive code:**

1. Move `loaders/filesystem.py` → `db/sync/_loader.py`
2. Move jsonnet code from `snapshot_registry.py` → `db/sync/_jsonnet.py`
3. Move Pydantic `TruePositive`/`FalsePositive` from `models/true_positive.py` → `db/sync/_transport.py`
4. Keep `Occurrence` types in models (used by grader/critic)

**Update db/sync/__init__.py:**

```python
"""Sync snapshots and issues from filesystem to database.

⚠️⚠️⚠️ DO NOT IMPORT PRIVATE MODULES FROM THIS PACKAGE ⚠️⚠️⚠️

Public API:
- sync_snapshots(session, base_path)
- sync_issues(session, base_path)

Everything else (_jsonnet.py, _loader.py, _transport.py) is private sync machinery.
"""

from .sync import sync_snapshots, sync_issues

__all__ = ["sync_snapshots", "sync_issues"]
```

**Phase 1 Technical Details:**

**1. Import resolution: ELIMINATED custom callback**

**Original implementation** had a custom `_jsonnet_importer` with two-candidate resolution:
- cand1: relative to base
- cand2: JSONNET_LIBDIR fallback

**Simplified implementation:** Completely removed custom import callback!
- Jsonnet's default resolution with `jpathdir=[str(JSONNET_LIBDIR)]` handles everything
- Issue files use `import '../../lib.libsonnet'` which resolves relative to the importing file
- No custom logic needed - jsonnet does it all

**Benefits:**
- 30 lines of code deleted
- Simpler, more maintainable
- Uses standard jsonnet features

**2. Single evaluation function (batch only):**

**ELIMINATED redundancy:** Originally had two evaluation functions (`evaluate_single_issue_file` and `evaluate_snapshot_issues`), but single-file was completely redundant.

**Current implementation:**
- Only `evaluate_snapshot_issues(snapshot_dir)` exists - batch loads all *.libsonnet files and handles TP/FP splitting
- Both FilesystemLoader and SnapshotRegistry now use the batch function
- FilesystemLoader converts raw dicts → Pydantic models with proper keyword-argument instantiation

**Benefits:**
- Simpler codebase (one evaluation path, not two)
- More efficient (batch evaluation is faster than per-file loop)
- Clearer intent (sync is a batch operation)

**3. SnapshotSlug parsing: FIXED**

**Before:**
```python
slug_parts = str(slug).split("/")  # ❌ Manual parsing
if len(slug_parts) != 2:
    raise ValueError(...)
```

**After:**
```python
from ...ids import split_snapshot_slug

repo, version = split_snapshot_slug(slug)  # ✅ Use helper
snapshot_dir = self.specimens_dir / repo / version
```

**4. Direct ORM construction (eliminated raw dicts)**

**Problem:** Manual dict construction is error-prone and not type-safe:
```python
# ❌ BEFORE: Easy to forget fields, no compile-time checking
issue_data = {
    "snapshot_slug": issue.snapshot_slug,
    "tp_id": issue.tp_id,
    "rationale": issue.rationale,
    "occurrences": [occ.model_dump(mode="json") for occ in issue.occurrences],
}
stmt = insert(TruePositive).values(**issue_data)
session.execute(stmt)
```

**Solution:** Create ORM instances directly, let SQLAlchemy handle everything:
```python
# ✅ AFTER: Type-safe, can't forget fields
orm_issue = TruePositive(
    snapshot_slug=issue.snapshot_slug,
    tp_id=issue.tp_id,
    rationale=issue.rationale,
    occurrences=issue.occurrences,  # PydanticColumn handles serialization
)
session.add(orm_issue)

# For updates: direct assignment
existing.rationale = issue.rationale
existing.occurrences = issue.occurrences
```

**Benefits:**
- Type-safe: Constructor signature checked at compile time
- Can't forget fields: Missing required field = immediate error
- Cleaner: No manual serialization, PydanticColumn does it
- Safer: SQLAlchemy validates types and handles DB specifics
- No raw SQL: Uses ORM patterns throughout

### Phase 2: ORM Adapters and Grader Integration

**Goal:** Enable grader to load issues from database while preserving current prompt format.

**Relationships already exist** (in `db/models.py:143-148`):
```python
class Snapshot(Base):
    # Relationships (already present)
    true_positives: Mapped[list[TruePositive]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan"
    )
    false_positives: Mapped[list[FalsePositive]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan"
    )
```

**Add thin adapter layer** to convert ORM → Pydantic wrappers for grader:

```python
# db/adapters.py (new file)
from adgn.props.db.models import TruePositive, FalsePositive
from adgn.props.snapshot_registry import TruePositiveIssue, KnownFalsePositive
from adgn.props.ids import TruePositiveID, FalsePositiveID
from adgn.props.rationale import Rationale

def orm_to_wrapper_tps(tps: list[TruePositive]) -> list[TruePositiveIssue]:
    """Convert ORM TruePositive → TruePositiveIssue wrapper for grader.

    ORM splits ID into (snapshot_slug, tp_id), wrapper uses single namespaced ID.
    Occurrences work as-is (PydanticColumn gives us correct type).
    """
    return [
        TruePositiveIssue(
            id=TruePositiveID(f"{tp.snapshot_slug}/{tp.tp_id}"),
            rationale=Rationale(tp.rationale),  # Validates 10-5000 char constraint
            occurrences=tp.occurrences,  # Already list[TruePositiveOccurrence]
        )
        for tp in tps
    ]

def orm_to_wrapper_fps(fps: list[FalsePositive]) -> list[KnownFalsePositive]:
    """Convert ORM FalsePositive → KnownFalsePositive wrapper for grader."""
    return [
        KnownFalsePositive(
            id=FalsePositiveID(f"{fp.snapshot_slug}/{fp.fp_id}"),
            rationale=Rationale(fp.rationale),
            occurrences=fp.occurrences,  # Already list[FalsePositiveOccurrence]
        )
        for fp in fps
    ]
```

**Update grader** to load from database:

```python
# grader/grader.py
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.adapters import orm_to_wrapper_tps, orm_to_wrapper_fps

async def grade_critique_by_id(session, critique_id, client, verbose=False):
    critique = _get_required_critique(session, critique_id)
    snapshot_slug = critique.snapshot_slug

    # Load snapshot and issues from database (no jsonnet!)
    snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()

    # Convert ORM → wrappers for grader prompt
    canonical_typed = orm_to_wrapper_tps(snapshot.true_positives)
    fp_typed = orm_to_wrapper_fps(snapshot.false_positives)

    # Build grader prompt (unchanged - still dumps Pydantic to JSON)
    prompt = build_grade_from_json_prompt(
        true_positive_issues=canonical_typed,
        known_fps=fp_typed,
        ...
    )

    # Execute grading (unchanged)
    await run_grader(...)
```

**Pros:**
- Minimal changes (~20 lines of adapter code)
- Grader prompt/template unchanged (proven to work)
- Completes Phase 2 migration goal (no jsonnet evaluation)
- ORM occurrences already have correct Pydantic type (PydanticColumn magic)

**Cons:**
- Still dumps big JSON blobs into prompt (current approach)
- Maintains wrapper types (TruePositiveIssue, KnownFalsePositive)

**Alternative approach (future enhancement):** Give grader Docker + psql access to query database directly (similar to prompt-optimizer pattern in `db/agent_queries.py`). Agent would query TPs/FPs incrementally via SQL templates instead of receiving full JSON dump. More work but cleaner architecture - defer to separate OKR.

**TODO:** Consider moving ORM→Pydantic adapters (`orm_to_wrapper_tps`, `orm_to_wrapper_fps`) into `grader/` module if they're only used by grader. If sync also needs them (unlikely), keep in `db/adapters.py`. Evaluate after seeing actual usage patterns.

### Phase 3: Migration Plan

**STATUS:** 🚧 IN PROGRESS (resolve_critic_scope migrated, other load_and_hydrate calls remaining)

**Overview:** Phase 3 has two parallel tracks:
1. **Split SnapshotRegistry** → `SyncLoader` (private) + `SnapshotHydrator` (public)
2. **Migrate call sites** to use `SnapshotHydrator` + ORM for issues

#### Phase 3a: Split SnapshotRegistry (SnapshotHydrator extraction)

**Problem:** SnapshotRegistry does TWO things:
1. **Issue loading from jsonnet** - Should be sync-only (replaced by ORM)
2. **Source code hydration** - Still needed by runtime (extracts bundle to temp dir)

**Solution:** Split into two classes:

```python
# db/sync/_loader.py (private)
class SyncLoader:
    """Private sync machinery: jsonnet + hydration for sync only.

    Used only by db-sync command to populate database.
    """
    def __init__(self, base_path: Path):
        self.base_path = base_path

    def load_issues_for_snapshot(self, slug: SnapshotSlug):
        """Load issues from jsonnet (sync path only)."""
        # Same as current FilesystemLoader
        repo, version = split_snapshot_slug(slug)
        snapshot_dir = self.base_path / repo / version
        raw_tps, raw_fps = evaluate_snapshot_issues(snapshot_dir)
        # Return ORM instances directly
        return (
            [TruePositive(tp_id=id, snapshot_slug=slug, ...) for id, data in raw_tps.items()],
            [FalsePositive(fp_id=id, snapshot_slug=slug, ...) for id, data in raw_fps.items()],
        )

    async def hydrate_for_sync(self, slug: SnapshotSlug) -> HydratedSnapshot:
        """Hydrate source for sync only (no issue loading)."""
        # Extract source to temp dir
        # Return HydratedSnapshot with just content_root + files

# snapshot_hydrator.py (public, new file)
class SnapshotHydrator:
    """Public API for source code hydration only (no issue loading).

    Used by runtime components (grader, critic, GEPA, CLI) to extract
    source code to temporary directories.
    """
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.snapshots_config = self._load_snapshots_config()

    @asynccontextmanager
    async def hydrate(self, slug: SnapshotSlug) -> AsyncIterator[HydratedSnapshot]:
        """Hydrate source code only (no issue data).

        Returns HydratedSnapshot with:
        - content_root: Path to extracted source
        - all_discovered_files: set[Path] relative paths

        Issues must be loaded separately from database via ORM.
        """
        manifest = self._get_manifest(slug)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract source bundle
            bundle_path = await self._ensure_bundle_cached(manifest.bundle)
            content_root = Path(tmpdir) / "workspace"
            extract_bundle(bundle_path, content_root)

            # List files
            files = {path.relative_to(content_root) for path in content_root.rglob("*") if path.is_file()}

            yield HydratedSnapshot(
                content_root=content_root,
                all_discovered_files=files,
            )
```

**Migration steps:**

1. Create `snapshot_hydrator.py` with `SnapshotHydrator` class
   - Extract hydration logic from `SnapshotRegistry.load_and_hydrate()`
   - Remove all issue loading code
   - Return `HydratedSnapshot` with only source paths

2. Update `db/sync/_loader.py`:
   - Rename `FilesystemLoader` → `SyncLoader`
   - Keep all jsonnet evaluation logic
   - Add `hydrate_for_sync()` method (reuses SnapshotHydrator internals)

3. Update `HydratedSnapshot` dataclass:
   ```python
   @dataclass
   class HydratedSnapshot:
       """Hydrated snapshot with source code only (no issues).

       Issues must be loaded from database via ORM Snapshot model.
       """
       content_root: Path
       all_discovered_files: set[Path]
       # REMOVED: record field (no more SnapshotRecord with issues)
   ```

4. Delete `SnapshotRegistry` after all call sites migrated

**Runtime components that need SnapshotHydrator:**
- Grader (needs source for Docker context)
- Critic CLI (needs source for review)
- GEPA (needs source for training examples)
- Detector commands (runs tools on source)
- Prompt optimizer (needs source for agent)
- Lint issue (validates paths)

#### Phase 3b: Migrate call sites to use SnapshotHydrator + ORM

Replace all calls to `SnapshotRegistry.load_and_hydrate()`:

```python
# OLD (jsonnet evaluation + hydration)
async with registry.load_and_hydrate(slug) as hydrated:
    tps = hydrated.record.true_positives  # From jsonnet!
    fps = hydrated.record.false_positives

# NEW (separate hydration + ORM issues)
hydrator = SnapshotHydrator.from_package_resources()
session = get_session()
snapshot = session.query(Snapshot).filter_by(slug=slug).one()

async with hydrator.hydrate(slug) as hydrated:
    # Source from hydrator
    workspace = hydrated.content_root
    files = hydrated.all_discovered_files

    # Issues from ORM
    tps = snapshot.true_positives
    fps = snapshot.false_positives
```

**Affected files (~50+ call sites):**
- gepa_adapter.py (load_datasets, hydrate_snapshot_examples)
- critic.py (run_critic)
- grader.py (grade_critique)
- cmd_snapshot.py, cmd_detector.py, main.py (15+ CLI commands)
- lint_issue.py
- prompt_optimizer.py
- 20+ test files

**Progress tracker:**
- ✅ `resolve_critic_scope()` migrated to load from DB (no registry param)
- ✅ `Snapshot.files_with_issues()` method added (ORM helper)
- 🚧 Remaining: ~16 `load_and_hydrate()` call sites need migration

#### Phase 3c: Eliminate FilesystemLoader usage

Replace `FilesystemLoader` (now renamed to `SyncLoader` in `db/sync/_loader.py`) with direct DB queries:

```python
# OLD (jsonnet evaluation)
loader = FilesystemLoader(base_path)
train_examples = loader.get_per_file_examples_for_split(Split.TRAIN)

# NEW (ORM from DB)
session = get_session()
train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN).all()

# Build training examples from ORM models + critic_scopes
for snapshot in train_snapshots:
    # Load critic scopes from YAML (still needed for file groupings)
    scopes = load_critic_scopes_for_snapshot(snapshot.slug)

    for scope in scopes:
        example = TrainingExample(
            snapshot_slug=snapshot.slug,
            split=snapshot.split,
            targeted_files=scope.files,
            true_positives=filter_catchable(snapshot.true_positives, scope.files),
            false_positives=filter_relevant(snapshot.false_positives, scope.files),
        )
```

**Affected components:**
- GEPA load_datasets()
- Training example generation
- Tests using SyncLoader (only in sync path)

#### Phase 3d: Grader/Critic serialization

Add ORM → Pydantic conversion at boundaries (if needed):

```python
# In grader output preparation
grader_output = GraderOutput(
    tp_matches=[
        orm_tp.to_pydantic()  # Add .to_pydantic() method to ORM models
        for orm_tp in matched_tps
    ]
)
```

### Phase 4: Verification and Cleanup

**Pre-commit hook:**

```python
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: no-sync-imports
      name: Prevent imports from db/sync/ private modules
      entry: 'from adgn\.props\.db\.sync\._'
      language: pygrep
      files: '^(?!src/adgn/props/db/sync/).*\.py$'
```

**Tombstone comments:**

Add at deletion sites explaining what was removed and why:

```python
# loaders/filesystem.py - DELETED
# This module has been moved to db/sync/_loader.py (private sync machinery).
# For loading issues at runtime, use ORM models:
#
#   session = get_session()
#   snapshot = session.query(Snapshot).filter_by(slug=slug).one()
#   tps = snapshot.true_positives  # ORM relationship
#
# See docs/plans/decouple-hydration-from-issue-loading.md for details.
```

**Tests:**

```python
def test_no_sync_imports_outside_sync_module():
    """Ensure no code outside db/sync/ imports private sync modules."""
    import ast
    # Find all .py files excluding db/sync/
    # Parse ASTs and check for imports from db.sync._*
    # Fail if any found
```

### Phase 5: Success Criteria

**Definition of Done:**

1. ✅ All jsonnet code physically isolated in `db/sync/`
2. ✅ `SyncLoader` private (in `db/sync/_loader.py`, renamed from FilesystemLoader)
3. ✅ Pydantic models private (in `db/sync/_transport.py`)
4. ✅ `SnapshotRegistry` deleted (split into `SnapshotHydrator` + `SyncLoader`)
5. ✅ `SnapshotHydrator` created (public API for source hydration only)
6. ✅ `HydratedSnapshot` simplified (no record field, just paths)
7. ✅ TrainingExample uses ORM models
8. ✅ GEPA uses ORM models (no SyncLoader)
9. ✅ All runtime code loads issues from DB (no jsonnet evaluation)
10. ✅ All runtime code uses `SnapshotHydrator` for source extraction
11. ✅ Pre-commit hooks prevent violations
12. ✅ Tombstone comments at all deletion sites
13. ✅ Full test suite passing
14. ✅ Zero imports of `db.sync._*` outside `db/sync/`
15. ✅ **Pydantic instantiation:** All Pydantic models instantiated with keyword arguments (`Model(field=value)`), NOT via `model_validate(dict)`. The `model_validate()` pattern should only be used for external/untrusted payloads at system boundaries.
16. ✅ **SnapshotSlug parsing:** All slug splitting uses `split_snapshot_slug()` helper from `ids.py`, NOT manual `str(slug).split("/")`
17. ✅ **Single specimen root definition:** Exactly one canonical function to resolve specimens root directory. Scan for `resources.files("adgn.props")` patterns and consolidate to single helper.
18. ✅ **Remove deprecated HydratedSnapshot methods:** After migration complete, remove temporary compat `record` field and deprecated properties (`manifest`, `slug`, `true_positives`, `false_positives`, `files_with_issues()`)
19. ✅ **Thread SnapshotHydrator through functions:** SnapshotHydrator instances created at CLI entry points and threaded through as parameters (like SnapshotRegistry was). No inline creation inside internal functions with `.from_package_resources()`. Imports always at module top, never inline.

**Verification commands:**

```bash
# No private sync imports outside sync module
rg "from adgn\.props\.db\.sync\._" --type py src/ tests/ | grep -v "src/adgn/props/db/sync/"

# No direct jsonnet imports outside sync module
rg "import _jsonnet" --type py src/ tests/ | grep -v "src/adgn/props/db/sync/"

# SnapshotRegistry fully removed
rg "SnapshotRegistry" --type py src/ tests/

# SyncLoader only in sync module (renamed from FilesystemLoader)
rg "SyncLoader|FilesystemLoader" --type py src/ tests/ | grep -v "src/adgn/props/db/sync/"

# SnapshotHydrator used in runtime (not in sync)
rg "SnapshotHydrator" --type py src/ tests/ | grep "src/adgn/props/db/sync/"
# (should return empty - hydrator should NOT be used in sync)

# Verify HydratedSnapshot has no record field
rg "HydratedSnapshot.*record" --type py src/ tests/
# (should return empty after migration)
```

## Migration Timeline

**Phase 1 (COMPLETE):** Physical isolation
- ✅ Created `db/sync/` directory
- ✅ Moved FilesystemLoader → `db/sync/_loader.py`
- ✅ Moved jsonnet code → `db/sync/_jsonnet.py`
- ✅ Simplified: eliminated custom import resolution (30 lines)
- ✅ Simplified: eliminated single-file evaluation (35 lines)
- ✅ Fixed SnapshotSlug parsing to use helper
- ✅ Fixed direct ORM construction (no raw dicts)

**Phase 2 (COMPLETE):** ORM adapters and grader integration
- ✅ Added `db/adapters.py` with ORM → Pydantic converters
- ✅ Updated grader to load from DB
- ✅ Added `Snapshot.files_with_issues()` method

**Phase 3 (IN PROGRESS):** Split SnapshotRegistry + migrate call sites
- 🚧 Phase 3a: Extract `SnapshotHydrator` (public, hydration only)
- 🚧 Phase 3b: Migrate ~16 `load_and_hydrate()` call sites
- 🚧 Phase 3c: Rename `FilesystemLoader` → `SyncLoader` (private)
- 🚧 Phase 3d: Update grader/critic serialization if needed

**Phase 4 (TODO):** Cleanup and verification
- Consolidate duplicate specimen root definitions:
  - `cli/cmd_build_bundle.py`: Use `specimens_definitions_root()` instead of `resources.files("adgn.props").joinpath("specimens")`
  - `snapshot_registry.py`: Use `specimens_definitions_root()` (same pattern)
  - `gepa/gepa_adapter.py`: Use `specimens_definitions_root()` (same pattern)
  - ✅ `snapshot_hydrator.py`: Already uses `specimens_definitions_root()`
- Remove deprecated HydratedSnapshot compat properties (record, manifest, slug, true_positives, false_positives, files_with_issues)
- Add pre-commit hooks
- Add tombstone comments
- Verify all success criteria

**Phase 5 (TODO):** Success validation
- Run full verification commands
- Delete SnapshotRegistry
- Validate 200+ redundant evaluations eliminated

**Estimated remaining: ~3-5 days** (Phase 3 + 4 + 5)

## Open Questions

1. **critic_scopes.yaml loading:** Should this move to DB or stay as YAML? (Lean toward YAML for now - it's metadata about training strategy, not runtime data)

2. **HydratedSnapshot type:** Should it contain ORM Snapshot reference or just paths? (Lean toward ORM reference for easy access to relationships)

3. **Occurrence types:** Keep in models.true_positive for grader/critic? Or move to db/models.py? (Lean toward keeping in models - they're used outside sync path)

4. **Performance:** Will ORM relationships cause N+1 queries? (Use joinedload/selectinload as needed)

5. **TrainingExample Pydantic vs dataclass:** If using ORM models, should TrainingExample be a dataclass instead? (Lean toward dataclass - Pydantic with arbitrary_types_allowed feels odd)

## Notes

- This refactoring is HIGH IMPACT (affects 50+ call sites)
- Benefits are SIGNIFICANT (eliminates 200+ redundant jsonnet evaluations in GEPA)
- Risk is MODERATE (comprehensive test suite should catch regressions)
- Execution requires DISCIPLINE (follow phase order strictly, no shortcuts)
