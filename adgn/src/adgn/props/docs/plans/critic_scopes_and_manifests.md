# Critic Scopes & Manifest Reorganization

**Status:** Validation implemented, reorganization planned
**Date:** 2025-12-04

## Context

Per-file training examples enable fine-grained optimization by targeting specific file combinations rather than full-snapshot review. This requires explicit specification of which file combinations should serve as training datapoints.

## Current Implementation (Phase 1)

### Centralized YAML Files

```
specimens/
  snapshots.yaml              # All snapshot metadata
  critic_scopes.yaml          # All critic scope specifications
  ducktape/
    2025-11-20-00/            # Issue files only
      *.libsonnet
```

**Limitations:**
- Two central files grow unboundedly
- Merge conflicts when multiple authors work on different snapshots
- Scope definitions separated from snapshots they describe
- Easy to forget adding scopes for new snapshots

### Validation (Implemented)

**Requirements:**
1. `critic_scopes.yaml` must exist (no longer optional)
2. Every `expect_caught_from` set must have a corresponding scope

**Enforcement:**
```python
loader.validate_critic_scopes_coverage()
# Raises ValueError with list of missing scopes
```

**Current Status:** Validation works, found ~300+ missing scopes across snapshots (expected - only populated 5 training snapshots so far)

## Proposed Reorganization (Phase 2)

### Per-Snapshot Manifests

```
specimens/
  ducktape/
    snapshots.bundle          # Shared code bundle
    2025-11-20-00/
      manifest.yaml           # Metadata + scopes together
      *.libsonnet             # Issue files
    2025-12-04-00/
      manifest.yaml
      *.libsonnet
```

**manifest.yaml structure:**
```yaml
# Snapshot metadata
source:
  vcs: github
  repo: agentydragon/ducktape
  ref: ab7e9d68ee5c34a61f1fc1e5f9919bb72a8aaa32
  bundle: ../snapshots.bundle

split: train

# Critic scopes (inline, not separate file)
# Rationale documented via comments
critic_scopes:
  # Agent initialization and core loop
  - files: ["adgn/src/adgn/agent/agent.py"]

  # Check for duplicated type definitions
  - files: ["adgn/src/adgn/mcp/types.py", "adgn/src/adgn/mcp/persist.py"]
```

**Benefits:**
- **Locality:** All snapshot data (metadata + scopes + issues) in one directory
- **Scalability:** No central files that grow without bound
- **Discoverability:** Directory structure mirrors data structure
- **Explicit validation:** Can't add snapshot without scopes
- **Parallel authoring:** No YAML merge conflicts

## Implementation Phases

### Phase 1: Validation ✅ DONE

- [x] Make `critic_scopes.yaml` required
- [x] Add `validate_critic_scopes_coverage()` method
- [x] Update tests
- [x] Document validation requirements

### Phase 2: Manifest Support (Planned)

1. Define `SnapshotManifest` schema (combines metadata + scopes)
2. Update `load_snapshots()` to discover `*/*/manifest.yaml` files
3. Derive slug from directory path: `specimens/ducktape/2025-11-20-00/` → `ducktape/2025-11-20-00`
4. Dual support: try manifests first, fallback to legacy YAMLs with warning
5. Add tests for manifest loading

### Phase 3: Migration (Planned)

1. Write migration script: `snapshots.yaml` + `critic_scopes.yaml` → per-snapshot manifests
2. Run on test data first
3. Update all documentation
4. Migrate production data
5. Remove legacy YAML support

**Estimated effort:** 2-3 days for complete migration

---

## Detailed Implementation Plan

### Schema Changes

**File:** `src/adgn/props/models/snapshot.py`

**Current:**
```python
class Snapshot(BaseModel):
    source: SnapshotSource
    split: Split
```

**New:**
```python
class SnapshotManifest(BaseModel):
    """Per-snapshot manifest combining metadata + critic scopes."""
    source: SnapshotSource
    split: Split
    critic_scopes: list[CriticScope] = Field(default_factory=list)

# Keep Snapshot for backwards compat initially
Snapshot = SnapshotManifest  # Alias during migration
```

### Loading Logic Changes

