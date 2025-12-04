# Issue File Migration Script (Phase 3.2)

This script automates the migration of issue files from old Jsonnet helpers to new helpers as part of the specimen-to-snapshot migration (MIGRATION_PLAN.md Phase 3.2).

## Overview

The migration script handles:

### Auto-Migration (~372 files)
- **issueOneOccurrence** → **issue()** (for true positives in `issues/` directories)
- **issueOneOccurrence with should_flag=false** → **falsePositive()** (for files in `false_positives/` directories)

Changes applied:
1. Update helper name (`issue` or `falsePositive`)
2. Add `snapshot='{slug}'` as first parameter
3. Remove `should_flag` parameter (for false positives)
4. Update import path: `../../lib.libsonnet` → `../lib.libsonnet`
5. Move file from `specimens/{slug}/issues/*.libsonnet` to `specimens/{slug}/*.libsonnet`
6. Move file from `specimens/{slug}/false_positives/*.libsonnet` to `specimens/{slug}/*.libsonnet`

### Manual Migration Flagged (~33 files)
Files using these helpers require manual intervention:
- **issueWithOccurrences** (26 files) → needs `issueMulti` with notes + `expect_caught_from`
- **issueOccurrencesFromLines** (7 files) → needs expansion to explicit occurrences

## Prerequisites

1. **Phase 2 Complete**: `lib.libsonnet` must have the new helpers (`issue`, `issueMulti`, `falsePositive`, `falsePositiveMulti`)
2. **Git Clean State**: Commit or stash any changes before running (for easy rollback if needed)
3. **Python 3.11+**: Script requires Python 3.11 or later

## Usage

### 1. Preview Changes (Dry Run)

**Always run dry-run first** to review what will be changed:

```bash
cd /home/user/ducktape/adgn
python scripts/migrate_issue_files.py --dry-run
```

This will:
- Show total files to be migrated
- List auto-migration transformations
- List files needing manual review
- Provide manual migration guidance
- **Not modify any files**

### 2. Execute Migration

After reviewing the dry-run output:

```bash
python scripts/migrate_issue_files.py
```

This will:
- Auto-migrate 372 files
- Move files from `issues/` and `false_positives/` to parent directories
- Remove empty `issues/` and `false_positives/` directories
- Leave 33 files for manual review

### 3. Manual Migration

For the 33 files flagged for manual review, follow the guide printed by the script:

#### For issueWithOccurrences → issueMulti:
1. Change helper: `I.issueWithOccurrences` → `I.issueMulti`
2. Add snapshot parameter: `snapshot='<repo>/<version>'` as first parameter
3. Add `note` field to ALL occurrences (required)
4. Add `expect_caught_from` field to ALL occurrences if total files > 1
   - Format: `[['file1.py'], ['file2.py', 'file3.py']]`
   - Semantics: Issue detectable from ANY of these file sets (OR)
   - Inner arrays are files required together (AND)
5. Update import: `../../lib.libsonnet` → `../lib.libsonnet`
6. Move file from `issues/` to parent directory

#### For issueOccurrencesFromLines → issueMulti:
1. Change helper: `I.issueOccurrencesFromLines` → `I.issueMulti`
2. Expand `linesByFile` dict to explicit occurrence objects
3. Each occurrence needs:
   - `files`: `{file: [[start, end]], ...}`
   - `note`: string explaining this specific occurrence
   - `expect_caught_from`: minimal file sets for detection
4. Add snapshot parameter and update import/move file as above

## Example Transformations

### Auto-Migration: True Positive

**Before** (`specimens/ducktape/2025-11-26-00/issues/dead-code.libsonnet`):
```jsonnet
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Function is never called. Remove it.
  |||,
  filesToRanges={
    'src/cli.py': [[145, 167]],
  },
)
```

**After** (`specimens/ducktape/2025-11-26-00/dead-code.libsonnet`):
```jsonnet
local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Function is never called. Remove it.
  |||,
  filesToRanges={
    'src/cli.py': [[145, 167]],
  },
)
```

### Auto-Migration: False Positive

