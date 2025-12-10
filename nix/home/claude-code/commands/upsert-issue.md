---
description: Capture a code quality issue in the specimens repository (user)
---

Capture an issue (e.g., "foo() is dead code", "duplicate pattern in X and Y") in the specimens repository at `~/code/specimens`.

## Purpose

**Document issues in ground truth dataset** - When the user identifies a code quality issue during review/refactoring:
- Check if it's already captured in the latest snapshot
- If not, either add it or indicate a new snapshot is needed
- Follow libsonnet format and conventions from `~/code/specimens/CLAUDE.md`

## Usage

User will say something like:
- "upsert issue that foo() is dead code"
- "upsert issue: duplicate _parse_json helper in A.py and B.py"
- "upsert issue - missing type annotations in bar.py:123-145"

Extract:
- **Issue description**: What's wrong (dead code, duplication, type issue, etc.)
- **File paths and line ranges**: Where it occurs
- **Rationale**: Why this is a problem

## Workflow

### Step 1: Determine Current Repository

```bash
# Get current repo name and path
cd "$(pwd)"
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
REPO_NAME=$(basename "$REPO_ROOT")
```

**Map to specimens repo name:**
- `ducktape` → `ducktape/`
- `crush` → `crush/`
- Other repos → check if they exist in `~/code/specimens/`

### Step 2: Find Latest Snapshot for This Repo

```bash
# Check if repo exists in specimens
if [ ! -d ~/code/specimens/$REPO_NAME ]; then
    echo "Repo $REPO_NAME not in specimens yet"
    exit 1
fi

# Get latest snapshot (highest numbered YYYY-MM-DD-NN)
LATEST_SNAPSHOT=$(ls -1d ~/code/specimens/$REPO_NAME/20* 2>/dev/null | tail -1)
SNAPSHOT_SLUG="$REPO_NAME/$(basename "$LATEST_SNAPSHOT")"
```

### Step 3: Check if Issue Already Exists in Latest Snapshot

Use `adgn-properties snapshot exec` to introspect the snapshot and look for:
- The specific file/function mentioned
- Existing libsonnet files that might already document this issue

```bash
# Run from adgn directory where direnv is configured
cd /home/agentydragon/code/ducktape/adgn

# Example: Check if foo.py exists and look for the function
direnv exec /home/agentydragon/code/ducktape/adgn \
  adgn-properties snapshot exec "$SNAPSHOT_SLUG" -- \
    bash -lc "test -f /workspace/path/to/foo.py && grep -n 'def foo' /workspace/path/to/foo.py"

# Check existing issue files
ls ~/code/specimens/$SNAPSHOT_SLUG/*.libsonnet | xargs grep -l "foo.py" | head -5
```

**Search strategy:**
1. Verify the file/location exists in the snapshot using `snapshot exec`
2. Search existing `.libsonnet` files for mentions of the same file/function
3. Read any potentially matching libsonnet files to check if issue is already covered

### Step 4: Decision Point

**If issue is already documented:**
```
The issue "<description>" is already captured in:
- File: ~/code/specimens/<snapshot>/existing-issue.libsonnet
- ID: existing-issue
- Lines: <ranges>

Would you like me to:
a) Review and possibly update the existing issue?
b) Create a separate issue if this is distinct?
```

**If issue is NOT documented but file exists in snapshot:**
- Proceed to Step 5 (create new libsonnet issue file)

**If file doesn't exist in snapshot OR repo not in specimens:**
```
Cannot upsert this issue because:
- [Repo not in specimens] / [File not in latest snapshot]

We need to take a new snapshot to capture the current state.
Please teach me how to create snapshots for this repository.

Latest snapshot for $REPO_NAME: $LATEST_SNAPSHOT
Current file: <path>
```

### Step 5: Create Libsonnet Issue File

**Generate issue ID (kebab-case):**
- Extract essence of issue: "dead-code-foo", "duplicate-parse-json", "missing-type-annotations-bar"
- Check ID doesn't conflict: `ls ~/code/specimens/$SNAPSHOT_SLUG/<id>.libsonnet`
- Add suffix if needed: `-2`, `-3`, etc.

**Draft libsonnet file** following format from `~/code/specimens/lib.libsonnet`:

```jsonnet
local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    <Clear description of what's wrong and why it matters>

    <Show code snippet if helpful (≤30 lines)>

    <Suggest fix if appropriate>
  |||,
  filesToRanges={
    'relative/path/from/workspace/to/file.py': [[start_line, end_line]],
    // Use null for whole-file issues
    // Use multiple entries for cross-file issues
  },
  // expect_caught_from is optional for single-file issues (auto-inferred)
  // REQUIRED for multi-file issues: [[file1], [file2, file3]] (OR/AND logic)
)
```

**For duplicated code issues** (multiple independent occurrences), use `issueMulti`:

