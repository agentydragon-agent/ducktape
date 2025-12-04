# Specimen-to-Snapshot Migration Plan

## Overview

Atomic migration of the specimen/issue structure with **NO backward compatibility**. Single large PR.

### Major Changes

1. **Snapshot/Issue Separation**
   - Consolidate all snapshot definitions into single `specimens/snapshots.yaml`
   - Issues move from `specimens/{slug}/issues/*.libsonnet` to `specimens/{slug}/*.libsonnet` (no `issues/` subdirectory)
   - Issues reference snapshots by slug (e.g., `ducktape/2025-11-26-00`)
   - Delete individual `manifest.yaml` files

2. **Jsonnet Helper Redesign**
   - Replace 3 helpers → 4 helpers: `issue()`, `issueMulti()`, `falsePositive()`, `falsePositiveMulti()`
   - Add `snapshot` parameter (first argument)
   - Add `expect_caught_from` field for TPs (minimal file sets to detect issues)
   - Add `relevant_files` field for FPs (ANY matching)
   - Require `note` for multi-occurrence issues
   - Auto-inference for single-file cases
   - **Remove `should_flag` field** - TP/FP split now at helper/type level

3. **Database Integration**
   - New `snapshots` table (replaces `specimens`)
   - New `issues` table (true positives)
   - New `false_positives` table (known false positives)
   - Single sync command: `adgn-properties2 db sync`
   - Drop and recreate via CLI: `adgn-properties2 db recreate`
   - **No `should_flag` column** - TP/FP split at table level
   - **No `labeled_files` column** - computed from issues/occurrences

4. **CLI Command Renames**
   - `specimen-exec` → `snapshot exec` (subcommand, not hyphenated)
   - `specimen-dump` → `snapshot dump` (subcommand, not hyphenated)
   - `capture-ducktape-specimen` → `snapshot capture-ducktape` (subcommand)
   - `specimen-discover` → `snapshot-discover` (hyphenated)
   - `specimen-grade` → `snapshot-grade` (hyphenated)
   - `--specimen` flag → `--snapshot` flag

5. **Terminology Refactoring**
   - `specimen_slug` → `snapshot_slug` (variables, columns, parameters)
   - Database columns: `specimen` → `snapshot_slug`
   - Help text updated throughout
   - Documentation updated

### Migration Scope

- **~405 issue files** across all specimens
- **Estimated manual review**: 50-80 files (multi-file `expect_caught_from`, multi-occurrence notes)
- **Estimated effort**: 7 days

## Execution Strategy

- Single large PR with all changes
- Delete old manifest.yaml files after migration
- All ~405 issue files migrated atomically
- Update database schema for snapshots/issues
- Comprehensive terminology refactoring (CLI + code + docs)

---

## Background and Rationale

### Problem Statement

Current specimens are **monolithic**: one specimen slug = one training/eval example. Analysis reveals:

- Specimens review multiple independent subsystems (e.g., `2025-11-26-00`: 22 git-commit-ai issues, 19 agent-server issues, 11 mcp issues)
- Issues cluster around specific files (e.g., 17 issues all touch `git_commit_ai/cli.py`)
- Training/eval is slow because we process entire specimens even when testing specific capabilities
- Cannot reuse source code snapshots across different issue sets

**Goals**:
1. Decouple source code snapshots from issue definitions (enable reuse)
2. Enable smaller, focused training examples for faster iteration
3. Explicit catchability semantics per occurrence

### Data-Driven Analysis

Across all 355 issues in existing specimens:

| Files Touched | Count | Percentage | Cumulative |
|--------------|-------|------------|------------|
| 1 file | 269 | **75.8%** | 75.8% |
| 2 files | 48 | 13.5% | 89.3% |
| 3 files | 15 | 4.2% | 93.5% |
| 4 files | 10 | 2.8% | 96.3% |
| 5+ files | 13 | 3.7% | 100.0% |

**Key insight**: **Three-quarters of issues are single-file** - perfect candidates for auto-inference. Multi-file concerns (24.2%) need explicit `expect_caught_from` specification.

### Issue Clustering by Specimen

| Specimen | Issues | Unique File Sets | Ratio | Interpretation |
|----------|--------|------------------|-------|----------------|
| `misc/2025-08-29-pyright_watch_report` | 19 | 1 | 19.0 | Single-file deep dive |
| `ducktape/2025-09-03-00` | 66 | 14 | 4.7 | Concentrated (33 on cli.py) |
| `ducktape/2025-11-26-00` | 60 | 27 | 2.2 | Mixed (17 on cli.py, rest scattered) |
| `ducktape/2025-11-22-00` | 58 | 43 | 1.3 | Dispersed sweep review |

**Implications**:
- High ratio (>4): Coherent file reviews, naturally cluster
- Low ratio (<2): Already close to independent issues
- Mixed (2-4): Have clusters plus scattered issues
- **Training examples**: Can split by file sets for granular eval (187 unique file sets total)

### Design Decision: Occurrence-Level `expect_caught_from`

