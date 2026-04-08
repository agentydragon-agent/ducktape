---
name: followups
description: >
  Surface all pending followups and verify session work is still on disk.
  Use when user says "bt", "backtrace", "stack", "where are we", or asks about
  current progress on a multi-step task.
allowed-tools: Bash, Read, Glob, Grep, Agent
---

Surface all pending followups and verify session work is still on disk.

## Purpose

**Save user time and cognitive load** - If there's >10-20% chance the user wants to do something, surface it for them to select with a key press. Much cheaper than having to remember/type it themselves.
**Memory guide** - Make sure nothing mentioned (by user or agent) gets forgotten.
**Verify persistence** - Double-check work done in this session is actually on disk (not stashed/reverted by parallel process).

## Process

### Phase 1: Verify Session Work Still Exists (CRITICAL)

**Consider delegating to subagent** for read-only verification tasks:

- Good for: Checking multiple files, searching for patterns, reading git status
- Provides distinct scope: "Verify these N files contain expected changes"

**Accessing session history for delegation:**
If delegating conversation analysis to subagent, use the `session_logs` skill for finding and analyzing Claude Code session logs.

See: `~/.claude/skills/session_logs/SKILL.md` for complete documentation.

Quick reference:

```bash
# Find current session file
CURRENT_SESSION=$(~/.claude/skills/session_logs/find-current-session.sh)

# Get session analysis and statistics
~/.claude/skills/session_logs/analyze-session.sh

# Or analyze specific session
~/.claude/skills/session_logs/analyze-session.sh /path/to/session.jsonl
```

The session_logs skill provides:

- Automatic current session discovery (scores by cwd, git branch, recency)
- Session log format documentation (JSONL structure, field meanings)
- Common query examples (Extract tool calls, find modified files, get user messages)
- Helper scripts for analysis

Check all files created/modified in this session:

- Read file to confirm changes are present
- Check git status shows them as modified/untracked
- If missing: ALERT prominently - "⚠️ Work lost: [file] no longer contains [change]"
- If stashed: Note "📦 Stashed: Changes in stash - user may want to pop"

**Output:**

```
✅ All session work verified on disk
or
⚠️ MISSING: file.py - expected changes not found (stashed? reverted?)
```

### Phase 2: Extract What We Talked About But Didn't Do

**Consider delegating** conversation analysis for large sessions:

- Good for: Scanning long conversations, extracting patterns
- Can provide session log access (see Phase 1)

Scan conversation for:

- "should...", "could...", "TODO", "later", "next time"
- "maybe add...", "consider...", "might want to..."
- Incomplete actions ("let's do X" → did it actually get done?)
- Questions asked but not fully answered

### Phase 3: Find Natural Followups

**Consider delegating** independent discovery tasks:

- Good for: Code pattern searches, workflow checks, cleanup scans
- Can split into distinct scopes with separate files-allowed-to-edit blocks

**Code propagation analysis:**

- If created new helper/class → search for hand-rolled equivalents
- If DRYed pattern → search for remaining duplicates
- If fixed bug → search for similar bugs
- If added validation → find sites missing it

**Workflow completion:**

- Git: Any modified files? → suggest commit message
- Tests: Did code change? → suggest test command
- Docs: Did behavior change? → check if docs updated
- Pre-commit: Any pre-commit hooks to run?

**Cleanup opportunities:**

- Dead code from this session's changes
- Newly unused imports
- Outdated comments referencing old code
- Inconsistencies introduced

### Phase 4: Prevent Recurrence Analysis

If the session involved debugging, diagnosing, or working around a problem, ask:

**Has this happened before?**

- Search recent Claude session logs for similar symptoms, error messages, or affected components
- Check `debug/` directories and `lessons_learned/` for prior investigations of the same area
- If recurring: this is a higher-priority followup — the pattern needs a structural fix, not another one-off diagnosis

**Can we prevent it from happening again?**

For each significant problem encountered, consider whether any of these would be worth the effort:

- **Pre-commit check or CI test**: Catches the problem before it ships (e.g., lint rule, validation script, regression test)
- **Automated guard**: Code-level assertion, type constraint, or invariant that makes the bad state unrepresentable
- **Better diagnostics**: More logging, metrics, or transparency that would make the _next_ occurrence faster to diagnose (e.g., structured error messages, health check endpoints, undeclared test outputs)
- **Easier workflow**: A CLI command, script, or alias that automates the manual steps we had to do (e.g., `bbapi target history --failures-only` was built this session because manual API calls were painful)
- **Documentation**: A `lessons_learned/` entry, `AGENTS.md` update, or troubleshooting section that captures the diagnosis path so future sessions don't start from scratch

