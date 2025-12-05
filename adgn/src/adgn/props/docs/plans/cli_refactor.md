# CLI App Refactoring Plan

## Status: MOSTLY COMPLETE

**Last updated:** 2025-12-04

Recent refactoring session completed major reorganization. The CLI is now well-structured with clear separation of concerns.

---

## Current State (2025-12-04 Evening)

### Directory Structure

```
cli/  (renamed from cli_app/)
├── decorators.py            ~25 lines  (async helpers)
├── common_options.py        ~90 lines  (shared CLI options)
├── types.py                 ~30 lines  (custom Typer types)
├── shared.py               ~180 lines  (CLI utilities)
├── cmd_db.py               ~185 lines  ✓ (db sync, db recreate)
├── cmd_detector.py         ~341 lines  ✓ (run-detector, detector-coverage)
├── cmd_build_bundle.py     ~417 lines  ✓ (build-bundle - has TODO for extraction)
├── cmd_snapshot.py         ~217 lines  ✓ (snapshot list/dump/exec/capture-ducktape)
├── cmd_gepa.py              ~96 lines  ✓ (gepa optimization)
└── main.py                 ~693 lines  (9 remaining commands + app setup)
Total: ~2,274 lines
```

### Recent Changes (This Session)

1. ✅ **DB commands reorganized:**
   - `sync` → `db sync`
   - `db-recreate` → `db recreate`
   - Created `db_app` Typer sub-app for logical grouping

2. ✅ **Extracted commands from main.py:**
   - `cmd_snapshot.py` (~217 lines)
   - `cmd_gepa.py` (~96 lines)
   - Reduced main.py from ~862 to ~693 lines

3. ✅ **Directory rename:**
   - `cli_app/` → `cli/`
   - Updated all imports and pyproject.toml entry point

4. ✅ **Critic prompts reorganization:**
   - Created `critic/prompts/__init__.py` with discovery functions
   - Moved .md files from `prompts/system/` to `critic/prompts/`
   - Renamed functions: `discover_detector_prompts()` → `list_critic_system_prompts()`
   - Deleted empty `detector/` directory (was: `detector/discovery.py`)
   - Updated all imports in `cmd_db.py`, `cmd_detector.py`, `db/prompts.py`

5. ✅ **DB module split:**
   - Merged `db/sync_model_metadata.py` into `db/sync.py`
   - Created `db/setup.py` for RLS/schema setup (extracted from `session.py`)
   - Deleted obsolete files: `snapshot_registry_init.py`, `detector/discovery.py`

### Main.py Commands (Remaining)

**Top-level commands in main.py:**
- `check` - Check path against properties
- `snapshot-discover` - Discover new issues vs notes
- `cluster-unknowns` - Cluster unknown findings
- `prompt-optimize` - Optimize prompt with budget
- `snapshot-grade` - Grade critique by ID
- `fix` - Refactor code to satisfy properties
- `lint-issue` - Lint issue definitions
- `eval-all` - Run all evaluations
- `run` - Unified runner (snapshot|path + structured|freeform)

**Subcommand groups:**
- `db` subgroup → `cmd_db.py` (sync, recreate)
- `snapshot` subgroup → `cmd_snapshot.py` (list, dump, exec, capture-ducktape)

---

## Implementation Quality

### What Works Well ✅

1. **Clear module boundaries:**
   - CLI layer (`cli/*.py`) vs implementation (`db/`, `critic/`, `gepa/`)
   - Each `cmd_*.py` is self-contained with minimal dependencies
   - Shared options/types/decorators in dedicated modules

2. **Subcommand groups:**
   - `db` and `snapshot` subgroups provide logical namespacing
   - Easy to discover related commands (`adgn-properties db --help`)

3. **Lazy imports:**
   - Heavy dependencies imported inside functions (e.g., GEPA in `cmd_gepa.py`)
   - Keeps CLI startup fast for simple commands

4. **Consistent patterns:**
   - All commands use `@async_run` decorator
   - Common options defined once in `common_options.py`
   - DB operations separated from CLI logic

### Known Issues / TODOs

