---
description: Intelligently organize and commit overlapping changes in a messy git repository
name: commit
---

Analyze a repository with many unstaged changes and help create clean, logical commits from the chaos.

## Usage

```
/commit
```

Or naturally in conversation:
```
U: help me commit these changes
A: I'll analyze your uncommitted changes and suggest logical commits.

U: organize my git mess
A: Let me scan your repository and propose clean commits.

U: commit
A: Starting repository analysis for intelligent commit suggestions.
```

## Overview

This command helps when you have:
- Many untracked/dirty files
- Overlapping changes across files
- Mixed refactors, features, and experiments
- Abandoned work mixed with valuable changes

## Process Flow

### 1. Pre-commit Cleanup

Run automated cleanup to avoid wasted effort:
```
U: /commit
A: Running pre-commit checks and auto-cleanup first...
   
   🧹 Auto-formatting with pre-commit hooks:
   ✓ Fixed whitespace in 12 files
   ✓ Reformatted Python with black (8 files)
   ✓ Sorted imports with isort (5 files)
   ✓ Fixed line endings (3 files)
   
   ⚠️ Pre-commit made changes. Continuing with analysis...
```

If pre-commit fails:
```
A: ❌ Pre-commit checks failed:
   - Large file detected: debug.log (>10MB)
   - Merge conflict markers in api/routes.py
   
   Fix these issues first? [fix/continue anyway/abort]
```

### 2. Index State Preservation

If the git index already has staged changes:
```
U: /commit
A: I see you have 3 files already staged. I'll save this index state so we can restore it if needed.
   
   Saving index state to: .git/COMMIT_TOOL_SAVED_INDEX_1706234567
   ✓ Index state saved. You can restore with: git read-tree COMMIT_TOOL_SAVED_INDEX_1706234567
   
   Resetting index to analyze all changes...
```

### 2. Change Analysis

```
A: Analyzing repository changes...

📊 Repository State:
- 47 modified files
- 23 untracked files  
- 12 deleted files
- ~2,400 lines changed

🔍 Detected logical change groups:
1. Auth service implementation (12 files, ~450 lines)
2. Logging refactor (8 files, ~200 lines)
3. API documentation updates (5 files, ~150 lines)
4. Test suite additions (15 files, ~800 lines)
5. Config file updates (3 files, ~50 lines)

🗑️ Likely unwanted:
- 5 log files (*.log)
- 3 abandoned experiment files (experiment-*.py)
- Backup files (*~, *.backup)

📝 Notes:
- File auth.py has changes for both auth service AND logging refactor
- The logging refactor touches many files but changes are consistent
- Found 3 possible abandoned features that could be cleaned up
```

### 3. Commit Proposals (Progressive)

When there are many changes:
```
A: Found 5 logical commits so far (15 more files remain unanalyzed):

1️⃣ [config] Update environment configs
   - .env.example: Add new auth variables
   - config/settings.py: Add auth configuration
   - docker-compose.yml: Add auth service
   
2️⃣ [feat] Implement authentication service
   - auth/service.py: New auth service class
   - auth/models.py: User and token models  
   - api/endpoints.py: Add auth endpoints (hunks 1-3)
   - tests/test_auth.py: Auth service tests
   
3️⃣ [refactor] Standardize logging across services
   - utils/logger.py: New centralized logger
   - api/endpoints.py: Update to new logger (hunk 4)
   - services/*.py: Replace print with logger (8 files)
   
4️⃣ [docs] Update API documentation
   - README.md: Document auth endpoints
   - docs/api.md: Full endpoint documentation
   - auth/service.py: Add docstring examples (hunk 5)

5️⃣ [test] Add integration test suite
   - tests/integration/*: New test files
   - .github/workflows/test.yml: Run integration tests

What would you like to do?
- 1-5: Stage and commit specific change
- all: Stage all 5 commits in order
- more: Continue analyzing remaining 15 files
- custom: Create custom grouping
```

### 4. Interactive Staging

```
U: let's do 2
A: Staging commit 2: [feat] Implement authentication service

📋 Saving current index state...
✓ Saved to: .git/COMMIT_TOOL_SAVED_INDEX_1706234568

🔄 Resetting index...
📝 Staging changes:
  ✓ auth/service.py (full file)
  ✓ auth/models.py (full file)
  ✓ api/endpoints.py (hunks 1-3 only)
  ✓ tests/test_auth.py (full file)

✅ Changes staged. Please review with: git diff --cached

Options:
- commit - Create the commit
- review - Show the staged diff
- unstage - Undo and restore previous state
- amend - Add/remove files from staging
```