**Why at occurrence level, not issue level**:
- Each occurrence is independent (reviewing file1 catches occurrence1, not occurrence2)
- Natural for duplication (each duplicate is its own occurrence with independent detection scope)
- Clear evaluation: "Did we catch this specific instance?"
- Handles multi-file requirements (some occurrences need multiple files, others don't)

**Semantics** (AND/OR logic):
- Outer set = **alternatives** (OR) - any one of these is sufficient
- Inner set = **required together** (AND) - all files must be reviewed
- Examples:
  - `{{frozenset({'a.py'})}}` - must review a.py
  - `{{frozenset({'a.py'}), frozenset({'b.py'})}}` - can catch from EITHER a.py OR b.py (duplication)
  - `{{frozenset({'a.py', 'b.py'})}}` - must review BOTH a.py AND b.py together
  - `{{frozenset({'a.py'}), frozenset({'b.py', 'c.py'})}}` - catch from a.py alone OR from b.py+c.py together

---

## Runtime Interface Changes

### Current State (Before Migration)

**Filesystem is runtime source** (grader.py:692-715):
- Grader loads specimen from filesystem at runtime
- Evaluates `issues/*.libsonnet` every run
- `hydrated.record.canonical_issues` comes from Jsonnet evaluation
- Slow: Jsonnet eval on every grader run

### After Migration (DB as Runtime Source)

**Database is runtime source, filesystem is build-time source**:
- Grader loads snapshot + issues + FPs from DB
- No Jsonnet evaluation at runtime
- Hydration still needed (Docker requires actual code files)
- Fast: Just SQL queries

### Build-Time vs Runtime Split

**Build-time** (once per change):
- Edit Jsonnet files: `vim issues/dead-code.libsonnet`
- Sync to DB: `adgn-properties2 db sync` (evaluates Jsonnet → populates DB)
- Verify: `SELECT COUNT(*) FROM issues WHERE snapshot_slug = '...'`

**Runtime** (every critic/grader run):
- Load from DB: `SELECT * FROM issues WHERE snapshot_slug = '...'`
- Hydrate code: Extract/mount for Docker (if needed)
- No Jsonnet evaluation

### Interface Changes Summary

| Component | Before (Filesystem) | After (Database) |
|-----------|---------------------|------------------|
| **Snapshots** | `specimens/{slug}/manifest.yaml` | `specimens/snapshots.yaml` → `snapshots` table |
| **Issues** | `specimens/{slug}/issues/*.libsonnet` (runtime eval) | `specimens/{slug}/*.libsonnet` → `issues` table (pre-loaded) |
| **False Positives** | `specimens/{slug}/false_positives/*.libsonnet` (runtime eval) | `specimens/{slug}/*.libsonnet` → `false_positives` table (pre-loaded) |
| **Critic input** | `specimen_slug` parameter | `snapshot_slug` parameter |
| **Grader input** | Loads from filesystem on every run | Loads from DB on every run |
| **Hydration** | Driven by manifest.yaml | Driven by `Snapshot` object from DB |
| **CLI commands** | `specimen-exec`, `specimen-grade` | `snapshot exec`, `snapshot dump`, `snapshot-discover`, `snapshot-grade` |

### SpecimenRecord Evolution

**Current**: `SpecimenRecord` loads everything from filesystem
- `manifest`, `issues`, `false_positives` all from Jsonnet at runtime
- `canonical_issues` property converts from filesystem data

**After Migration**: Renamed to `SnapshotHydrator`, becomes hydration-only
- Only extracts code to `content_root`
- NO `issues`/`false_positives` properties (loaded from DB separately)
- Class renamed from `SpecimenRecord` to `SnapshotHydrator` for clarity

### Why This Matters

1. **Performance**: No Jsonnet evaluation on every run
2. **Consistency**: All tools see same issues from DB
3. **Queryability**: Can query issues across snapshots via SQL
4. **Separation**: Code (snapshots) and labels (issues) are independent

---

## File Scope and Issue Filtering

### How File Scope is Tracked

**Key insight**: `CriticRun.files` stores the reviewed file scope (list of paths)
- NOT stored in `Critique` (critic might review files but find nothing)
- Needed for grading: filter expected issues based on what was reviewed
- Stored at critic runtime, used by grader to compute expected set

### Current State (No Filtering)

**Problem** (grader.py:614-615):
- Loads ALL canonical issues + FPs from filesystem
- Passes everything to LLM
- LLM must manually determine relevance (inefficient, error-prone)

### After Migration (Proper Filtering)

**Three-step process**:
1. Load file scope from `CriticRun.files` (join via `critique_id`)
2. Load all issues/FPs from DB for snapshot
3. Filter using `expect_caught_from` (TPs) and `relevant_files` (FPs)
4. Pass only expected set to grader LLM

### Filtering Logic Implementation

**For True Positives** (AND/OR logic):
- Check `expect_caught_from: set[frozenset[Path]]` for each occurrence
- Format: `{{frozenset({'a.py','b.py'}), frozenset({'c.py'})}}` means "(a AND b) OR c"
- Semantics: Minimal file sets such that a good critic is expected to find the issue if given any superset
- Include occurrence if ANY alternative file set is subset of reviewed files
- Return issue with only expected occurrences

**For False Positives** (ANY logic):
- Check `relevant_files: set[Path]` for each occurrence
- Include occurrence if critic reviewed ANY of the relevant files
- Liberal matching: show FP if ANY overlap
- Return FP with only expected occurrences

### Example Walkthrough

**Scenario**:
- TP "type-confusion-enums" has 2 occurrences:
  - Occ 1: Needs `{status.py, persist.py}` (both required)
  - Occ 2: Needs `{sqlite.py}` (single file)
- FP "intentional-duplication": Show if `{button.py OR link.py}` reviewed
- Critic reviewed: `{sqlite.py, button.py, other.py}`

**Filtering results**:
- TP Occ 1: `{status.py, persist.py} ⊆ reviewed`? NO → Skip
- TP Occ 2: `{sqlite.py} ⊆ reviewed`? YES → Include
- FP Occ 1: `button.py ∈ reviewed`? YES → Include

**Expected set**: TP with just occurrence 2, FP with occurrence 1

### Database Schema Requirements

**CriticRun maintains file scope**:
- Column: `files: Mapped[list[str]]` (JSONB, required)
- Renamed: `specimen` → `snapshot_slug`
- Used by grader to filter expected issues

**Grader query pattern**:
```sql
SELECT c.*, cr.files FROM critiques c
JOIN critic_runs cr ON cr.critique_id = c.id
WHERE c.id = '...';

---

## Phase 1: Core Infrastructure

### 1.1 Update Pydantic Models

**File**: `src/adgn/props/models/snapshot.py` (rename from specimen.py)
- Keep existing `GitSource`, `GitHubSource`, `LocalSource` types
- Keep existing `BundleFilter` type (no changes needed):
  ```python
  class BundleFilter(BaseModel):
      source_commit: str  # Required: Full commit SHA in original source repo
      include: list[str] | None = None  # Optional: gitignore-style include patterns
      exclude: list[str] | None = None  # Optional: gitignore-style exclude patterns
  ```
- Add `SnapshotSlug` NewType:
  ```python
  SnapshotSlug = NewType('SnapshotSlug', str)  # Format: "{repo}/{version}" e.g. "ducktape/2025-11-26-00"
  ```
- Add `Snapshot` model with slug (SnapshotSlug type), source, split, bundle (optional)
- Add computed properties for slug components:
  ```python
  class Snapshot(BaseModel):
      slug: SnapshotSlug
      # ...

      @property
      def repo(self) -> str:
          """Extract repo from slug (e.g., 'ducktape/2025-11-26-00' → 'ducktape')"""
          return self.slug.split('/', 1)[0]

      @property
      def version(self) -> str:
          """Extract version from slug (e.g., 'ducktape/2025-11-26-00' → '2025-11-26-00')"""
          return self.slug.split('/', 1)[1]
  ```
- Issues reference snapshots by slug (SnapshotSlug type)

**File**: `src/adgn/props/models/issue.py` (update existing)
- Split into separate TP/FP models:
  - `IssueOccurrence` with `expect_caught_from: set[frozenset[Path]]` (AND/OR logic, inner frozensets for hashability)
  - `FalsePositiveOccurrence` with `relevant_files: set[Path]` (ANY logic)
  - `Issue` model (TP) with validators
  - `FalsePositive` model (FP) with validators
- **Remove `should_flag` field** (TP/FP split at type level)
- **Use sets/frozensets for unordered collections**
- **Serialization**: Use Pydantic `@field_serializer` to convert sets→lists for JSON, existing pattern in codebase (see `issue.py:60-63`)
- **Path conversion**: Pydantic coerces strings→Path automatically, use `PlainSerializer` for JSON output (existing pattern in `paths.py:92`)
- **Jsonnet ↔ Python type conversion** (transparent via Pydantic):
  - Authors write in Jsonnet: `expect_caught_from: [['a.py', 'b.py'], ['c.py']]` (list of lists)
  - Pydantic automatically deserializes: `list[list[str]]` → `set[frozenset[Path]]` on model validation
  - Serialization back to JSON: `@field_serializer` converts `set[frozenset[Path]]` → `list[list[str]]` for storage
  - **No manual conversion needed** - Pydantic handles the list→set→frozenset coercion
- Validators: non-empty fields, multi-occurrence notes required

### 1.2 Class Architecture and Responsibilities

**Clean separation at "we now have Pydantic data" boundary:**

#### 1. Hydrator (Context Manager)
**File**: `src/adgn/props/hydration.py` (rename from `specimens/hydrated.py`)
```python
class SnapshotHydrator:
    """Hydrates snapshot code from bundle/source into filesystem.

    Responsibility: Snapshot spec (Pydantic) → hydrated directory
    Does NOT parse Jsonnet or YAML - just takes Pydantic and hydrates.
    """
    def __init__(self, snapshot: Snapshot): ...
    def __enter__(self) -> Path:  # Returns hydrated directory path
    def __exit__(self, ...): ...
```

#### 2. File Loader (Filesystem → Pydantic)
**File**: `src/adgn/props/loaders/filesystem.py` (new)
```python
class FilesystemLoader:
    """Loads snapshot metadata and issues from filesystem.

    Responsibility: Parse YAML/Jsonnet → Pydantic objects
    """
    def load_snapshots() -> dict[SnapshotSlug, Snapshot]:
        """Load specimens/snapshots.yaml → Snapshot objects"""

    def load_issues_for_snapshot(slug: SnapshotSlug) -> tuple[list[Issue], list[FalsePositive]]:
        """Evaluate specimens/{slug}/*.libsonnet → Issue/FP objects
        - Determines TP vs FP by helper used (issue() vs falsePositive())
        - Adds issue_id/fp_id from filename stem
        - Adds snapshot_slug from Jsonnet 'snapshot' field
        """
```

#### 3. Database Queries (SQLAlchemy ORM)
**File**: `src/adgn/props/db/models.py` (update existing)
```python
class Snapshot(Base):
    """SQLAlchemy ORM model with query methods"""
    @classmethod
    def get(cls, slug: SnapshotSlug) -> Snapshot | None: ...
    @classmethod
    def get_by_split(cls, split: Split) -> list[Snapshot]: ...

class Issue(Base):
    @classmethod
    def get(cls, snapshot_slug: SnapshotSlug, issue_id: str) -> Issue | None: ...
    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[Issue]: ...
```

#### 4. Sync Orchestrator (Files → DB)
**File**: `src/adgn/props/db/sync.py` (update existing)
```python
def sync_snapshots_to_db() -> SyncStats:
    """Load from filesystem (using FilesystemLoader) → upsert to DB"""
    snapshots = FilesystemLoader.load_snapshots()
    # Upsert to DB via SQLAlchemy
    return SyncStats(...)

def sync_issues_to_db() -> SyncStats:
    """Load all issues from filesystem → upsert to DB"""
    for slug in snapshots:
        issues, fps = FilesystemLoader.load_issues_for_snapshot(slug)
        # Upsert to DB via SQLAlchemy
    return SyncStats(...)
```

**Separation of Concerns**:
- Hydrator: Knows about bundles/git, doesn't know about Jsonnet/DB
- FileLoader: Knows about YAML/Jsonnet syntax, doesn't know about DB
- ORM Models: Know about DB schema, expose query interface
- Sync: Orchestrates FileLoader → DB upsert, reports stats

### 1.3 Training/Evaluation Example Structure

**File**: `src/adgn/props/models/training_example.py` (new)

**Purpose**: Structured format for training/evaluation examples consumed by GEPA and other optimization systems.

**Model**:
```python
class TrainingExample(BaseModel):
    snapshot_slug: str
    file_scope: set[Path]  # Files being reviewed in this example
    true_positives: list[Issue]  # TPs expected for this file scope (filtered)
    false_positives: list[FalsePositive]  # FPs expected for this file scope (filtered)
```

**API** (add to appropriate module, e.g., `src/adgn/props/examples.py`):
- `get_examples_for_split(split: Literal["train", "valid", "test"]) -> list[TrainingExample]`
  - Load all snapshots with matching split
  - For each snapshot, generate examples (see below)
  - Return flattened list of all examples

- `get_examples_for_snapshot(snapshot_slug: str) -> list[TrainingExample]`
  - Load snapshot + all issues + FPs from DB
  - **For now**: Generate one example per snapshot:
    - `file_scope` = union of all files touched by TPs on this snapshot
    - `true_positives` = all TPs for this snapshot
    - `false_positives` = all FPs for this snapshot
  - **Future**: Could generate multiple examples per snapshot with different file scopes (e.g., by file set clustering)
  - Return list of examples (currently length 1 per snapshot)

**Split Assignment** (current approach):
- Train/test/valid splits assigned at snapshot level (existing `Snapshot.split` field)
- All examples from a snapshot inherit that snapshot's split
- **Future**: May add example-level splits or file-scope-based splitting

### 1.4 Update Database Schema

**Strategy**: Drop and recreate (no Alembic migration)
- No incremental migration needed - we're nuking the database
- Order doesn't matter: code and DB migration can happen in any order since we're recreating from scratch

**New tables**:
- `snapshots`: slug (PK), split, source (JSONB), bundle (JSONB)
  - **NO `labeled_files` column** - removed (was derived data, can compute from issues/occurrences when needed)
  - Hydration always hydrates the whole snapshot from bundle (doesn't use labeled_files)
- `issues`: snapshot_slug + issue_id (composite PK), rationale, occurrences (JSONB)
  - NO `should_flag` column (TP/FP split at table level)
  - **NO separate UUID primary key** - composite key (snapshot_slug, issue_id) is sufficient
- `false_positives`: snapshot_slug + fp_id (composite PK), rationale, occurrences (JSONB)

**Relationships**:
- Cascade deletes from snapshot to issues/FPs
- **Prevent snapshot deletion** if evaluation runs exist (referential integrity protection):
  - `critic_runs.snapshot_slug` REFERENCES `snapshots.slug` ON DELETE RESTRICT
  - `critiques.snapshot_slug` REFERENCES `snapshots.slug` ON DELETE RESTRICT
  - `grader_runs.snapshot_slug` REFERENCES `snapshots.slug` ON DELETE RESTRICT

**Primary Keys**:
- `issues`: Composite PK (snapshot_slug, issue_id) - no separate UUID
- `false_positives`: Composite PK (snapshot_slug, fp_id) - no separate UUID

**Column updates**: Rename `specimen` → `snapshot_slug` in critic_runs, grader_runs, critiques

**Issue ID derivation**:
- Derived from filename stem: `dead-code-cli.libsonnet` → `issue_id = "dead-code-cli"`
- NOT specified in Jsonnet (loader adds it)
- Composite primary key ensures uniqueness per snapshot

**Workflow**:
```bash
adgn-properties2 db recreate  # Drops schema + recreates + syncs from filesystem (includes sync)
```

---

## Phase 2: Jsonnet Helpers

### 2.1 Update `lib.libsonnet`

**File**: `src/adgn/props/specimens/lib.libsonnet`

Replace entire file with 4 new helpers (no backward compat):

**True Positive Helpers**:
- `issue(snapshot, rationale, filesToRanges, expect_caught_from?)`:
  - Single occurrence
  - **Auto-inference**: If `len(filesToRanges.keys()) == 1` AND `expect_caught_from` not provided:
    - Infer `expect_caught_from = [[that_single_file]]`
  - **Error**: If `len(filesToRanges.keys()) > 1` AND `expect_caught_from` not provided:
    - Raise descriptive error: "Multi-file issue requires explicit expect_caught_from. Specify minimal file sets required to detect this issue (AND/OR semantics)."
- `issueMulti(snapshot, rationale, occurrences)`:
  - Multiple occurrences, requires `note` on all
  - **CRITICAL**: If the Jsonnet file touches >1 file in TOTAL (across all occurrences), EVERY occurrence must have explicit `expect_caught_from`
    - Even if a particular occurrence only touches 1 file
    - Forces author to consider catchability semantics for all occurrences
    - Error if any occurrence lacks `expect_caught_from` when total files > 1

**False Positive Helpers**:
- `falsePositive(snapshot, rationale, filesToRanges)`:
  - Single occurrence, auto-infers `relevant_files`
- `falsePositiveMulti(snapshot, rationale, occurrences)`:
  - Multiple occurrences, requires `note` on all

**Removed**: `issueOneOccurrence`, `issueWithOccurrences`, `issueOccurrencesFromLines`
**Key change**: NO `should_flag` parameter (TP/FP split at helper level)

**Jsonnet Return Format**:
- Helpers return Jsonnet objects: `{snapshot: '...', rationale: '...', occurrences: [...]}`
- **Loader adds metadata**:
  - `id` = filename stem (e.g., `dead-code-cli.libsonnet` → `id: "dead-code-cli"`)
  - `snapshot_slug` = extracted from `snapshot` field (e.g., `ducktape/2025-11-26-00`)
- Primary key in DB: `(snapshot_slug, issue_id)`
- Loader workflow: evaluates Jsonnet → JSON → adds `id`/`snapshot_slug` → validates via Pydantic

---

## Appendix A: Issue Definition Examples

This appendix shows concrete examples of the new issue definition format after migration.

### A.1 Directory Structure

**Before** (current):
```
specimens/
  ducktape/
    2025-11-26-00/
      manifest.yaml
      issues/
        dead-code.libsonnet
        type-confusion.libsonnet
      false_positives/
        intentional-duplication.libsonnet
```

**After** (new):
```
specimens/
  snapshots.yaml                  # All snapshots in one file
  ducktape/
    2025-11-26-00/
      dead-code-cli.libsonnet     # Issues directly in slug dir (no issues/ subdirectory)
      type-confusion-enums.libsonnet
      intentional-duplication-styles.libsonnet  # FPs mixed with TPs
    2025-11-22-00/
      issue1.libsonnet
      issue2.libsonnet
```

**Note**: True positives and false positives are in the same directory. The loader determines type by evaluating the Jsonnet helper used (`issue()` vs `falsePositive()`), not by directory structure.

### A.2 Snapshots Registry

**File**: `specimens/snapshots.yaml`

```yaml
# All snapshots in one YAML file, keyed by slug
ducktape/2025-11-26-00:
  source:
    vcs: git
    url: "https://gitlab.com/agentydragon/ducktape.git"
    commit: "3561e7e59d91f487dbaaa4bfa99a8dd3d97b07ef"
  split: train
  bundle:
    source_commit: "3561e7e59d91f487dbaaa4bfa99a8dd3d97b07ef"  # Required when bundle present
    include: ["adgn/"]  # Gitignore-style patterns
    exclude: null  # Optional

crush/2025-08-30-internal_db:
  source:
    vcs: git
    url: "https://github.com/user/crush.git"
    commit: "f1e2d3c4b5a6978685949392817263540918273"
  split: valid
  bundle: null  # No bundle, use git directly
```

**Bundle Schema Notes**:
- `bundle` field is optional (null = use git directly)
- When `bundle` is present:
  - `source_commit` is **required** (full commit SHA)
  - `include` is optional (gitignore-style patterns, e.g., `["adgn/", "tests/"]`)
  - `exclude` is optional (gitignore-style patterns)
- Gitignore-style patterns: trailing slash = directory (e.g., `"web/"` excludes web directory)

### A.3 True Positive Examples

#### Example 1: Simple Single-File Issue (75% of cases)

**File**: `specimens/ducktape/2025-11-26-00/dead-code-cli.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Function `_legacy_format_output()` in cli.py is never called.
    Remove it to reduce maintenance burden.
  |||,
  filesToRanges={
    'src/cli.py': [[145, 167]],
  },
  // expect_caught_from auto-inferred: {{'src/cli.py'}} (single file)
)
```

**Metadata** (added by loader):
- `id = "dead-code-cli"` (derived from filename stem: `dead-code-cli.libsonnet` → `dead-code-cli`)
- `snapshot_slug = "ducktape/2025-11-26-00"` (extracted from `snapshot` field in Jsonnet)

#### Example 2: Multi-File Duplication (Catchable from Either)

**File**: `specimens/ducktape/2025-11-26-00/duplicate-enum-definitions.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    PolicyStatus enum defined identically in both files.
    Consolidate to single definition.
  |||,
  filesToRanges={
    'src/approval_policy/proposal_status.py': [[6, 10]],
    'src/approval_policy/persist/__init__.py': [[54, 58]],
  },
  expect_caught_from=[
    ['src/approval_policy/proposal_status.py'],      // Can catch from either
    ['src/approval_policy/persist/__init__.py'],
  ],
)
```

**Result**: `expect_caught_from = {{frozenset({'src/.../proposal_status.py'}), frozenset({'src/.../persist/__init__.py'})}}`

#### Example 3: Multi-File Requirement (Need Both)

**File**: `specimens/ducktape/2025-11-26-00/interface-implementation-mismatch.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Interface declares `list_prompts()` as required but implementation omits it.
    Need both files to see the inconsistency.
  |||,
  filesToRanges={
    'src/mcp/base_server.py': [[45, 47]],
    'src/mcp/runtime_server.py': [[100, 250]],
  },
  expect_caught_from=[
    ['src/mcp/base_server.py', 'src/mcp/runtime_server.py'],  // Need BOTH
  ],
)
```

**Result**: `expect_caught_from = {{frozenset({'src/mcp/base_server.py', 'src/mcp/runtime_server.py'})}}`

#### Example 4: Multiple Independent Occurrences

**File**: `specimens/ducktape/2025-11-26-00/imperative-list-building.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.issueMulti(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Imperative loop-and-append pattern instead of list comprehension.
  |||,
  occurrences=[
    {
      files: {'src/agent/agents.py': [[50, 59]]},
      note= |||
        In _convert_pending_approvals(): Replace with list comprehension.
      |||,
      expect_caught_from: [['src/agent/agents.py']],  // Explicit required (>1 file total)
    },
    {
      files: {'src/mcp_bridge/approvals_bridge.py': [[64, 108]]},
      note= |||
        In list_approvals(): two consecutive loops.
      |||,
      expect_caught_from: [['src/mcp_bridge/approvals_bridge.py']],  // Explicit required
    },
    {
      files: {'src/agent/runtime.py': [[267, 274]]},
      note= |||
        In get_policy(): builds list imperatively.
      |||,
      expect_caught_from: [['src/agent/runtime.py']],  // Explicit required
    },
  ],
)
```

#### Example 5: Multi-File Issue with Mixed Alternatives

**File**: `specimens/ducktape/2025-11-26-00/type-confusion-enums.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.issueMulti(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Duplicate enums cause type confusion. Consolidate to single enum.
  |||,
  occurrences=[
    {
      files: {
        'src/approval_policy/proposal_status.py': [[6, 10]],
        'src/approval_policy/persist/__init__.py': [[54, 58]],
      },
      note= |||
        Both enum definitions. Need both to see duplication.
      |||,
      expect_caught_from: [
        ['src/approval_policy/proposal_status.py', 'src/approval_policy/persist/__init__.py'],
      ],
    },
    {
      files: {'src/approval_policy/sqlite.py': [[217, 293]]},
      note= |||
        Type confusion visible in query_proposals().
      |||,
      expect_caught_from: [['src/approval_policy/sqlite.py']],  // Explicit required (>1 file total)
    },
  ],
)
```

### A.4 False Positive Examples

#### Example 6: Intentional Pattern (Not a Bug)

**File**: `specimens/ducktape/2025-09-03-00/intentional-duplication-styles.libsonnet`

```jsonnet
local I = import '../lib.libsonnet';