Surface these as followup suggestions with concrete proposals, not vague "consider adding tests." Example:

```
B. **Add pre-commit check for unquoted URLs in pnpm lockfiles**
   - We spent time diagnosing a check-yaml failure caused by pnpm's YAML output
   - A targeted check could catch this on lockfile regeneration
```

### Phase 5: Probabilistic Action Suggestions

For each potential action, estimate probability user wants it:

**>80% probability - DO NOW category:**

- Commit modified files (if changes were made)
- Fix breaking changes introduced
- Complete half-finished work

**40-80% probability - LIKELY category:**

- Run tests after code changes
- Propagate new pattern to obvious sites
- Update related documentation
- Push committed work

**20-40% probability - MAYBE category:**

- Add tests for new feature
- Refactor similar code
- Improve error messages
- Add logging

**10-20% probability - OPTIONAL category:**

- Performance optimizations
- Nice-to-have cleanups
- Documentation improvements for edge cases

**<10% probability - omit** (don't waste user's attention)

## Output Format

````markdown
# Followups - Session [timestamp]

## ⚠️ Verification

✅ All work from this session verified on disk

- src/feature/ (3 files modified)
- config/settings.yaml (new validation added)
- tests/test_feature.py (new)

## 🔴 DO NOW

1. **Commit feature implementation**
   ```bash
   git add src/feature/
   git commit -m "feat: implement user authentication with JWT tokens"
   ```
````

2. **Commit test coverage**

   ```bash
   git add tests/test_feature.py
   git commit -m "test: add unit tests for authentication flow"
   ```

## 🟡 LIKELY

a. **Run test suite**

- Verify new tests pass and no regressions

  ```bash
  pytest tests/test_feature.py -v
  ```

b. **Remove unused helper functions**

- legacy_auth_helper (auth.py:145)
- deprecated_token_parser (utils.py:89)
- old_validation_logic (validators.py:234)

c. **Update API documentation**

- New endpoints need OpenAPI specs
- Authentication flow diagram

## 🟢 MAYBE

A. **Finish refactor away from FOO singleton to Foo class**

- Started migration in src/core/
- 8 more callsites in src/legacy/

B. **Propagate new validation pattern**

- Check if other endpoints could use same validator
- Search for manual validation that could be replaced

C. **Update architecture documentation**

- Recent changes to auth flow
- May need diagrams in docs/architecture/

## 🔵 OPTIONAL

x. Add performance benchmarks for new code paths
y. Consider adding retry logic for network calls
z. Update CONTRIBUTING.md with new testing patterns

---

**Quick actions:**

- Type `1` or `2` to execute DO NOW items
- Type `a`, `b`, or `c` for LIKELY items
- Type `A`, `B`, or `C` for MAYBE items
- Type `x`, `y`, or `z` for OPTIONAL items
- Type `all-likely` to queue a+b+c
- Type `skip` to continue with new work

````

## Implementation Requirements

### 1. Consider Delegation

Delegate tasks that are:

- Read-only discovery (searching, scanning, verifying)
- Independently executable with clear scope
- Chunkable into distinct files-allowed-to-edit blocks
- Large enough that parallel execution provides value

### 2. Parallel Execution (When Appropriate)

If tasks are truly independent, spawn subagents in parallel:

```python
# Example: 3 independent read-only tasks
Task 1: "Verify these files still contain changes: [list]"
Task 2: "Search codebase for pattern X usage sites"
Task 3: "Check git status and suggest commit messages"
# Wait for all, combine results
```

### 3. Concrete Commands

Every suggestion includes exact command to run:

- ✅ `git commit -m "exact message"`
- ✅ `pytest tests/specific_test.py::test_name`
- ❌ "consider committing changes"

### 4. Probability Calibration

Be honest about probabilities:

- 90%: User explicitly said "do this next"
- 70%: Standard workflow step (commit after edits)
- 50%: Natural followup (tests after code change)
- 30%: Improvement opportunity (refactor similar code)
- 15%: Nice-to-have (documentation polish)

### 5. Session Verification Template

For every file touched:

```
✅ path/to/file.py - verified (shows expected changes at line X)
or
⚠️ path/to/file.py - MISSING expected changes (check git stash)
```

### 6. Zero False Omissions

Better to show 5 low-probability items than miss the one action user wanted.
Err on side of over-suggesting rather than under-suggesting.
````
