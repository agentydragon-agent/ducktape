---
description: Clean up temporary files, side outputs, and oneoff scripts
name: cleanup
---

Intelligent cleanup of temporary work artifacts, focusing on oneoff scripts and exploration side-effects.

## Usage

Clean up the current directory:
```
/cleanup
```

Or use naturally in conversation:
```
U: cleanup the temp files
A: I'll scan for temporary files and oneoff scripts to clean up.

U: clean up my experiments 
A: Looking for experimental code and temporary outputs to remove.

U: cleanup
A: Starting cleanup scan for temporary artifacts.
```

## What Gets Cleaned

### 1. Oneoff Scripts (Priority)
Pattern: `oneoff__*.{py,js,ts,sh}` @{#oneoff-scripts}

```
U: cleanup oneoffs
A: Found 5 oneoff scripts:
   - oneoff__test_webhook_integration.py (2 days old)
   - oneoff__bulk_rename_vars.py (1 week old)
   - oneoff__debug_auth_flow.js (3 hours old)
   Would you like to delete all? [y/n/selective]
```

### 2. Temporary Outputs
- Test outputs: `test-output-*`, `*-test-results.*`
- Debug logs: `debug-*.log`, `*.debug`, `trace-*`
- Temporary data: `*.tmp`, `*.temp`, `temp-*`, `tmp-*`
- Process artifacts: `*.pid`, `*.lock` (except INSTANCE_LOCK.md)
- Cache files: `*.cache`, `.cache/` (if not gitignored)

### 3. Exploration Artifacts
- Quick analysis: `analysis-*.txt`, `output-*.json`
- Extracted data: `extracted-*.{json,txt,csv}`
- Download remnants: `download-*`, `snapshot-*.json.backup`
- Screenshot captures: `/tmp/tana-captures/` (older than 1 day)

### 4. Failed Attempts
- Backup files: `*.backup`, `*.old`, `*~`
- Version sprawl: `*-v2`, `*-final`, `*-FINAL-FINAL`
- Partial outputs: `*.partial`, `*.incomplete`

### 5. Build Artifacts in Wrong Places
- Node modules outside project: `./node_modules/` in scripts/
- Python caches: `__pycache__/`, `*.pyc` outside venv
- TypeScript outputs: `*.js` files with corresponding `*.ts`

## Safety Features

### Always Protected
- Git worktrees (use `git worktree remove`)
- Active lock files (INSTANCE_LOCK.md with recent timestamp)
- Config files (even if named `.tmp`)
- Anything in `.git/`
- Files modified in last hour (unless explicitly requested)

### Smart Detection
```
U: cleanup
A: Cleanup scan found:

📝 Oneoff Scripts (5 files, 12KB):
  ✓ oneoff__test_api_v2.py - "Can delete after: API tests added" (3 days old)
  ✓ oneoff__bulk_rename.sh - "Can delete after: Rename complete" (1 week old)
  ⚠️ oneoff__debug_current.py - Modified 10 minutes ago, skip? [y/n]

🗑️ Temporary Files (23 files, 145MB):
  - debug-2024-01-*.log (15 files, 89MB)
  - test-output-*.json (8 files, 56MB)

💾 Old Snapshots (3 files, 267MB):
  - workspace-snapshot-2024-01-15.json.backup
  - workspace-snapshot-2024-01-14.json.old
  - snapshot-before-refactor.json

📦 Found archive at: ./experiments/archive/
What would you like to do? (archive all/delete all/archive oneoffs only/pick each/cancel)
```

### Confirmation Options
- `all` or `yes` - Delete everything found
- `oneoffs` - Only delete oneoff scripts  
- `temp files` or `temp` - Only delete temporary files
- `snapshots` - Only delete old snapshots
- `pick each` or `selective` - Choose file by file
- `nothing` or `no` - Cancel cleanup

## Natural Language Triggers

Nonexhaustive examples of recognized phrases:
- "cleanup", "clean up", "clean"
- "remove temp files", "delete temporary"
- "cleanup oneoffs", "remove oneoff scripts"
- "tidy up", "clean workspace"

## Examples

```
U: I've been experimenting a lot, cleanup
A: I'll scan for experimental artifacts and oneoff scripts.
   
   Found:
   - 8 oneoff scripts (oneoff__*.py)
   - 45 temporary outputs
   - 3 old workspace snapshots
   
   Total: 523MB can be cleaned up. Proceed? [y/n]

U: just cleanup the oneoffs from last week
A: Found 3 oneoff scripts older than 7 days:
   - oneoff__migrate_data.py (10 days)
   - oneoff__test_old_api.py (8 days)  
   - oneoff__benchmark_v1.py (14 days)
   
   Delete these 3 files? [y/n]

U: cleanup but keep anything related to auth
A: Cleanup scan (excluding *auth* files):
   
   Safe to delete:
   - oneoff__test_performance.py
   - debug-render-2024.log
   - tmp-calculations.json
   
   Keeping:
   - oneoff__debug_auth_flow.py (matches 'auth')
   - auth-test-results.json (matches 'auth')
   
   Proceed? [y/n]
```

## Archive Detection

The cleanup command automatically detects nearby archive directories:
- `./archive/`
- `./archives/`
- `./old/`
- `./experiments/archive/`
- `../.archive/` (parent directory)

When found, offers to move files instead of deleting:

```
U: cleanup
A: Found archive directory at ./archive/experiments/
   
   📝 Oneoff Scripts (3 files):
   - oneoff__test_integration.py
   - oneoff__bulk_process.py
   
   Would you like to:
   - archive - Move to ./archive/experiments/2024-01-20/
   - delete - Permanently delete
   - selective - Choose per file
   - cancel

U: archive
A: Moving to archive:
   ✓ oneoff__test_integration.py → ./archive/experiments/2024-01-20/
   ✓ oneoff__bulk_process.py → ./archive/experiments/2024-01-20/
   
   Archived 2 files. Archive location saved to cleanup-archive.log
```

## Best Practices

1. **Archive vs delete** - Use archives for experiments that might be referenced later
2. **Date-based subdirs** - Archives are organized by date automatically
3. **Archive log** - Creates `cleanup-archive.log` tracking what was archived when

## Integration with Other Patterns

- Works with @{#oneoff-scripts} marking pattern
- Respects @{#messy-workspace} detection
- Follows @{#no-data-loss} principle - asks before deleting
- Compatible with version control - suggests `git rm` for tracked files
- Auto-triggered by WORK_COMPLETE trigger when temp files were used

## Automatic Trigger

When completing work that used temporary files or oneoff scripts:

```
U: test the webhook integration
A: I'll create a oneoff script to test the webhook...
   [creates oneoff__test_webhook.py]
   [runs tests]
   ✅ Webhook integration working correctly!
   
   🧹 I created temporary files during this work. Would you like to clean up?
   - oneoff__test_webhook.py
   - webhook-test-output.json
   
   [cleanup/keep/selective]

U: cleanup
A: Removing temporary work files:
   ✓ Deleted oneoff__test_webhook.py
   ✓ Deleted webhook-test-output.json
```

## Notes

- Never auto-deletes without confirmation
- Shows file ages and sizes for context
- Groups similar items for easier decisions
- Suggests adding patterns to `.gitignore`
- Can be undone with git if needed (for tracked files)