### 5. Smart Hunk Selection

For files with overlapping changes:
```
U: show me how you'll split api/endpoints.py
A: File api/endpoints.py has changes for multiple commits:

Hunk 1 (lines 15-45): ✅ Include - Auth endpoint definitions
```python
+@app.post("/auth/login")
+async def login(credentials: LoginRequest):
+    """Authenticate user and return token."""
+    user = await auth_service.authenticate(credentials)
+    return {"token": generate_token(user)}
```

Hunk 2 (lines 47-62): ✅ Include - Auth middleware  
```python
+@app.middleware("http")
+async def auth_middleware(request: Request, call_next):
+    token = request.headers.get("Authorization")
+    request.state.user = await verify_token(token)
```

Hunk 3 (lines 78-85): ✅ Include - Error handling for auth
```python
+except AuthenticationError as e:
+    return JSONResponse({"error": str(e)}, status_code=401)
```

Hunk 4 (lines 120-125): ❌ Exclude - Logging refactor (separate commit)
```python
-    print(f"Request: {request.path}")
+    logger.info(f"Request: {request.path}")
```

This creates a clean separation between features.
```

## Features

### Intelligent Grouping
- Detects related changes across files
- Identifies refactoring patterns
- Separates features from cleanup
- Handles files with mixed changes

### Safety Features
- Always preserves index state before changes
- Can restore to any saved state
- Shows preview before committing
- Allows incremental review

### Cleanup Detection
- Identifies likely unwanted files (logs, backups)
- Suggests .gitignore additions
- Detects abandoned experiments
- Finds incomplete features

## Natural Language Triggers

- "help me commit"
- "organize these changes"
- "clean up my commits"
- "stage these changes properly"
- "split up this mess"

## Examples

### Basic Usage
```
U: /commit
A: [full analysis and proposals as shown above]

U: do commits 1 and 3
A: I'll stage those commits in order.
   
   First, commit 1: [config] Update environment configs
   [stages files]
   Ready to commit. Run: git commit -m "[config] Update environment configs"
   
   After you commit, tell me "next" for commit 3.
```

### Handling Complex Splits
```
U: file x.py has too many unrelated changes, help
A: Let me analyze x.py in detail...
   
   I found 4 distinct change types in x.py:
   - Lines 10-45: New feature A
   - Lines 100-120: Refactoring logging  
   - Lines 200-250: New feature B
   - Lines 300-310: Typo fixes
   
   I can stage these as separate commits using git add -p.
   Would you like me to walk through each hunk? [y/n]
```

### Cleanup Mode
```
U: just clean up the junk
A: I'll help remove unwanted files:
   
   🗑️ Suggested for deletion:
   - server.log (2.3MB)
   - debug.log (5.1MB)  
   - backup-2023-*.sql (3 files, 150MB)
   - experiment-*.py (not referenced)
   
   📝 Suggested .gitignore additions:
   *.log
   backup-*.sql
   experiment-*.py
   
   Delete files and update .gitignore? [y/n/selective]
```

## Advanced Features

### Saved States Management
```
U: show saved states
A: Saved index states:
   
   1. COMMIT_TOOL_SAVED_INDEX_1706234567 (2 hours ago) - 3 files
   2. COMMIT_TOOL_SAVED_INDEX_1706234568 (5 min ago) - empty
   
   Restore with: git read-tree <state-name>
```

### Custom Commit Creation
```
U: I want to create my own grouping
A: Interactive mode activated. I'll help you build custom commits.
   
   Select files for your commit:
   1. [ ] auth/service.py
   2. [ ] auth/models.py
   3. [ ] api/endpoints.py (partial)
   4. [ ] tests/test_auth.py
   
   Enter numbers to toggle (e.g., "1 3"), or "done" when ready:
```

## Integration

- Works with @{#messy-workspace} detection
- Can trigger /cleanup for identified junk
- Respects @{#no-data-loss} by saving states
- Compatible with git hooks and aliases

## Technical Implementation

### Index State Saving
Uses git's tree objects to preserve index state:
```bash
# Save current index as tree object
git write-tree  # Returns tree SHA

# Restore index from tree
git read-tree <tree-sha>
```

### Hunk Analysis
- Uses `git diff --cached` for staged changes
- Uses `git diff` for unstaged changes  
- Parses unified diff format
- Groups by semantic patterns

## Notes

- Never commits automatically - always requires confirmation
- Preserves all changes - nothing is lost
- Can be interrupted and resumed
- Works with partial staging (git add -p)