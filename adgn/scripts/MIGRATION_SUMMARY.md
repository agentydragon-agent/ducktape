# Issue File Migration Script - Summary

## What Was Created

### 1. Migration Script
**File**: `/home/user/ducktape/adgn/scripts/migrate_issue_files.py`

A Python script that automates the migration of issue files from old Jsonnet helpers to new helpers (MIGRATION_PLAN.md Phase 3.2).

**Key Features**:
- Auto-migrates 372 files using `issueOneOccurrence`
- Identifies 33 files requiring manual review
- Handles both true positives and false positives
- Updates import paths and moves files to flat structure
- Provides detailed migration report with guidance
- Includes environment validation
- Safe dry-run mode for previewing changes

### 2. Documentation
**File**: `/home/user/ducktape/adgn/scripts/README_migrate_issue_files.md`

Comprehensive documentation covering:
- Script usage and examples
- Prerequisites and verification steps
- Manual migration guide
- Troubleshooting
- Rollback procedures

## Migration Statistics

Based on analysis of the codebase:

| Category | Count | Action |
|----------|-------|--------|
| **Auto-Migration** | **372 files** | Automated by script |
| - True Positives (issues/) | 366 files | → `issue()` helper |
| - False Positives (false_positives/) | 6 files | → `falsePositive()` helper |
| **Manual Migration** | **33 files** | Requires human review |
| - issueWithOccurrences | 26 files | → `issueMulti()` with notes + expect_caught_from |
| - issueOccurrencesFromLines | 7 files | → `issueMulti()` with expanded occurrences |
| **Total** | **405 files** | |

## Quick Start

### 1. Preview the Migration (Recommended First Step)

```bash
cd /home/user/ducktape/adgn
python scripts/migrate_issue_files.py --dry-run
```

This shows:
- Which files will be auto-migrated
- Which files need manual review
- Detailed transformation preview
- No files are modified

### 2. Execute Auto-Migration

After reviewing the dry-run output:

```bash
python scripts/migrate_issue_files.py
```

This will:
- Migrate 372 files automatically
- Move files from `issues/` and `false_positives/` to parent directories
- Update helper names, add snapshot parameters, fix import paths
- Leave 33 files in `issues/` directories for manual review
- Remove empty `issues/` and `false_positives/` directories

### 3. Complete Manual Migrations

For the 33 remaining files, follow the guide printed by the script:

**Files requiring manual review**:
```
issueOccurrencesFromLines (7 files):
  ducktape/2025-09-03-00/issues/exceptions-for-control-flow.libsonnet
  ducktape/2025-09-03-00/issues/remove-shebangs-libs.libsonnet
  ducktape/2025-09-03-00/issues/scoped-try-except-swallow.libsonnet
  ducktape/2025-11-22-02/issues/historical-comments.libsonnet
  ducktape/2025-11-22-02/issues/obvious-comments.libsonnet
  ducktape/2025-11-22-02/issues/one-off-variables.libsonnet
  ducktape/2025-11-26-00/issues/useless-docstrings.libsonnet

issueWithOccurrences (26 files):
  [See dry-run output for complete list]
```

## Script Implementation Details

### Transformations Applied

#### For True Positives (366 files):
```jsonnet
// BEFORE (in issues/ directory)
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= ||| ... |||,
  filesToRanges={ 'src/cli.py': [[145, 167]] },
)

// AFTER (in parent directory)
local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= ||| ... |||,
  filesToRanges={ 'src/cli.py': [[145, 167]] },
)
```

#### For False Positives (6 files):
```jsonnet
// BEFORE (in false_positives/ directory)
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  should_flag=false,
  rationale= ||| ... |||,
  filesToRanges={ 'view.go': [[258, 276]] },
)

// AFTER (in parent directory)
local I = import '../lib.libsonnet';

I.falsePositive(
  snapshot='crush/2025-08-30-internal_db',
  rationale= ||| ... |||,
  filesToRanges={ 'view.go': [[258, 276]] },
)
```

### Changes Applied by Script

1. ✅ **Helper name replacement**: `issueOneOccurrence` → `issue` or `falsePositive`
2. ✅ **Snapshot parameter addition**: `snapshot='{repo}/{version}'` as first parameter
3. ✅ **should_flag removal**: For false positives, removes `should_flag=false,` line
4. ✅ **Import path update**: `../../specimens/lib.libsonnet` → `../lib.libsonnet`
5. ✅ **File relocation**: Moves from `issues/` or `false_positives/` to parent directory
6. ✅ **Directory cleanup**: Removes empty `issues/` and `false_positives/` directories

