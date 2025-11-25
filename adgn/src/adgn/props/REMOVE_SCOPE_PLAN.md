# Plan: Remove Specimen Scope, Keep Only Bundle Filters

## Problem Statement

Specimens currently have two overlapping concepts for filtering code:

1. **scope**: Describes what code is being analyzed (file patterns like `**/*.py`, `adgn/**/*.py`)
2. **bundle**: Controls what code is included in the git bundle snapshot (directory patterns like `adgn/`, `wt/`)

This creates redundancy and confusion:
- Bundle determines what code is physically present in the hydrated copy
- Scope purportedly describes what subset of that code is analyzed
- In practice, we analyze everything in the bundle anyway
- Having both requires maintaining two filter specifications that need to stay consistent

## Current Usage

### Where scope is used:

1. **Display/UI purposes** (prompts/util.py:build_scope_text):
   - Generates human-readable text like "all files under wt/** (excluding: wt/tests/**)"
   - Inserted into LLM prompts to describe what code is being analyzed

2. **Referenced in 5 locations** (all for display):
   - `cli_app/main.py:221` - build prompt for specimen runs
   - `cli_app/main.py:624` - list specimens command  - `cli_app/main.py:635` - show specimen details
   - `cli_app/main.py:661` - show specimen in UI
   - `prompt_eval/server.py:187` - build wiring text

3. **Schema definition** (models/specimen.py:30-32):
   ```python
   class Scope(BaseModel):
       include: list[str]
       exclude: list[str] | None = None
   ```

4. **Required field in SpecimenDoc** (models/specimen.py:55):
   ```python
   scope: Scope
   ```

### Where bundle is used:

1. **Bundle creation** (bundles/build_bundle.py:298-299):
   - Actually controls what files go into the git bundle snapshot
   - Uses gitignore-style patterns

2. **Schema definition** (models/specimen.py:35-44):
   ```python
   class BundleFilter(BaseModel):
       include: list[str] | None = None
       exclude: list[str] | None = None
   ```

3. **Optional field in SpecimenDoc** (models/specimen.py:56):
   ```python
   bundle: BundleFilter | None = None
   ```

## Proposed Solution

**Remove scope entirely, derive scope text from bundle filters.**

### Key insight:
The bundle already determines what code is present in the hydrated copy. We don't need a separate "scope" concept - just analyze everything in the bundle. The bundle filters can be used to generate human-readable scope descriptions for prompts.

### Changes required:

1. **Update Pydantic schema** (models/specimen.py):
   - Remove `Scope` class
   - Make `bundle: BundleFilter` required (not optional) in `SpecimenDoc`
   - Remove `scope: Scope` field from `SpecimenDoc`

2. **Update build_scope_text function** (prompts/util.py):
   - Change signature to accept bundle filters instead of scope
   - Generate similar human-readable text from bundle include/exclude
   - Example: "adgn/, wt/ (excluding: adgn/src/adgn/props/specimens/)"

3. **Update all callers** (5 locations):
   - Replace `man.scope.include, man.scope.exclude` with `man.bundle.include, man.bundle.exclude`
   - Requires bundle to be required (not None)

4. **Update all specimen manifests** (~6 ducktape specimens):
   - Remove `scope:` section
   - Keep `bundle:` section
   - For specimens where scope was more specific than bundle:
     - Option A: Adjust bundle to match old scope (narrower snapshot)
     - Option B: Accept analyzing all bundled code (simpler, recommended)

5. **Update documentation**:
   - Remove references to scope from CLAUDE.md, README.md
   - Update examples to show only bundle filters
   - Clarify that bundle determines both snapshot content AND analysis scope

6. **Update tests**:
   - Remove scope from test specimen fixtures
   - Update assertions that check manifest structure
   - Ensure bundle is present in all test specimens

## Migration Strategy

### Phase 1: Make bundle required, add transitional support
1. Change `bundle: BundleFilter | None` to `bundle: BundleFilter` in schema
2. Add default empty bundle if None (for backward compat during migration)
3. Update build_scope_text to accept either scope OR bundle (transitional)

### Phase 2: Update all manifests
1. For each specimen, either:
   - Copy scope patterns to bundle (if they differ)
   - Remove scope section (if bundle is sufficient)
2. Verify no specimens have `bundle: None`

### Phase 3: Remove scope from schema
1. Remove `Scope` class from models/specimen.py
2. Remove `scope` field from SpecimenDoc
3. Update build_scope_text to only accept bundle
4. Update all callers to use bundle
5. Remove transitional compatibility code

### Phase 4: Update documentation and tests
1. Update all docs to remove scope references
2. Update test fixtures
3. Update jsonnet helpers if needed

## Example Manifest Transformations

### Before (current):
```yaml
source:
  vcs: git
  url: file://../specimens.bundle
  ref: refs/tags/specimen-2025-11-22-repo
scope:
  include:
  - '**/*.py'
  - '**/*.md'
  - '**/*.yaml'
bundle:
  include:
  - adgn/
  - wt/
  exclude:
  - adgn/src/adgn/props/specimens/
```

### After (proposed):
```yaml
source:
  vcs: git
  url: file://../specimens.bundle
  ref: refs/tags/specimen-2025-11-22-repo
bundle:
  include:
  - adgn/
  - wt/
  exclude:
  - adgn/src/adgn/props/specimens/
```

The scope text generated would change from:
- Old: "all files under **/*.py, **/*.md, **/*.yaml, **/*.yml, **/*.ts, **/*.tsx"
- New: "all files under adgn/, wt/ (excluding: adgn/src/adgn/props/specimens/)"

This is actually **more accurate** - it describes what code is actually present, not just which file types we care about.

## Impact Assessment

### Breaking changes:
- All existing specimen manifests need updating (remove `scope:` section)
- Any external code loading specimens will fail if it expects `scope` field
- Generated scope text will be different (directory-based vs file-pattern-based)

### Benefits:
- Single source of truth for code filtering
- Simpler mental model: bundle = snapshot = analysis scope
- Fewer fields to maintain in manifests
- More accurate scope descriptions (based on actual content, not patterns)
- Eliminates potential inconsistency between scope and bundle

### Risks:
- Specimens with very specific scope (e.g., `adgn/src/adgn/agent/**/*.py`) would need either:
  - Narrower bundle (more targeted snapshot)
  - Or accept analyzing more code than before
- May break external tools that consume specimen manifests

## Decision Points

1. **Should we narrow bundles to match old scopes?**
   - Recommended: No - accept analyzing all bundled code for simplicity
   - Alternative: Yes - make bundles as specific as old scopes (more work, smaller snapshots)

2. **Should we support transitional "scope-in-bundle" patterns?**
   - Recommended: No - pure directory-based filtering is simpler
   - Alternative: Yes - support file patterns in bundle for backward compat

3. **How to handle specimen-2025-11-20-adgn with scope `adgn/src/adgn/agent/**/*.py`?**
   - Option A: Change bundle to only include `adgn/src/adgn/agent/`
   - Option B: Keep bundle as `adgn/`, accept analyzing more code
   - Recommended: Option B (simpler, aligns with goal of removing scope)

## Next Steps

1. ✅ Create this plan document
2. Get user approval on approach and decision points
3. Implement Phase 1 (make bundle required)
4. Update all manifest files (Phase 2)
5. Remove scope from schema (Phase 3)
6. Update docs and tests (Phase 4)
7. Run full test suite to verify
8. Commit changes

## Questions for User

1. Should we narrow bundles to match specific old scopes, or accept broader analysis?
2. Any concerns about the breaking change to scope text format?
3. Are there external tools/scripts that depend on the scope field?