```jsonnet
local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Function _foo appears in multiple files with identical/similar logic.
    Should be extracted to shared utility.
  |||,
  occurrences=[
    {
      files: { 'path/to/A.py': [[10, 20]] },
      note: 'First occurrence',
      expect_caught_from: [['path/to/A.py']]
    },
    {
      files: { 'path/to/B.py': [[45, 55]] },
      note: 'Duplicate in B',
      expect_caught_from: [['path/to/B.py']]
    },
  ],
)
```

**Write the file:**
```bash
cat > ~/code/specimens/$SNAPSHOT_SLUG/<issue-id>.libsonnet <<'EOF'
<generated content>
EOF
```

### Step 6: Verify Issue File

```bash
# Check jsonnet syntax
cd ~/code/specimens
jsonnet <snapshot>/<issue-id>.libsonnet >/dev/null

# Verify file paths exist in snapshot
direnv exec /home/agentydragon/code/ducktape/adgn \
  adgn-properties snapshot exec "$SNAPSHOT_SLUG" -- \
    bash -lc "ls -la /workspace/<file-path>"
```

### Step 7: Report to User

```
✓ Created issue: <issue-id>
  File: ~/code/specimens/<snapshot>/<issue-id>.libsonnet

Summary:
- Type: <dead-code | duplication | missing-types | etc>
- Files: <list>
- Lines: <ranges>

Issue has been captured in the specimens dataset for training.
```

## Key Conventions

**From ~/code/specimens docs (CLAUDE.md, docs/format-spec.md, docs/authoring-guide.md):**
- Use `local I = import '../../lib.libsonnet';` at top
- Triple-bar blocks (|||) for rationale, indent 2 spaces
- File paths relative to workspace root (no leading `/workspace/`)
- Line ranges: `[[start, end]]` or `null` for whole file
- Use `I.issue` for simple cases (single logical occurrence)
- Use `I.issueMulti` for duplicates/multiple independent occurrences
- Closing `|||,` (comma on same line as closing bars)
- Exact indentation: 2 spaces for content inside |||
- Closing delimiter: two spaces + `|||,` on its own line
- No string-based forward references in ranges
- File name = issue ID (no `.id` field in jsonnet)

## Helper Functions Reference

**True Positives:**
```jsonnet
// Single logical occurrence (one or more files)
I.issue(rationale, filesToRanges, expect_caught_from=null)
// expect_caught_from: optional for single-file, REQUIRED for multi-file
// Format: [[file1], [file2, file3]] - OR logic across lists, AND within

// Multiple independent occurrences
I.issueMulti(rationale, occurrences)
// Each occurrence MUST have: files, note
// If total files > 1: ALL occurrences MUST have expect_caught_from
```

**False Positives:**
```jsonnet
// Single occurrence false positive
I.falsePositive(rationale, filesToRanges, relevant_files=null)

// Multiple occurrences false positive
I.falsePositiveMulti(rationale, occurrences)
```

## Error Handling

**Common issues:**
1. **File not in snapshot**: Tell user snapshot is stale, need new one
2. **Invalid jsonnet syntax**: Fix indentation/commas before writing
3. **Duplicate issue ID**: Add numeric suffix
4. **Wrong file paths**: Verify paths exist in snapshot using `snapshot exec`

## Complete Example

User: "upsert issue that derive_run_phase() in status_shared.py is dead code"

```bash
# 1. Determine repo
REPO_NAME=ducktape
SNAPSHOT=ducktape/2025-12-04-00

# 2. Check if file exists in snapshot
direnv exec /home/agentydragon/code/ducktape/adgn \
  adgn-properties snapshot exec $SNAPSHOT -- \
    grep -n "def derive_run_phase" /workspace/adgn/src/adgn/agent/server/status_shared.py

# Output: 25:def derive_run_phase(...

# 3. Check if already documented
ls ~/code/specimens/$SNAPSHOT/*.libsonnet | xargs grep -l "status_shared" | xargs grep -l "derive_run_phase"
# (no results = not documented)

# 4. Create issue file
cat > ~/code/specimens/$SNAPSHOT/dead-code-derive-run-phase.libsonnet <<'EOF'
local I = import '../../lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Function derive_run_phase() is defined but never called.
    The codebase uses determine_run_phase() instead (which has more precise logic).
    This function should be deleted.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [[25, 34]],
  },
)
EOF

# 5. Verify
jsonnet ~/code/specimens/$SNAPSHOT/dead-code-derive-run-phase.libsonnet
```

## Notes

- **Always use absolute paths** for direnv exec: `/home/agentydragon/code/ducktape/adgn`
- **Specimens repo is separate** from main codebase (sibling directory)
- **Snapshot slug format**: `<repo>/<YYYY-MM-DD-NN>` (e.g., `ducktape/2025-12-04-00`)
- **Don't create snapshots yourself** - remind user to teach you if needed