1. **cmd_build_bundle.py** (~417 lines):
   - Has TODO comment noting most code is git/bundle logic, not CLI
   - Should extract to `bundles/builder.py` (implementation)
   - Keep only Typer command definition in CLI layer
   - Follows same pattern as `cmd_db.py` (CLI) vs `db/` (implementation)

2. **main.py still moderately large** (~693 lines):
   - 9 commands + app setup
   - Could extract further, but not urgent

---

## Next Recommended Refactor

### Priority 1: Extract Bundle Logic (cmd_build_bundle.py)

**Problem:** 417 lines in `cmd_build_bundle.py`, but most is git/bundle manipulation, not CLI.

**Solution:**
```
bundles/
├── __init__.py
├── builder.py          (git bundle logic, ~380 lines)
└── models.py           (BundleConfig, BundleResult dataclasses)

cli/
└── cmd_build_bundle.py (Typer command only, ~30 lines)
```

**Benefits:**
- Testable bundle logic without CLI harness
- Follows established pattern (cmd_db.py → db/)
- Clear separation: CLI wiring vs implementation

**Estimated effort:** 1-2 hours

### Priority 2: Extract Snapshot-Related Commands

**Problem:** `snapshot-grade`, `snapshot-discover` are in main.py but related to snapshot subgroup.

**Solution:** Move to `cmd_snapshot.py`
- `snapshot-grade` → `snapshot grade`
- `snapshot-discover` → `snapshot discover`

**Benefits:**
- All snapshot operations in one place
- Reduces main.py by ~80 lines
- Consistent with snapshot subgroup pattern

**Estimated effort:** 30 minutes

### Priority 3 (Optional): Extract Analysis Commands

If main.py becomes unwieldy (>1000 lines), consider:

```
cli/
└── cmd_analysis.py  (check, lint-issue, cluster-unknowns)
```

**Current assessment:** Not urgent. Main.py at 693 lines is manageable.

---

## Architecture Wins

### Separation of Concerns

```
cli/              # User-facing commands (Typer wiring)
├── cmd_db.py     # Calls functions from db/
├── cmd_snapshot.py
└── cmd_gepa.py

db/               # Database implementation
├── session.py    # Connection management
├── setup.py      # Schema/RLS setup (extracted this session)
├── sync.py       # Snapshot/issue sync
├── prompts.py    # Prompt storage
└── models.py     # ORM models

critic/           # Critic implementation
├── prompts/      # System prompts (reorganized this session)
│   ├── __init__.py
│   ├── dead_code.md
│   ├── contract_truthfulness.md
│   └── flag_propagation.md
└── critic.py

bundles/          # (FUTURE) Bundle building
└── builder.py
```

### Clear Dependencies

```
CLI → Implementation
cmd_db.py → db/{session,setup,sync,prompts}
cmd_snapshot.py → snapshot_registry, bundles/
cmd_gepa.py → gepa/
```

No circular imports, testable implementation layers.

---

## Progress Tracking

- [x] cmd_db.py (sync → db sync, db-recreate → db recreate)
- [x] cmd_detector.py (run-detector, detector-coverage)
- [x] cmd_build_bundle.py (extracted, but needs further split)
- [x] cmd_snapshot.py (snapshot subgroup commands)
- [x] cmd_gepa.py (gepa optimization)
- [x] cli_app/ → cli/ rename
- [x] Critic prompts reorganization (detector/ → critic/prompts/)
- [x] DB module split (sync_model_metadata merged, setup.py extracted)
- [x] Cleanup (deleted empty detector/, snapshot_registry_init.py)
- [ ] Extract bundle builder logic from cmd_build_bundle.py (NEXT)
- [ ] Move snapshot-grade/snapshot-discover to cmd_snapshot.py (OPTIONAL)
- [ ] Further main.py extraction (OPTIONAL, if >1000 lines)

---

## Conclusion

The CLI is now well-organized with clear boundaries. Most commands have been extracted from main.py into logical modules. The main remaining task is extracting bundle logic from `cmd_build_bundle.py` to match the pattern established by other commands.

**Current state:** Good ✅
**Next action:** Extract `bundles/builder.py` (see cmd_build_bundle.py TODO comment)
**Overall structure:** Maintainable and extensible