**File:** `src/adgn/props/loaders/filesystem.py`

#### `load_snapshots()`

**Current:**
- Reads `specimens/snapshots.yaml`
- Returns `dict[SnapshotSlug, Snapshot]`

**New:**
- Discovers all `*/*/manifest.yaml` files under `specimens/`
- Parses each manifest
- Derives slug from directory path: `specimens/ducktape/2025-11-20-00/` → `ducktape/2025-11-20-00`
- Returns `dict[SnapshotSlug, SnapshotManifest]`

**Pseudo-code:**
```python
def load_snapshots(self) -> dict[SnapshotSlug, SnapshotManifest]:
    manifests = {}
    for manifest_path in self.specimens_dir.rglob("*/*/manifest.yaml"):
        # Parse: specimens/ducktape/2025-11-20-00/manifest.yaml
        #   → slug: "ducktape/2025-11-20-00"
        project = manifest_path.parent.parent.name  # "ducktape"
        version = manifest_path.parent.name         # "2025-11-20-00"
        slug = SnapshotSlug(f"{project}/{version}")

        raw = yaml.safe_load(manifest_path.read_text())
        manifests[slug] = SnapshotManifest.model_validate(raw)

    return manifests
```

#### `load_critic_scopes()`

**Current:**
- Reads `specimens/critic_scopes.yaml`
- Returns `dict[SnapshotSlug, list[CriticScope]]`

**New:**
- Reads from manifests (already loaded by `load_snapshots()`)
- Extract `critic_scopes` field from each manifest

**Pseudo-code:**
```python
def load_critic_scopes(self) -> dict[SnapshotSlug, list[CriticScope]]:
    manifests = self.load_snapshots()
    return {
        slug: manifest.critic_scopes
        for slug, manifest in manifests.items()
    }
```

**Note:** Could cache `load_snapshots()` result to avoid re-parsing.

#### Bundle Path Resolution

**Current:** Bundle paths are in `snapshots.yaml` source

**New:** Bundle paths are relative in manifest: `bundle: ../snapshots.bundle`

**Resolution logic:**
```python
def _resolve_bundle_path(self, slug: SnapshotSlug, manifest: SnapshotManifest) -> Path:
    """Resolve bundle path from manifest."""
    if hasattr(manifest.source, 'bundle'):
        # Relative to manifest directory
        manifest_dir = self.specimens_dir / slug.split("/")[0] / slug.split("/")[1]
        return (manifest_dir / manifest.source.bundle).resolve()
    # Fallback logic for old-style bundles
    ...
```

### Test Updates

**Files to update:**

1. **`tests/props/loaders/test_critic_scopes.py`**
   - Update fixtures to create `manifest.yaml` instead of separate YAMLs
   - Test discovery of manifests from directory structure
   - Test relative bundle path resolution

2. **`tests/props/specimens/test_validation.py`**
   - Update to expect manifests

3. **`tests/props/bundles/test_bundle_validation.py`**
   - Update bundle path logic

**New tests needed:**
- `test_load_manifests_from_directory_structure()`
- `test_manifest_missing_raises_error()`
- `test_bundle_path_resolution()`
- `test_critic_scopes_in_manifest()`

### Documentation Updates

**Files to update:**

1. **`docs/authoring.md`**
   - Update structure diagram
   - Document `manifest.yaml` schema
   - Explain bundle path (`../snapshots.bundle`)
   - Update "Creating a new snapshot" workflow

2. **`docs/training_strategy.md`**
   - Update references to file locations
   - Show new manifest examples

3. **`README.md`**
   - Update structure overview

### Migration Strategy

#### Phase 1: Dual Support (Backwards Compatible)

1. Keep old `snapshots.yaml` and `critic_scopes.yaml` working
2. Add manifest support alongside:
   ```python
   def load_snapshots(self):
       # Try new manifests first
       manifests = self._load_from_manifests()
       if manifests:
           return manifests
       # Fallback to old snapshots.yaml
       return self._load_from_legacy_yaml()
   ```
3. Add validation warning: "Using legacy snapshots.yaml, migrate to manifests"

#### Phase 2: Migration Script