**Before** (`specimens/crush/2025-08-30-internal_db/false_positives/fp-002.libsonnet`):
```jsonnet
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  should_flag=false,
  rationale= |||
    This looks like duplication but isn't.
  |||,
  filesToRanges={
    'internal/llm/tools/view.go': [[258, 276]],
  },
)
```

**After** (`specimens/crush/2025-08-30-internal_db/fp-002.libsonnet`):
```jsonnet
local I = import '../lib.libsonnet';

I.falsePositive(
  snapshot='crush/2025-08-30-internal_db',
  rationale= |||
    This looks like duplication but isn't.
  |||,
  filesToRanges={
    'internal/llm/tools/view.go': [[258, 276]],
  },
)
```

## Verification

After migration, verify:

1. **File counts match**:
   ```bash
   # Before migration
   find src/adgn/props/specimens -name "*.libsonnet" -path "*/issues/*" | wc -l  # 399
   find src/adgn/props/specimens -name "*.libsonnet" -path "*/false_positives/*" | wc -l  # 7

   # After migration (all files should be in parent directories)
   find src/adgn/props/specimens -name "*.libsonnet" -path "*/issues/*" | wc -l  # 33 (manual review)
   find src/adgn/props/specimens -name "*.libsonnet" -path "*/false_positives/*" | wc -l  # 0
   ```

2. **No old helpers remain** (except in files needing manual review):
   ```bash
   grep -r "issueOneOccurrence" src/adgn/props/specimens --include="*.libsonnet" | wc -l  # 33
   ```

3. **Import paths updated**:
   ```bash
   # Should find 0 files with old import in migrated files
   grep -r "import '../../specimens/lib.libsonnet'" \
     src/adgn/props/specimens/*/[!i]*.libsonnet | wc -l  # 0
   ```

## Rollback

If migration fails or produces unexpected results:

```bash
git checkout -- src/adgn/props/specimens/
```

This will restore all files to their pre-migration state.

## Migration Report Example

```
================================================================================
MIGRATION REPORT (EXECUTED)
================================================================================

Total files processed: 405
  - Auto-migrated: 372
  - Need manual review: 33

--------------------------------------------------------------------------------
AUTO-MIGRATED FILES (372)
--------------------------------------------------------------------------------

issueOneOccurrence → falsePositive (6 files):
  [list of files...]

issueOneOccurrence → issue (366 files):
  [list of files...]

--------------------------------------------------------------------------------
FILES NEEDING MANUAL REVIEW (33)
--------------------------------------------------------------------------------

issueOccurrencesFromLines (7 files):
  [list of files...]

issueWithOccurrences (26 files):
  [list of files...]

--------------------------------------------------------------------------------
MANUAL MIGRATION GUIDE
--------------------------------------------------------------------------------
[detailed guide...]
```

## Troubleshooting

### "lib.libsonnet is missing new helpers"

**Problem**: Phase 2 (Jsonnet helper redesign) is not complete.

**Solution**: Ensure `src/adgn/props/specimens/lib.libsonnet` contains the new helpers:
- `issue:`
- `issueMulti:`
- `falsePositive:`
- `falsePositiveMulti:`

### "Specimens directory not found"

**Problem**: Running from wrong directory or path is incorrect.

**Solution**:
```bash
cd /home/user/ducktape/adgn
python scripts/migrate_issue_files.py --specimens-dir src/adgn/props/specimens
```

### Files not migrating

**Problem**: Files may already be migrated or use unrecognized helpers.

**Solution**: Check the file manually. If it's using new helpers already, no action needed.

## Next Steps After Migration

1. **Complete Manual Migrations**: Migrate the 33 flagged files
2. **Verify All Files**: Run validation commands above
3. **Test Loading**: Ensure all migrated files can be loaded by the system
4. **Commit Changes**: Create a commit for the auto-migration
5. **Continue to Phase 3.3**: Sync to database

## Related Documentation

- Main migration plan: `/home/user/ducktape/adgn/src/adgn/props/docs/MIGRATION_PLAN.md`
- Helper documentation: `/home/user/ducktape/adgn/src/adgn/props/specimens/lib.libsonnet`
- Authoring guide: `/home/user/ducktape/adgn/src/adgn/props/docs/authoring.md`