I.falsePositive(
  snapshot='ducktape/2025-09-03-00',
  rationale= |||
    Button styles duplicated across components is intentional for visual consistency.
    Not a bug.
  |||,
  filesToRanges={
    'src/components/Button.svelte': [[45, 60]],
    'src/components/Link.svelte': [[32, 47]],
  },
  // relevant_files auto-inferred: {'src/components/Button.svelte', 'src/components/Link.svelte'}
)
```

**Semantics**: Show this FP **to grader** if critic reviewed ANY of these files (liberal matching for FP detection).

### A.5 Python Data Model

```python
from pydantic import BaseModel, Field, model_validator, field_serializer
from pathlib import Path

class Snapshot(BaseModel):
    slug: str
    split: Literal["train", "valid", "test"]
    source: GitSource | GitHubSource | LocalSource
    bundle: BundleConfig | None = None

class LineRange(BaseModel):
    start_line: int
    end_line: int | None = None

class IssueOccurrence(BaseModel):
    files: dict[Path, list[LineRange] | None]
    note: str | None = None
    expect_caught_from: set[frozenset[Path]]  # AND/OR logic, inner frozensets for hashability

    @field_serializer('expect_caught_from')
    def serialize_expect_caught_from(self, value):
        # Convert to JSON: set[frozenset[Path]] → list[list[str]]
        return [[str(p) for p in fs] for fs in value]

    @model_validator(mode='after')
    def validate_non_empty(self):
        if not self.expect_caught_from:
            raise ValueError("expect_caught_from must be non-empty")
        return self

