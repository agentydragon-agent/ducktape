# CLI App Refactoring Plan

## Status: COMPLETE

**Last updated:** 2025-12-10

The CLI is well-organized with clear separation of concerns. All major refactoring tasks are complete.

---

## Current Structure

```
cli/
├── decorators.py            ~25 lines  (async helpers)
├── common_options.py        ~90 lines  (shared CLI options)
├── types.py                 ~30 lines  (custom Typer types)
├── shared.py               ~180 lines  (CLI utilities)
├── cmd_db.py               ~185 lines  (db sync, db recreate)
├── cmd_detector.py         ~341 lines  (run-detector, detector-coverage)
├── cmd_snapshot.py         ~380 lines  (snapshot list/dump/exec/shell/capture-ducktape)
├── cmd_gepa.py              ~96 lines  (gepa optimization)
└── main.py                 ~650 lines  (9 commands + app setup)
Total: ~2,080 lines
```

**Main.py commands:**
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
- `snapshot` subgroup → `cmd_snapshot.py` (list, dump, exec, shell, capture-ducktape)

---

## Recent Work (2025-12-10)

### ✅ Git Bundle to Plain Files Migration

Migrated from git bundles to plain files:
- `issues/*.libsonnet` for issues
- `code/...` for actual snapshotted files
- LocalSource for locally-captured snapshots
- GitSource preserved for remote repositories

**Deleted:**
- `cmd_build_bundle.py` (~420 lines)
- `cmd_migrate_bundles.py` (~320 lines)
- `tests/props/bundles/test_bundle_validation.py` (~238 lines)
- Total: ~978 lines removed

**Updated:**
- `cmd_snapshot.py` - capture workflow now uses plain files
- `file_filters.py` - extracted shared gitignore pattern matching
- `hydration.py` - removed file:// URL rewriting
- `models/snapshot.py` - clarified BundleFilter is historical metadata only

---

## Optional Future Work

**Move snapshot commands to subgroup:**
- `snapshot-grade` → `snapshot grade`
- `snapshot-discover` → `snapshot discover`
- Would reduce main.py by ~80 lines
- Not urgent (main.py at 650 lines is manageable)

**Extract analysis commands:**
- If main.py exceeds 1000 lines, consider grouping: check, lint-issue, cluster-unknowns
- Current assessment: Not needed

---

## Summary

✅ **Clear module boundaries**: CLI layer vs implementation
✅ **Subcommand groups**: Logical namespacing (db, snapshot)
✅ **Lazy imports**: Fast CLI startup
✅ **Consistent patterns**: @async_run, shared options
✅ **No bundle complexity**: Plain files workflow

**Current state:** Excellent ✅
**Overall structure:** Maintainable and extensible
