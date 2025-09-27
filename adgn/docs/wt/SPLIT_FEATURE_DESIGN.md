# Split Feature Design

## Overview

A new feature for `wt` that allows splitting large PRs by moving files from the current branch to a new worktree. This addresses the common scenario where a PR grows too large and needs to be split into smaller, more reviewable chunks.

## Motivation

- Large PRs are harder to review and understand
- Sometimes you realize mid-development that changes should be split
- Need a clean way to extract files/changes while maintaining git history
- Should feel natural and integrated with existing worktree workflow

## Core Functionality

### High-Level Flow

1. Identify files/changes to move from current branch
2. Create a new worktree for the extracted changes
3. Remove the changes from current branch
4. Leave current branch in clean state
5. New worktree contains the extracted changes ready for independent PR

### Command Interface

#### Basic Mode: File List
```bash
wt split <new-worktree-name> <file1> <file2> ...
wt split my-new-feature src/feature.py src/feature_test.py
```

#### Interactive Mode
```bash
wt split --interactive <new-worktree-name>
wt split -i my-new-feature
```

## Interactive Mode Design

### REPL Interface

Similar to `git add --interactive` but for file/change movement:

```
Split Plan for 'my-new-feature':
Files to move:
  1. src/feature.py (modified, +150 -20)
  2. src/feature_test.py (new file, +80)
  3. docs/feature.md (modified, +30 -5)

Commands:
  [s]how plan
  [a]dd file
  [r]emove file  
  [p]atch (edit chunks)
  [e]xecute plan
  [q]uit

What now> 
```

### Interactive Commands

#### Show Plan (`s`)
Display current plan with file status and change summary

#### Add File (`a`) 
```
Add file> src/another_file.py
Added src/another_file.py to split plan
```

#### Remove File (`r`)
```
Remove file> 2
Removed src/feature_test.py from split plan
```

#### Patch Mode (`p`)
Enter patch-style editing for specific files:
```
Patch file> 1
# Shows hunks for src/feature.py
Hunk 1/3: @@ -10,6 +10,15 @@
 def existing_function():
     pass
 
+def new_feature_function():
+    return "new feature"
+
 def another_function():
     pass

[y]es move this hunk, [n]o keep in current branch, [s]kip to next file: 
```

#### Execute (`e`)
Execute the split plan:
- Create new worktree
- Move selected files/hunks
- Clean up current branch
- Show summary of what was moved

#### Quit (`q`)
Exit without making changes

## Implementation Considerations

### Git Operations

#### File Movement Strategy
1. **Full File Move**: Simple case - entire file moves to new worktree
2. **Partial File Move**: Complex case - only some hunks move, file exists in both branches

#### For Full File Moves:
```bash
# In current branch
git rm <file>
git commit -m "Move <file> to separate branch"

# In new worktree  
git checkout current-branch -- <file>
git add <file>
git commit -m "Add <file> from main branch"
```

#### For Partial File Moves:
1. Use `git apply` with patch splitting

...