class Issue(BaseModel):
    issue_id: str  # Derived from filename by loader (e.g., "dead-code-cli")
    snapshot_slug: str  # Extracted from snapshot field in Jsonnet
    rationale: str
    occurrences: list[IssueOccurrence]
    # NO should_flag field (TP/FP split at model level)
    # Primary key in DB: (snapshot_slug, issue_id)

    @model_validator(mode='after')
    def validate_multi_occurrence_notes(self):
        if len(self.occurrences) > 1:
            for occ in self.occurrences:
                if occ.note is None:
                    raise ValueError("note required for multi-occurrence issues")
        return self

class FalsePositiveOccurrence(BaseModel):
    files: dict[Path, list[LineRange] | None]
    note: str | None = None
    relevant_files: set[Path]  # ANY logic

    @field_serializer('relevant_files')
    def serialize_relevant_files(self, value):
        return [str(p) for p in value]

class FalsePositive(BaseModel):
    fp_id: str  # Derived from filename by loader
    snapshot_slug: str  # Extracted from snapshot field in Jsonnet
    rationale: str
    occurrences: list[FalsePositiveOccurrence]
    # Primary key in DB: (snapshot_slug, fp_id)

# Filtering logic
def should_catch_occurrence(occ: IssueOccurrence, reviewed_files: set[Path]) -> bool:
    """Check if occurrence should be caught given reviewed files."""
    return any(
        alternative_set.issubset(reviewed_files)
        for alternative_set in occ.expect_caught_from
    )

def should_show_fp_occurrence(occ: FalsePositiveOccurrence, reviewed_files: set[Path]) -> bool:
    """Check if FP occurrence is relevant given reviewed files."""
    return bool(occ.relevant_files & reviewed_files)  # ANY overlap
