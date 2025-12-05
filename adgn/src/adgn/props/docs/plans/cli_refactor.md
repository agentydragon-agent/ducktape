# CLI App Refactoring Plan

## Status: PARTIALLY IMPLEMENTED / SUPERSEDED

**Last updated:** 2025-12-04

This plan has been partially implemented and the implementation took a better approach than originally proposed. Key improvements:

1. ✅ **Implemented:** `cmd_db.py`, `cmd_detector.py`, `cmd_build_bundle.py`
2. ✅ **Better approach:** Snapshot commands organized as `snapshot` subcommand group (not in original plan)
3. ⚠️ **Decision needed:** Whether to continue extracting remaining commands from main.py

---

## Current State (2025-12-04)

```
cli_app/
├── decorators.py            ~25 lines  (utilities)
├── common_options.py        ~60 lines  (shared options)
├── types.py                ~30 lines  (custom Typer types)
├── shared.py               ~180 lines (CLI utilities)
├── cmd_db.py               ~110 lines ✓ DONE (sync, db-recreate)
├── cmd_detector.py         ~330 lines ✓ DONE (run-detector, detector-coverage)
├── cmd_build_bundle.py     ~450 lines ✓ DONE (build-bundle)
└── main.py                 ~862 lines (14 commands + snapshot subgroup)
Total: ~2,047 lines
```

### Main.py Commands

**Top-level commands:**
- `check` - Check path against properties
- `snapshot-discover` - Discover new issues vs notes
- `cluster-unknowns` - Cluster unknown findings
- `prompt-optimize` - Optimize prompt with budget
- `snapshot-grade` - Grade critique by ID
- `fix` - Refactor code to satisfy properties
- `lint-issue` - Lint issue definitions
- `eval-all` - Run all evaluations
- `run` - Unified runner (snapshot|path + structured|freeform)
- `list-presets` - List available presets

**Snapshot subcommands (`snapshot <command>`):**
- `snapshot list` - List all snapshot slugs
- `snapshot dump` - Dump snapshot JSON
- `snapshot exec` - Execute command in snapshot container
- `snapshot capture-ducktape` - Capture ducktape repo as snapshot

---

## Implementation Improvements vs Original Plan

### 1. Snapshot Subcommand Group ✅

**Original plan:** Flat commands like `specimen-exec`, `specimen-grade`, `specimen-dump`

**Actual implementation:** Typer sub-app for logical grouping:
```python
snapshot_app = typer.Typer(help="Snapshot commands")
app.add_typer(snapshot_app, name="snapshot")

@snapshot_app.command("exec")
async def snapshot_exec(...): ...
```

**Benefits:**
- Clear namespace (`snapshot exec` vs `specimen-exec`)
- Help organization (`adgn-properties snapshot --help`)
- Extensibility (easy to add more snapshot commands)

### 2. Consistent Naming ✅

All "specimen" references renamed to "snapshot" for consistency with:
- Codebase terminology (`SnapshotSlug`, `SnapshotRegistry`)
- Data model (`snapshot_slug` in DB, not `specimen_id`)

### 3. cmd_build_bundle.py ✅

Not in original plan, but correctly extracted as standalone module (~450 lines).

---

## Original Extraction Plan (OUTDATED)

> **Note:** The extraction plan below is from the initial planning phase. Some line numbers and organization details are no longer accurate. Kept for historical reference only.

<details>
<summary>Original extraction plan (click to expand)</summary>

### Proposed Modules (Original Plan)

1. **cmd_analysis.py** (~75 lines) - check, lint-issue, cluster-unknowns
2. **cmd_fix.py** (~34 lines) - fix
3. **cmd_prompt.py** (~40 lines) - prompt-optimize, eval-all
4. **cmd_snapshot.py** (~280 lines) - snapshot commands
5. **cmd_runtime.py** (~220 lines) - run, list-presets

### Why Not Fully Implemented

- **Snapshot subgroup:** Better solution than extracting to separate module
- **Low churn:** Most commands are stable and rarely modified together
- **Single file acceptable:** 862 lines in main.py is manageable
- **Clear organization:** Commands already well-structured within main.py

</details>

---

## Future Considerations

### Option 1: Keep Current Structure (Recommended)

**Rationale:**
- ~862 lines in main.py is reasonable for a CLI entry point
- Commands are logically organized (snapshot subgroup works well)
- Low maintenance burden (rarely need to modify multiple commands at once)
- Easy navigation with good editor folding

**When to reconsider:**
- main.py exceeds 1500 lines
- Commands share significant amounts of duplicated code
- Need to test command groups independently

### Option 2: Extract Remaining Commands

If extraction is desired, recommended grouping:

```
cli_app/
├── cmd_analysis.py      (check, lint-issue, cluster-unknowns)
├── cmd_prompt.py        (prompt-optimize, eval-all)
├── cmd_fix.py           (fix)
├── cmd_snapshot.py      (snapshot-discover, snapshot-grade, snapshot subgroup)
├── cmd_runtime.py       (run, list-presets)
└── main.py              (~100 lines - app setup and registrations)
```

**Benefits:**
- Easier testing of command groups
- Reduced main.py to minimal wiring
- Commands grouped by domain

**Costs:**
- More import management
- Shared helper placement decisions
- Potential circular import risks

---

## Progress Tracking

- [x] cmd_db.py (sync, db-recreate)
- [x] cmd_detector.py (run-detector, detector-coverage)
- [x] cmd_build_bundle.py (build-bundle)
- [x] Snapshot subcommand group (list, dump, exec, capture-ducktape)
- [x] Consistent snapshot terminology (specimen → snapshot)
- [ ] Further extraction (DECISION PENDING)

---

## Conclusion

The current CLI organization is **good enough** for now. The snapshot subcommand group is a significant improvement over the original flat structure. Further extraction should only be pursued if:

1. main.py grows significantly (>1500 lines)
2. Command testing becomes difficult
3. Significant code duplication emerges between commands

**Recommendation:** Close this refactoring plan and create a new focused plan if extraction becomes necessary in the future.