Create `scripts/migrate_to_manifests.py`:
```python
def migrate():
    # Read snapshots.yaml + critic_scopes.yaml
    # For each snapshot:
    #   - Create manifest.yaml
    #   - Copy metadata from snapshots.yaml
    #   - Copy scopes from critic_scopes.yaml
    #   - Update bundle path to relative
    # Backup old YAMLs
    # Delete old YAMLs
```

#### Phase 3: Remove Legacy Support

1. Remove fallback code
2. Make manifests mandatory
3. Update all documentation

### Bundle Organization

**Current:** Bundles are per-snapshot or shared ad-hoc

**New:** Bundles are explicitly per-project

**Benefits:**
- Clearer structure: `ducktape/snapshots.bundle` serves all ducktape snapshots
- Easier to update bundle for project (affects all snapshots)
- Explicit in manifest: `bundle: ../snapshots.bundle`

**Bundle naming convention:**
- `{project}/snapshots.bundle` - shared bundle for project
- Alternative: `{project}/snapshots-{date-range}.bundle` if versioning needed

---

## Risks & Mitigations

### Risk 1: Breaking Existing Code

**Mitigation:**
- Dual support during migration (Phase 1)
- Extensive test coverage before switching
- Migration script with validation

### Risk 2: Directory Structure Coupling

**Current:** Slug format (`project/version`) coupled to directory structure

**Mitigation:**
- Document slug derivation clearly
- Add validation: manifest location must match slug
- Consider making slug explicit in manifest (redundant but safer)

### Risk 3: Relative Path Issues

**Mitigation:**
- Resolve all paths relative to manifest location
- Validate bundle paths exist during loading
- Clear error messages for missing bundles

---

## Questions & Decisions

**Q: Should slug be explicit in manifest?**
A: Optional, derive from directory path by default. Validates consistency if present.

**Q: Per-project or per-snapshot bundles?**
A: Per-project by default (`ducktape/snapshots.bundle`), allow per-snapshot via relative path.

**Q: Backwards compatibility period?**
A: 2-week dual support with deprecation warnings, then hard cutover.

---

## Implementation Order

1. ✅ Add validation that `critic_scopes.yaml` must exist (done)
2. ✅ Add validation that all `expect_caught_from` sets have scopes (done)
3. ⏸ Define `SnapshotManifest` schema
4. ⏸ Update `load_snapshots()` with dual support
5. ⏸ Add tests for manifest loading
6. ⏸ Write migration script
7. ⏸ Run migration on test data
8. ⏸ Update documentation
9. ⏸ Remove legacy YAML support
10. ⏸ Verify all tests pass

---

## Files That Need Changes

### Core Implementation
- `src/adgn/props/models/snapshot.py` - Add SnapshotManifest
- `src/adgn/props/models/critic_scopes.py` - Possibly merge into snapshot.py
- `src/adgn/props/loaders/filesystem.py` - Update loading logic

### Tests
- `tests/props/loaders/test_critic_scopes.py`
- `tests/props/specimens/test_validation.py`
- `tests/props/bundles/test_bundle_validation.py`
- All test fixtures that create snapshots

### Documentation
- `docs/authoring.md`
- `docs/training_strategy.md`
- `docs/per_file_examples_tracking.md`
- `README.md`

### Tooling
- `scripts/migrate_to_manifests.py` (new)
- Any CLI commands that reference snapshots.yaml

### Data (Migration)
- `specimens/snapshots.yaml` → delete after migration
- `specimens/critic_scopes.yaml` → delete after migration
- `specimens/{project}/{version}/manifest.yaml` (create for each)

---

## Related Work

**Per-File Training Examples:** `docs/training_strategy.md`, `docs/per_file_examples_tracking.md`
- Implemented sidecar `critic_scopes.yaml` as interim solution
- Now has validation to ensure completeness
- Will migrate to per-snapshot manifests for better organization

**Behavior-Cloning Goal:** `docs/prompt_optimizer_context.md`
- Critic learns user's subjective code review judgment
- Per-file examples provide 5.8x more training signal
- Explicit scopes ensure all `expect_caught_from` sets are tested