```

### A.6 Migration Counts

**Total issues**: ~405
- **Auto-migrated**: ~372 using `issueOneOccurrence` → `issue()` (single-file, auto-infer)
- **Manual migration**: ~33 files
  - 26 using `issueWithOccurrences` → `issueMulti()` (add notes + `expect_caught_from`)
  - 7 using `issueOccurrencesFromLines` → `issueMulti()` (expand to explicit occurrences)

**False positives**: Separate count (files in `false_positives/` directories)

---

## Phase 3: Migration Scripts

**Rollback Strategy**: Scripts are NOT idempotent. If migration fails partway through, use `git reset --hard` to restore original state and restart from beginning. No need for incremental checkpointing.

### 3.1 Generate `snapshots.yaml`

**Script**: `scripts/migrate_to_snapshots.py`
- Walk all `manifest.yaml` files
- Parse slug from directory structure: `{repo}/{date-seq}`
- Extract source, bundle, split from each manifest
- Write single `snapshots.yaml` with all entries

### 3.2 Migrate Issue Files (Auto Only)

**Script**: `scripts/migrate_issue_helpers.py`

**TP/FP Identification** (after migration):
- **Current**: TPs in `specimens/{slug}/issues/`, FPs in `specimens/{slug}/false_positives/`
- **After migration**: TPs and FPs mixed in `specimens/{slug}/*.libsonnet`
- Loader determines type by evaluating the Jsonnet helper used:
  - `issue()` or `issueMulti()` → True Positive (loads into `issues` table)
  - `falsePositive()` or `falsePositiveMulti()` → False Positive (loads into `false_positives` table)
- Current code uses `should_flag` internally, but this is removed in new schema

**Auto-migration**:
- Move files from `specimens/{slug}/issues/*.libsonnet` → `specimens/{slug}/*.libsonnet`
- Move files from `specimens/{slug}/false_positives/*.libsonnet` → `specimens/{slug}/*.libsonnet`
- `issueOneOccurrence` in old `issues/` dir → `issue(snapshot='...')` (TP helper)
- `issueOneOccurrence` in old `false_positives/` dir → `falsePositive(snapshot='...')` (FP helper)
- Add snapshot slug as first parameter
- Update import paths: `../../lib.libsonnet` → `../lib.libsonnet` (one fewer `..` due to flattened structure)
- Report: ~372 auto-migrated TPs, count FPs separately, ~33 manual TPs

**Manual migration** (multi-file/multi-occurrence):
- 26 `issueWithOccurrences` + 7 `issueOccurrencesFromLines`
- Need explicit `expect_caught_from` (TPs) or `relevant_files` (FPs)
- Need `note` fields for multi-occurrence

### 3.3 Sync to Database

**File**: `src/adgn/props/db/sync_snapshots.py` (update existing)

**Key changes**:
- Load snapshot Pydantic models from `snapshots.yaml`, convert to DB records (no dicts)
- NO `labeled_files` field - labeled files computed from issues/occurrences at query time
- Use SQLAlchemy upsert: `insert(...).on_conflict_do_update()`
- Load issues from Jsonnet via `SpecimenRegistry.load_issues(slug)`
- Serialize occurrences with `model_dump()` for JSONB columns
- Compute diff: existing vs new slugs/issue_ids, delete removed, upsert changed
- Return `SyncStats(total, added, updated, deleted)`

**CLI Integration** (`src/adgn/props/cli_app/cmd_db.py`):
- Update `db sync` command to call both `sync_snapshots_to_db()` and `sync_issues_to_db()`
- Sync snapshots first (issues have FK to snapshots), then all issues
- Display stats: `"✓ Snapshots: {snap_stats.summary_text}"`

### 3.4 Delete Old Manifests

**File**: `scripts/cleanup_old_manifests.py`

**Logic**:
- Recursively find all `manifest.yaml` under `specimens/`
- Skip lib/specimens directory itself
- Delete each manifest
- Report count of deleted files

---

## Phase 4: Terminology Refactoring

**No backward compatibility**: Rename everything in place, no compatibility shims.
- External systems must update to new terminology
- No deprecated aliases or legacy flags

### 4.1 CLI Commands to Rename

**File**: `src/adgn/props/cli_app/main.py`

Rename these commands:
```python
# OLD → NEW
specimen-exec → snapshot exec (subcommand, not hyphenated)
specimen-dump → snapshot dump (subcommand, not hyphenated)
capture-ducktape-specimen → snapshot capture-ducktape (subcommand)
specimen-discover → snapshot-discover (hyphenated)
specimen-grade → snapshot-grade (hyphenated)
```

**File**: `src/adgn/props/cli_app/common_options.py`

Rename arguments and options:
```python
# OLD → NEW
ARG_SPECIMEN → ARG_SNAPSHOT
OPT_SPECIMEN → OPT_SNAPSHOT
OPT_RUNBOOK_SPECIMEN → OPT_RUNBOOK_SNAPSHOT

# Update help text
"Specimen slug (under properties/specimens)" → "Snapshot slug (e.g., 'ducktape/2025-11-26-00')"
"Specimen slug" → "Snapshot slug"
```

### 4.2 Python Files to Refactor

Search and replace "specimen" → "snapshot" in appropriate contexts:

**Core modules**:
- `src/adgn/props/models/specimen.py` → `snapshot.py` (rename file)
- `src/adgn/props/specimens/registry.py` → Delete (replaced by `loaders/filesystem.py`)
- `src/adgn/props/specimens/hydrated.py` → Rename file to `hydration.py`, rename class `HydratedSpecimen` → `SnapshotHydrator`
- `src/adgn/props/loaders/filesystem.py` → New file with `FilesystemLoader` class
- `src/adgn/props/db/sync_specimens.py` → Rename to `sync.py` (update functions)
- `src/adgn/props/db/models.py` → Specimen table → Snapshot table
- `src/adgn/props/cli_app/main.py` → Update all CLI command names (see 4.1)
- `src/adgn/props/cli_app/common_options.py` → Update arguments/options (see 4.1)
- `src/adgn/props/grader.py` → Update specimen references
- `src/adgn/props/critic.py` → Update specimen references
- `src/adgn/props/eval_harness.py` → Update specimen references

**Guidelines**:
- `specimen_slug` → `snapshot_slug` (in variables, columns, parameters, **use SnapshotSlug NewType**)
- `specimen` parameter → `snapshot` parameter (in CLI commands)
- `SpecimenRegistry` → Delete (replaced by `FilesystemLoader`)
- `HydratedSpecimen` → Rename to `SnapshotHydrator` (consistency with new terminology)
- Database columns: `specimen` → `snapshot_slug`
- CLI commands: Rename as shown in 4.1
- CLI flags: `--specimen` → `--snapshot`
- CLI help text: Update all references

**Exception**: Keep "specimen" when referring to:
- The directory structure (`specimens/` directory)
- The training data collection as a whole ("specimen collection")

### 4.3 Documentation Files to Update

**Core docs**:
- `src/adgn/props/docs/authoring.md` → Update terminology
- `src/adgn/props/docs/quality-checklist.md` → Update terminology
- `src/adgn/props/docs/specimen-splitting-design.md` → Rename to `snapshot-design.md`
- `src/adgn/props/docs/issue-definition-examples.md` → Update all examples
- `src/adgn/props/README.md` → Update references
- `src/adgn/props/AGENTS.md` → Update references

**Other docs**:
- `src/adgn/props/db/README.md` → Update schema references
- `src/adgn/props/.claude/commands/*.md` → Update commands
- All `specimens/*/README.md` → Update terminology if needed

---

## Phase 5: Testing

### 5.1 Unit Tests

**File**: `tests/props/test_snapshot_models.py`

**Test coverage**:
- `test_snapshot_validation()` - Load snapshots from YAML testdata
- `test_issue_occurrence_empty_expect_caught_from()` - Validates non-empty `expect_caught_from`
- `test_fp_occurrence_empty_relevant_files()` - Validates non-empty `relevant_files`
- `test_multi_occurrence_requires_notes()` - Multi-occurrence TPs must have notes
- `test_multi_occurrence_fp_requires_notes()` - Multi-occurrence FPs must have notes

**Test Fixtures**: Existing testdata in `tests/props/testdata/` auto-migrated by Phase 3 scripts

### 5.2 Integration Tests

**File**: `tests/props/test_snapshot_loading.py`

**Test coverage**:
- `test_load_snapshots_yaml()` - Parse `snapshots.yaml`, validate Snapshot model
- `test_load_all_issues()` - Load all issues via `SpecimenRegistry`, verify `snapshot_slug` and non-empty `expect_caught_from`
- `test_query_issues_from_db()` - Query issues from DB, verify FK integrity (no orphaned issues), test deserialization
- `test_get_examples_for_split()` - Generate training examples for each split, verify structure
- `test_get_examples_for_snapshot()` - Generate examples for specific snapshot, verify TPs/FPs are filtered correctly

### 5.3 Smoke Tests

```bash
# Test renamed CLI commands
adgn-properties2 list-snapshots
adgn-properties2 snapshot-info ducktape/2025-11-26-00
adgn-properties2 snapshot dump ducktape/2025-11-26-00  # Subcommand (not hyphenated)
adgn-properties2 snapshot exec ducktape/2025-11-26-00 -- ls -la  # Subcommand (not hyphenated)
adgn-properties2 run --snapshot ducktape/2025-11-26-00 --preset max-recall-critic

# Test database commands
adgn-properties2 db recreate  # Drops + recreates + syncs
adgn-properties2 db sync  # Standalone sync

# Verify counts
psql $DB_URL -c "SELECT split, COUNT(*) FROM snapshots GROUP BY split;"
psql $DB_URL -c "SELECT snapshot_slug, COUNT(*) FROM issues GROUP BY snapshot_slug LIMIT 10;"

# Verify database integrity
psql $DB_URL -c "SELECT COUNT(*) FROM snapshots;"  # Should match snapshot count
psql $DB_URL -c "SELECT COUNT(*) FROM issues;"     # Should be ~405
psql $DB_URL -c "SELECT COUNT(*) FROM issues WHERE snapshot_slug NOT IN (SELECT slug FROM snapshots);" # Should be 0

