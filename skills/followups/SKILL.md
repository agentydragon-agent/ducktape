---
name: followups
description: >
  Surface all pending followups and verify session work is still on disk.
  Use when user says "bt", "backtrace", "stack", "where are we", or asks about
  current progress on a multi-step task.
allowed-tools: Bash, Read, Glob, Grep, Agent, AskUserQuestion
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

### Phase 5: Verify Suggestions Are Actionable

Before surfacing any suggestion, verify it's actually actionable right now:

- **Git push/commit**: Check `git status` and `git log --oneline origin/HEAD..HEAD` — don't suggest pushing if already pushed, don't suggest committing if nothing is staged/modified
- **Run tests**: Confirm the test target exists and the test runner is available
- **Code changes**: Confirm the file/function still exists and hasn't been changed by a concurrent agent
- **Cleanup**: Confirm the dead code / unused import is actually still there

Drop suggestions that fail verification. A stale or impossible suggestion wastes more attention than omitting it. If a suggestion is borderline (e.g., "bench.py might need updating" but you haven't checked), either verify it or drop it — don't surface uncertain claims as actionable items.

### Phase 6: Probabilistic Action Suggestions

For each verified action, estimate probability user wants it:

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

## Output and Interaction

### Phase output (text)

Print verification results and a brief summary of findings as text:

```markdown
## Verification

✅ All session work verified on disk

- src/feature/ (3 files modified)
- config/settings.yaml (new validation added)

## Summary

Found 3 immediate actions, 4 likely followups, 2 optional items.
```

### Action selection (AskUserQuestion)

Use the `AskUserQuestion` tool to present followup actions as multi-select
questions grouped by priority/topic. The user can select multiple items and
add freeform input via the built-in "Other" option.

**Grouping strategy**: Group by logical topic (e.g., "Git", "Code quality",
"Documentation") rather than by priority level. Include the priority indicator
in the option description. Limit to 1-4 questions with 2-4 options each —
combine or drop low-value items to fit the constraints.

**Example** (2 questions covering 7 followups):

```
Question 1: "Which git/commit actions?" (multiSelect: true, header: "Git")
  - "Push 2 commits to devel" (description: "🔴 fe4942f, 80bbc8b — docs updates")
  - "Discard image_pins.json formatting" (description: "🟡 git checkout devinfra/image_pins.json")
  - "Commit MODULE.bazel changes" (description: "🟡 Unrelated modification, needs review")

Question 2: "Which code/docs followups?" (multiSelect: true, header: "Followups")
  - "Run test suite" (description: "🟡 bb-remote test //... --config=rbe")
  - "Remove dead helper functions" (description: "🟢 3 unused functions in auth.py, utils.py")
  - "Update API docs" (description: "🟢 New endpoints need OpenAPI specs")
  - "Add performance benchmarks" (description: "🔵 Optional — new code paths")
```

The user selects items to execute, can add freeform via "Other", and the agent
proceeds with the selected actions.

**Priority indicators in descriptions:**

- 🔴 = DO NOW (>80% probability)
- 🟡 = LIKELY (40-80%)
- 🟢 = MAYBE (20-40%)
- 🔵 = OPTIONAL (10-20%)

**If AskUserQuestion is not available** (e.g., non-interactive mode), fall back
to printing the full list as markdown with the priority groupings and let the
user respond in freeform text.

## Implementation Requirements

### 1. Consider Delegation

Delegate read-only tasks (verification, code search, git status) to subagents
when there are multiple independent checks. Spawn in parallel when possible.

### 2. Concrete Commands

Every suggestion includes the exact command in the description:

- ✅ `git push origin devel`
- ✅ `bb-remote test //path/to:target`
- ❌ "consider committing changes"

### 3. Probability Calibration

- 90%: User explicitly said "do this next"
- 70%: Standard workflow step (commit after edits)
- 50%: Natural followup (tests after code change)
- 30%: Improvement opportunity (refactor similar code)
- 15%: Nice-to-have (documentation polish)
- <10%: Omit entirely

### 4. AskUserQuestion Constraints

- 1-4 questions, 2-4 options each (hard API limit)
- Group by topic, not priority — priority goes in description text
- Use `multiSelect: true` on all questions (user picks what they want)
- Keep option labels short (1-5 words), put details in description
- "Other" is always available — user can add freeform items
- If >16 items total, combine related items or drop lowest-probability ones

### 5. Zero False Omissions

Better to show 5 low-probability items than miss the one action user wanted.
Err on side of over-suggesting rather than under-suggesting.