### Environment Validation

Script validates before running:
- ✅ `lib.libsonnet` exists at expected location
- ✅ New helpers present: `issue:`, `issueMulti:`, `falsePositive:`, `falsePositiveMulti:`
- ✅ Specimens directory exists

## Verification Commands

After running the migration:

### 1. Check File Counts
```bash
# Auto-migrated files should be in parent directories
find src/adgn/props/specimens -name "*.libsonnet" ! -path "*/issues/*" ! -path "*/false_positives/*" ! -name "lib.libsonnet" | wc -l
# Expected: 372

# Manual review files should still be in issues/
find src/adgn/props/specimens -name "*.libsonnet" -path "*/issues/*" | wc -l
# Expected: 33

# No files should remain in false_positives/
find src/adgn/props/specimens -name "*.libsonnet" -path "*/false_positives/*" | wc -l
# Expected: 0
```

### 2. Check Old Helpers Removed
```bash
# Should only find old helpers in files needing manual review
grep -r "issueOneOccurrence" src/adgn/props/specimens --include="*.libsonnet" | wc -l
# Expected: 33 (manual review files still using old helpers)
```

### 3. Check Import Paths Updated
```bash
# Migrated files should use new import path
grep -r "import '../lib.libsonnet'" src/adgn/props/specimens --include="*.libsonnet" | wc -l
# Expected: 372 (all auto-migrated files)

# Manual review files still use old import path
grep -r "import '../../specimens/lib.libsonnet'" src/adgn/props/specimens --include="*.libsonnet" | wc -l
# Expected: 33 (manual review files)
```

### 4. Check New Helpers Usage
```bash
# Count files using new issue() helper
grep -r "I\.issue(" src/adgn/props/specimens --include="*.libsonnet" | wc -l
# Expected: 366 (auto-migrated TPs)

# Count files using new falsePositive() helper
grep -r "I\.falsePositive(" src/adgn/props/specimens --include="*.libsonnet" | wc -l
# Expected: 6 (auto-migrated FPs)
```

## Next Steps

### Immediate (After Auto-Migration)
1. ✅ Run verification commands above
2. ✅ Review git diff to spot-check transformations
3. ✅ Test loading a few migrated files
4. ✅ Commit auto-migration results

### Manual Migration (33 Files)
1. ⏳ Migrate issueOccurrencesFromLines files (7 files)
2. ⏳ Migrate issueWithOccurrences files (26 files)
3. ⏳ Add notes and expect_caught_from fields
4. ⏳ Test and verify manual migrations
5. ⏳ Commit manual migration results

### Phase 3.3 (Database Sync)
After all 405 files are migrated:
1. ⏳ Run `adgn-properties2 db sync` to populate database
2. ⏳ Verify database integrity
3. ⏳ Test loading issues from database

## Rollback Plan

If migration produces unexpected results:

```bash
# Revert all changes
git checkout -- src/adgn/props/specimens/

# Or revert specific specimen
git checkout -- src/adgn/props/specimens/ducktape/2025-11-26-00/
```

## Support and Troubleshooting

### Common Issues

1. **"lib.libsonnet is missing new helpers"**
   - Ensure Phase 2 (Jsonnet helper redesign) is complete
   - Check that `lib.libsonnet` contains new helper exports

2. **"Specimens directory not found"**
   - Run from `/home/user/ducktape/adgn` directory
   - Or specify path with `--specimens-dir`

3. **Import errors after migration**
   - Verify file was moved to parent directory
   - Check import path changed to `../lib.libsonnet`

### Getting Help

- **Migration plan**: `/home/user/ducktape/adgn/src/adgn/props/docs/MIGRATION_PLAN.md`
- **Script README**: `/home/user/ducktape/adgn/scripts/README_migrate_issue_files.md`
- **Helper docs**: `/home/user/ducktape/adgn/src/adgn/props/specimens/lib.libsonnet`
- **Authoring guide**: `/home/user/ducktape/adgn/src/adgn/props/docs/authoring.md`

## Files Created

| File | Purpose |
|------|---------|
| `scripts/migrate_issue_files.py` | Main migration script (executable) |
| `scripts/README_migrate_issue_files.md` | Detailed usage documentation |
| `scripts/MIGRATION_SUMMARY.md` | This summary document |

---

**Ready to migrate!** Start with `python scripts/migrate_issue_files.py --dry-run` to preview the changes.