# Test specific commands
adgn-properties2 snapshot-discover ducktape/2025-11-26-00 --preset max-recall-critic  # Hyphenated
adgn-properties2 snapshot-grade <critique-id>  # Hyphenated
```

---

## Phase 6: Documentation Updates

### 6.1 Update Authoring Guide

**File**: `src/adgn/props/docs/authoring.md`

- Replace all examples with new helper signatures
- Add `snapshot` parameter documentation
- Update `expect_caught_from` semantics
- Add multi-occurrence `note` requirements

### 6.2 Update Quality Checklist

**File**: `src/adgn/props/docs/quality-checklist.md`

- Update terminology (specimen slug → snapshot slug where appropriate)
- Add checklist items for `expect_caught_from` validation
- Add checklist items for multi-occurrence notes

### 6.3 Update README

**File**: `src/adgn/props/README.md`

- Update terminology throughout
- Update CLI examples with new flags
- Document snapshot registry structure

---

## Risk Mitigation

### High-Risk Areas

1. **Multi-file `expect_caught_from` inference**:
   - Estimated ~30-50 files need manual review
   - Script will mark these for review
   - Plan: Automated migration + manual verification pass

2. **Multi-occurrence notes**:
   - 26 files using `issueWithOccurrences` need notes added
   - Plan: Script marks for review, manual addition of notes

3. **Database migration**:
   - Schema changes affect running systems
   - Plan: Test migration on staging DB first, backup production

4. **Terminology consistency**:
   - Risk of missing references in docs/code
   - Plan: Comprehensive grep + manual review

### Rollback Plan

If migration fails:
1. Revert DB migration
2. Restore old manifest.yaml files from git
3. Revert Jsonnet helpers
4. Revert code changes

**Note**: Atomic PR means rollback is simple `git revert`.

---

## Execution Timeline

1. **Day 1**: Phase 1.1-1.2 (Pydantic models + Snapshot registry)
2. **Day 2**: Phase 1.3 (Database schema + migration) + Phase 2 (Jsonnet helpers)
3. **Day 3**: Phase 3.1-3.2 (Generate snapshots.yaml + migrate issue files)
4. **Day 4**: Phase 3.3 (DB sync scripts) + manual review of ~50-80 files
5. **Day 5**: Phase 4 (Terminology refactoring) + Phase 3.4 (cleanup manifests)
6. **Day 6**: Phase 5 (Testing) + Phase 6 (Documentation)
7. **Day 7**: DB population + verification + final review + PR

**Estimated total effort**: 7 days (including manual review time for ~50-80 files and database population)

---

## Success Criteria

### Core Migration
- ✅ All ~405 issue files migrated to new helpers (`issue()`, `issueMulti()`)
- ✅ Single `snapshots.yaml` created and validated
- ✅ All old `manifest.yaml` files deleted
- ✅ No references to old helpers (`issueOneOccurrence`, etc.) in codebase

### Database Integration
- ✅ Database schema updated with `snapshots` and `issues` tables
- ✅ All snapshots synced to database (verify counts by split)
- ✅ All ~405 issues synced to database (verify foreign keys)
- ✅ Database integrity: all issues reference existing snapshots (no orphans)
- ✅ `adgn-properties2 db sync` command works end-to-end

### CLI Refactoring
- ✅ Snapshot subcommands implemented: `snapshot exec`, `snapshot dump`, `snapshot capture-ducktape`
- ✅ Hyphenated snapshot commands work: `snapshot-discover`, `snapshot-grade`
- ✅ Database subcommands: `db recreate` (auto-syncs), `db sync` (standalone)
- ✅ All CLI flags/options renamed (`--specimen` → `--snapshot`)
- ✅ All help text updated to reference "snapshot"

### Testing & Quality
- ✅ All tests passing (unit + integration + smoke)
- ✅ Test fixtures auto-migrated from testdata
- ✅ Documentation updated throughout (code + markdown)
- ✅ Terminology consistent across code and docs

---

## Definition of Done

### Code Quality Requirements

#### Import Organization
- ✅ All Python files have imports at the top of the file
- ✅ No inline imports except for documented circular dependencies
- ✅ Each in-function import has a one-line comment explaining the cycle
- ✅ No imports inside try/except blocks or conditional statements
- ✅ All imports follow standard ordering: stdlib → third-party → local

#### Terminology Cleanup
- ✅ No "specimen" references in public-facing code:
  - CLI command names (all renamed to `snapshot-*`)
  - CLI flags/options (all `--specimen` → `--snapshot`)
  - CLI help text and descriptions
  - User-facing error messages
  - Documentation (README, authoring guides, examples)

- ✅ "Specimen" retained only where appropriate:
  - **Directory name**: `specimens/` (filesystem convention - path to directory containing snapshots.yaml and snapshot subdirectories)
  - **Training data context**: "specimen collection" (when referring to the entire corpus as a conceptual unit)
  - **Module paths**: `src/adgn/props/specimens/` directory and Python module paths (e.g., `from adgn.props.specimens import ...`)
  - **Internal variables**: May appear in implementation code where contextually appropriate (e.g., `specimens_dir = Path("specimens")`)
  - **Note**: All class names fully migrated (`SnapshotHydrator`, `FilesystemLoader`, etc.)
  - **Note**: All public-facing interfaces use "snapshot" terminology exclusively

#### Schema Separation
- ✅ Clear separation between snapshot, issue, and occurrence models:
  - `Snapshot` model with slug (SnapshotSlug NewType), source, split, bundle
  - `Issue` model (TP) with `IssueOccurrence[]`
  - `FalsePositive` model (FP) with `FalsePositiveOccurrence[]`
  - No mixing of snapshot/issue concerns

#### SnapshotSlug NewType Propagation
- ✅ `SnapshotSlug = NewType('SnapshotSlug', str)` defined in models/snapshot.py
- ✅ Used throughout codebase instead of raw `str`:
  - Pydantic models: `Snapshot.slug: SnapshotSlug`
  - Function signatures: `def get_snapshot(slug: SnapshotSlug) -> Snapshot`
  - Database queries: `Issue.get_for_snapshot(snapshot_slug: SnapshotSlug)`
- ✅ Slug components accessible via properties:
  - `Snapshot.repo` property extracts repo (e.g., "ducktape")
  - `Snapshot.version` property extracts version (e.g., "2025-11-26-00")
  - Format: `"{repo}/{version}"` (slash-separated)

- ✅ Proper field types and validation:
  - `IssueOccurrence.expect_caught_from: set[frozenset[Path]]` (AND/OR logic, inner frozensets for hashability)
  - `FalsePositiveOccurrence.relevant_files: set[Path]` (ANY matching)
  - **Use sets/frozensets for unordered collections** (not lists)
  - Pydantic serialization: sets→JSON arrays via `@field_serializer`, deserialization automatic
  - Non-empty validators on both
  - Multi-occurrence note requirements enforced
  - **Multi-file validation**: If Jsonnet file touches >1 file total (across all occurrences), EVERY occurrence must have explicit `expect_caught_from`
    - Even single-file occurrences require explicit specification when total files > 1
    - Validation error if any occurrence lacks `expect_caught_from` in multi-file issues
    - Forces authors to consider catchability semantics explicitly

- ✅ Database schema matches Pydantic models:
  - `snapshots` table with proper columns (NO `labeled_files` - computed from issues/occurrences)
  - `issues` table with JSONB occurrences (NO `should_flag`), composite PK (snapshot_slug, issue_id)
  - `false_positives` table with JSONB occurrences, composite PK (snapshot_slug, fp_id)
  - Foreign key relationships enforced
  - **NO separate UUID primary keys** - composite keys (snapshot_slug, issue_id/fp_id) are sufficient

#### Docstring Quality
- ✅ Docstrings contain only what's helpful and not obvious from signature/immediate context
- ✅ No super-verbose Javadocs that restate parameter types or trivial behavior
- ✅ Focus on "why" and non-obvious constraints, not "what" that's already clear

#### Jsonnet Migration Completeness
- ✅ `lib.libsonnet` fully migrated to 4 new helpers (no backward compat shims)
- ✅ No unused helper functions remain in `lib.libsonnet`
- ✅ All old helpers removed: `issueOneOccurrence`, `issueWithOccurrences`, `issueOccurrencesFromLines`

#### Documentation Updates
- ✅ `docs/authoring.md` updated with proper Jsonnet helper usage examples
- ✅ All Markdown documentation updated with new terminology (snapshot/issue)
- ✅ Examples in docs use new helper signatures (`issue()`, `issueMulti()`, etc.)
- ✅ CLI command examples use `--snapshot` flag (not `--specimen`)

#### CLI Commands
- ✅ `db recreate` subcommand implemented (drops schema + recreates + syncs automatically)
- ✅ `db sync` subcommand syncs snapshots + issues from filesystem (standalone)
- ✅ Snapshot subcommands work: `snapshot exec`, `snapshot dump`, `snapshot capture-ducktape`
- ✅ Hyphenated snapshot commands work: `snapshot-discover`, `snapshot-grade`

#### Training/Evaluation Examples API
- ✅ `TrainingExample` model defined with snapshot_slug, file_scope, true_positives, false_positives
- ✅ `get_examples_for_split(split)` returns examples for train/valid/test split
- ✅ `get_examples_for_snapshot(snapshot_slug)` returns examples for specific snapshot
- ✅ For now: one example per snapshot (all files, all TPs, all FPs)
- ✅ Examples inherit split from snapshot level

#### Class Architecture
- ✅ `SnapshotHydrator` class implemented (context manager, takes Snapshot → returns Path)
- ✅ `FilesystemLoader` class implemented:
  - `load_snapshots()` reads specimens/snapshots.yaml
  - `load_issues_for_snapshot()` evaluates Jsonnet, adds metadata
- ✅ SQLAlchemy ORM models have query methods (`get()`, `get_by_split()`, etc.)
- ✅ `sync_snapshots_to_db()` and `sync_issues_to_db()` orchestrate filesystem → DB
- ✅ `SpecimenRegistry` and `HydratedSpecimen` classes deleted (no backward compat)
- ✅ Clear separation: hydration, loading, querying, syncing are independent modules

#### Deleted Classes and Files
- ✅ The following classes/files are completely deleted (no backward compatibility):
  - **Classes deleted**:
    - `SpecimenRegistry` (replaced by `FilesystemLoader`)
    - `HydratedSpecimen` (replaced by `SnapshotHydrator`)
  - **Files deleted**:
    - `src/adgn/props/specimens/registry.py` → Deleted (functionality moved to `loaders/filesystem.py`)
    - All `specimens/{slug}/manifest.yaml` files → Deleted (consolidated into `specimens/snapshots.yaml`)
  - **Files renamed**:
    - `src/adgn/props/models/specimen.py` → Renamed to `snapshot.py`
    - `src/adgn/props/specimens/hydrated.py` → Renamed to `hydration.py`
    - `src/adgn/props/db/sync_specimens.py` → Renamed to `sync.py`
  - **Helpers removed from lib.libsonnet**:
    - `issueOneOccurrence()`, `issueWithOccurrences()`, `issueOccurrencesFromLines()`
  - **CLI commands removed**:
    - `specimen-exec`, `specimen-dump`, `capture-ducktape-specimen`, `specimen-discover`, `specimen-grade`
    - (Replaced by `snapshot exec`, `snapshot dump`, `snapshot capture-ducktape`, `snapshot-discover`, `snapshot-grade`)

#### Multi-File Issue Verification
- ✅ All issues that span more than one file have been verified using actual snapshot content inspection:
  - **Verification method**: Via `snapshot exec <slug> -- <inspection commands>` OR manual clone from bundle/source
  - **Verification standard**: For each multi-file issue, confirmed that ANY good code critic pointed at ANY of the minimal sets would find and point out the issue
  - **Primary site not required**: Issue's "primary site" (main location) does not need to be in minimal sets - as long as a reasonably thorough critic reviewing ANY minimal set would discover and report the issue
  - **Example**: A type confusion issue with primary definition in `types.py` can be caught from `usage.py` alone if the confusion is evident in usage
- ✅ **Pessimistic approach when unclear**:
  - When minimal sets are ambiguous or uncertain, prefer to include all files listed in occurrences
  - Better to be over-inclusive (more files in minimal sets) than risk missing detection
  - Document rationale: "Unclear if subset sufficient → included all occurrence files"
- ✅ **Migration report documents all verification decisions**:
  - How each minimal set was determined (inspection method, reasoning)
  - Why specific files were included or excluded from minimal sets
  - What inspection method was used (`snapshot exec` commands, manual clone steps, etc.)
  - Any uncertainties resolved pessimistically (with explanation)

### Multi-File Issue Manual Review

**Post-Migration Document Required**: `docs/multi_file_issues_migration_report.md`

Document must include:

#### 1. Migration Summary Statistics
```markdown
## Migration Summary

- Total issues: ~405
- Auto-migrated (single-file): ~372
- Manual review required: ~33
  - issueWithOccurrences: 26 files
  - issueOccurrencesFromLines: 7 files

### Manual Review Process
- All multi-file issues reviewed manually
- Minimal catch sets validated for each
- All occurrences verified with notes
- False positives identified and separated
```

#### 2. Per-Issue Documentation

For each manually migrated issue, document:

**Issue ID and Type:**
```markdown
### Issue: ducktape-type-confusion-enums

**Original helper:** `issueWithOccurrences`
**New helper:** `issueMulti`
**Classification:** True Positive (TP)
```

**Files Involved:**
```markdown
**Files referenced:**
- src/approval_policy/proposal_status.py (enum definition)
- src/approval_policy/persist/__init__.py (duplicate enum)
- src/approval_policy/sqlite.py (type confusion in usage)
```

**Minimal Catch Sets:**
```markdown
**expect_caught_from (minimal detection requirements):**

Occurrence 1 (enum duplication):
- Alternative 1: [proposal_status.py, persist/__init__.py]
  - Requires both files to see the duplication

Occurrence 2 (type confusion):
- Alternative 1: [sqlite.py]
  - Single file sufficient (confusion visible in usage)

**Rationale:** Enum duplication requires comparing both definitions, but
type confusion is evident from sqlite.py alone (mixing both enum types).

**Decision process:**
- Verified via: `snapshot exec ducktape/2025-11-26-00 -- cat src/approval_policy/proposal_status.py src/approval_policy/persist/__init__.py src/approval_policy/sqlite.py`
- Inspection confirmed: sqlite.py shows type confusion independently (calls with both enum types)
- Conclusion: Occurrence 2 detectable from sqlite.py alone; occurrence 1 requires both enum definitions
```

**Migration Notes:**
```markdown
**Notes added:**
- Occurrence 1: "Both enum definitions reveal identical duplicates"
- Occurrence 2: "Type confusion visible: query_proposals() mixes both enum types"

**Verification method:**
- Inspected snapshot content via `snapshot exec` to confirm minimal sets
- For occurrence 2: Verified that sqlite.py alone shows type confusion (no need for enum definitions)
- For occurrence 1: Verified that both files needed to identify duplication

**Pessimistic decisions:**
- None - minimal sets are clearly sufficient based on inspection

**Validation:** Confirmed each occurrence is independently detectable from
its specified file sets.
```

#### 3. False Positive Handling

**Separate section documenting FP classification:**

```markdown
## False Positive Classification

### Criteria for FP Classification
- Patterns that look like issues but aren't (e.g., intentional duplication)
- Cases where issue detection is too sensitive (e.g., style preferences)
- Patterns that match rules but have valid context (e.g., TODO comments in tests)

### FP Migration Process
1. Identified X issues as false positives during manual review
2. Moved to separate `FalsePositive` model with `relevant_files`
3. Updated helpers to `falsePositive()` or `falsePositiveMulti()`

### FP Examples

#### FP: intentional-style-duplication
**Files:** [components/Button.svelte, components/Link.svelte]
**Rationale:** Button styles duplicated across components is intentional
for visual consistency. Not a bug.
**relevant_files:** ['components/Button.svelte', 'components/Link.svelte']
**Detection semantics:** Show if critic reviews ANY of these files (liberal matching)
```

#### 4. Validation Results

```markdown
## Validation Results

### Automated Checks
- ✅ All issues have non-empty `expect_caught_from` or `relevant_files`
- ✅ All multi-occurrence issues have notes
- ✅ All snapshot slugs valid and reference existing snapshots
- ✅ All file paths in occurrences exist in snapshot
- ✅ All line ranges are valid (start ≤ end, within file bounds)

### Manual Verification
- ✅ Each multi-file issue reviewed for minimal catch sets (via `snapshot exec` or manual inspection)
- ✅ Each minimal set verified: confirmed ANY good critic pointed at ANY minimal set would find the issue
- ✅ Each FP classification validated
- ✅ Each occurrence note explains the specific instance
- ✅ Ambiguous cases resolved pessimistically (all occurrence files included)
- ✅ All verification methods and decisions documented in migration report

### Database Integrity
- ✅ All issues sync to database successfully
- ✅ All FPs sync to database successfully
- ✅ No orphaned issues (all reference valid snapshots)
- ✅ JSONB occurrences deserialize correctly
```

#### 5. Edge Cases and Decisions

**REQUIRED**: Document ALL non-obvious decisions with verification method and rationale.

For each decision, include:
- **Decision**: What minimal sets were chosen
- **Rationale**: Why those files are sufficient/necessary
- **Verification method**: How decision was verified (`snapshot exec` commands, manual inspection, etc.)
- **Pessimistic choices**: Cases where uncertainty led to including all occurrence files

```markdown
## Migration Edge Cases and Decisions

### Issue: dead-functions-approvals (multiple occurrences in same file)
**Decision:** Keep as `issueMulti` even though all in one file
**Rationale:** Each function is a separate logical instance of dead code,
deserves separate note explaining why it's unused.
**Verification:** Via `snapshot exec` - confirmed each function is independent
**Pessimistic:** N/A - clear single-file case

### Issue: interface-implementation-mismatch
**Decision:** Classified as TP requiring both files
**Rationale:** Need interface definition + implementation to see mismatch.
Cannot detect from either file alone.
**Verification:** Inspected both files via `snapshot exec` - confirmed interface declares method that implementation omits
**Pessimistic:** N/A - clear both-files requirement

### Issue: intentional-duplication-styles
**Decision:** Reclassified as FP
**Rationale:** Duplication is intentional design pattern, not a bug.
Changed to `falsePositive()` with liberal ANY matching.
**Verification:** Manual review of code context - confirmed duplication serves visual consistency goal
**Pessimistic:** N/A - clear FP classification

### Issue: complex-dataflow-bug (ambiguous minimal set)
**Decision:** Included all 3 files [data_source.py, transformer.py, consumer.py]
**Rationale:** UNCLEAR if subset sufficient - bug spans dataflow chain
**Verification:** Attempted to understand from subsets via `snapshot exec`, ambiguous
**Pessimistic:** YES - included all occurrence files due to uncertainty
**Note:** May be detectable from consumer.py alone, but safer to include full chain
```

### Database Migration Verification

#### Schema Creation
- ✅ `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` executed
- ✅ `Base.metadata.create_all(engine)` creates all tables
- ✅ Tables created: `snapshots`, `issues`, `false_positives`, `critic_runs`, `grader_runs`, `critiques`
- ✅ All foreign keys defined correctly
- ✅ Composite primary keys created: (snapshot_slug, issue_id) for issues, (snapshot_slug, fp_id) for FPs
- ✅ All JSONB columns defined

#### Data Sync
- ✅ `adgn-properties2 db sync` runs successfully
- ✅ All snapshots synced (verify count by split):
  ```sql
  SELECT split, COUNT(*) FROM snapshots GROUP BY split;
  -- Expected: train/valid/test counts match snapshots.yaml
  ```

- ✅ All issues synced (~405 expected):
  ```sql
  SELECT COUNT(*) FROM issues;
  -- Expected: ~405
  ```

- ✅ All FPs synced:
  ```sql
  SELECT COUNT(*) FROM false_positives;
  -- Expected: count from FP files
  ```

#### Integrity Checks
- ✅ No orphaned issues:
  ```sql
  SELECT COUNT(*) FROM issues
  WHERE snapshot_slug NOT IN (SELECT slug FROM snapshots);
  -- Expected: 0
  ```

- ✅ No orphaned FPs:
  ```sql
  SELECT COUNT(*) FROM false_positives
  WHERE snapshot_slug NOT IN (SELECT slug FROM snapshots);
  -- Expected: 0
  ```

- ✅ Issue counts per snapshot match filesystem:
  ```sql
  SELECT snapshot_slug, COUNT(*) FROM issues
  GROUP BY snapshot_slug ORDER BY snapshot_slug;
  ```

- ✅ Occurrences deserialize correctly:
  ```python
  # Test: Load issue from DB, parse occurrences
  issue = await session.get(Issue, issue_id)
  occurrences = [IssueOccurrence(**occ) for occ in issue.occurrences]
  assert all(len(occ.expect_caught_from) > 0 for occ in occurrences)
  ```

### Testing Requirements

#### Unit Tests
- ✅ All model validation tests passing:
  - `test_snapshot_validation()` - Snapshot model
  - `test_issue_occurrence_empty_expect_caught_from()` - TP validation
  - `test_fp_occurrence_empty_relevant_files()` - FP validation
  - `test_multi_occurrence_requires_notes()` - Multi-occurrence TP
  - `test_multi_occurrence_fp_requires_notes()` - Multi-occurrence FP

#### Integration Tests
- ✅ Snapshot loading tests passing:
  - `test_load_snapshots_yaml()` - Parse snapshots.yaml
  - `test_load_all_issues()` - Load all issues from Jsonnet
  - `test_query_issues_from_db()` - Database queries work

#### Smoke Tests
- ✅ All CLI commands work:
  ```bash
  adgn-properties2 list-snapshots
  adgn-properties2 snapshot-info ducktape/2025-11-26-00
  adgn-properties2 snapshot dump ducktape/2025-11-26-00  # Not hyphenated
  adgn-properties2 snapshot exec ducktape/2025-11-26-00 -- ls -la  # Not hyphenated
  adgn-properties2 run --snapshot ducktape/2025-11-26-00 --preset max-recall-critic
  adgn-properties2 db sync
  adgn-properties2 snapshot-discover ducktape/2025-11-26-00 --preset max-recall-critic  # Hyphenated
  adgn-properties2 snapshot-grade <critique-id>  # Hyphenated
  ```

#### Test Fixture Migration
- ✅ All test fixtures in `tests/props/testdata/` migrated
- ✅ Tests load YAML from testdata, many through pytest fixtures that load into DB first
- ✅ Migration scripts handle both production and test data
- ✅ No test files reference old helper names

### Documentation Completeness

#### Core Documentation
- ✅ `docs/authoring.md` updated with new helper examples
- ✅ `docs/quality-checklist.md` updated with new terminology
- ✅ `docs/issue-definition-examples.md` updated with new examples
- ✅ `README.md` updated with snapshot references
- ✅ `AGENTS.md` updated with snapshot commands

#### Multi-File Migration Report
- ✅ `docs/multi_file_issues_migration_report.md` created
- ✅ All manually migrated issues documented
- ✅ All FP classifications documented
- ✅ All edge cases documented
- ✅ Validation results included

#### Example Files
- ✅ All example Jsonnet in docs use new helpers
- ✅ No examples reference old helpers
- ✅ All CLI examples use `--snapshot` flag
- ✅ All code snippets reference snapshots, not specimens

### Migration Artifacts Cleanup

#### Files Deleted
- ✅ All `manifest.yaml` files deleted (replaced by `snapshots.yaml`)
- ✅ No references to deleted manifests in code
- ✅ Old helper implementations removed from `lib.libsonnet`

#### Files Created
- ✅ `snapshots.yaml` exists and validates
- ✅ `docs/multi_file_issues_migration_report.md` exists
- ✅ All migration scripts preserved in `scripts/` for reference

#### Code References
- ✅ No references to `issueOneOccurrence`, `issueWithOccurrences`, `issueOccurrencesFromLines`
- ✅ All imports reference new model locations
- ✅ All tests use new helper names

### Final Validation Checklist

Before merging the PR, verify:

- ✅ **Full test suite passes** (pytest, including all props tests)
- ✅ **Ruff clean** (format + check)
- ✅ **Mypy clean** (no type errors)
- ✅ **Database populated** (verified via SQL queries)
- ✅ **CLI smoke tests pass** (all commands work)
- ✅ **Documentation complete** (authoring guide, quality checklist, migration report)
- ✅ **No "specimen" in user-facing code** (verified via grep)
- ✅ **Multi-file migration report complete** (all ~33 files documented)
- ✅ **All imports at top** (verified via grep for in-function imports)

---

## Summary of Key Design Decisions

### 1. True Positives vs False Positives

**Split at issue level** with different occurrence types:

- **True Positives (Issues)**:
  - Model: `Issue` with `IssueOccurrence[]`
  - Field: `expect_caught_from: set[frozenset[Path]]` (AND/OR logic, inner frozensets for hashability)
  - Semantics: Minimal file sets such that a good critic is **expected to find** the issue if pointed at any superset of any of these file sets
  - Example: `{{frozenset({'a.py', 'b.py'}), frozenset({'c.py'})}}` = "Expected if given {a.py, b.py} OR if given {c.py} (or supersets)"
  - Helpers: `issue()`, `issueMulti()`

- **False Positives**:
  - Model: `FalsePositive` with `FalsePositiveOccurrence[]`
  - Field: `relevant_files: set[Path]` (ANY logic)
  - Semantics: Show FP **to grader** if critic reviewed **ANY** of these files (not shown to critic, only for grader validation)
  - Example: `{'a.py', 'b.py', 'c.py'}` = "show to grader if ANY file reviewed"
  - Helpers: `falsePositive()`, `falsePositiveMulti()`

### 2. Database Strategy

**Drop and recreate** (no Alembic migration):
1. Via CLI: `adgn-properties2 db recreate` (drops schema + recreates + syncs from filesystem)
   - Automatically includes `db sync` step internally

Three tables:
- `snapshots`: Source pointers + split (NO `labeled_files` - computed from issues/occurrences)
- `issues`: True positives with `expect_caught_from` (NO `should_flag`)
- `false_positives`: False positives with `relevant_files`

### 3. Migration Scope

**Automatic** (~372 files):
- `issueOneOccurrence()` → `issue()` (add snapshot parameter)

**Manual** (~33 files):
- 26 files: `issueWithOccurrences()` → `issueMulti()` (add notes + expect_caught_from)
- 7 files: `issueOccurrencesFromLines()` → `issueMulti()` (expand to explicit occurrences)

### 4. CLI Simplification

**Single sync command**:
- `adgn-properties2 db sync` (syncs both snapshots and all issues)
- No separate subcommands

**Renamed commands**:
- All `specimen-*` → `snapshot-*`
- All `--specimen` → `--snapshot`

### 5. Testdata Handling

- Existing test fixtures in `tests/props/testdata/` auto-migrated
- Tests load YAML from testdata files (no hardcoded fixtures)
- Migration scripts handle both production and test data

### 6. Class Architecture

**Replaced**: `SpecimenRegistry`, `HydratedSpecimen`

**New classes** (clean separation at "Pydantic data" boundary):
1. `SnapshotHydrator` - Context manager: Snapshot spec → hydrated directory
2. `FilesystemLoader` - Loads snapshots/issues from YAML/Jsonnet → Pydantic
3. SQLAlchemy ORM models - Database queries via class methods
4. `sync_snapshots_to_db()` / `sync_issues_to_db()` - Orchestrates filesystem → DB

**Benefits**:
- Clear responsibilities: hydration, parsing, querying, syncing are separate
- Testable: each component has single, well-defined input/output
- SnapshotHydrator doesn't know about Jsonnet/DB, FileLoader doesn't know about DB
