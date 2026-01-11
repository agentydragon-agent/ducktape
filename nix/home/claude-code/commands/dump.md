---
description: Create a session tombstone capturing work done, open threads, and context for future sessions
---

Capture the current session state as a persistent markdown tombstone document.

## Purpose

**Session continuity** - While Claude Code has session restoration, this provides durable context for:

- Resuming work after restart/closure
- Handoff to future agents
- Historical record of incomplete work
- Critical context that shouldn't be lost

**Different from /followups:**

- /followups: Speculative "what could you do next"
- /dump: "What did we discuss, what's not finished, don't lose these threads"

## Scope

Can be invoked in two modes:

1. **Full session dump** (default): `dump`
   - Captures entire session work and context
   - For "about to close session, save everything" scenarios

2. **Scoped dump**: `dump <specific topic/idea>`
   - Example: `dump the idea about using transducers for function Foo`
   - Captures only that specific discussion/thread
   - Useful for extracting particular ideas from a long session

## Process

### Phase 1: Discover Session Context

**Use the session-logs skill to find and verify the current session:**

```bash
# Find current session file
CURRENT_SESSION=$(~/.claude/skills/session-logs/find-current-session.sh)

# Get session metadata
SESSION_ID=$(tail -1 "$CURRENT_SESSION" | jq -r .sessionId)
```

See: `~/.claude/skills/session-logs/SKILL.md` for complete documentation.

**Gather session facts:**

- Session ID (verified)
- Session file path
- Working directory
- Git branch (if applicable)
- Time range (first and last message timestamps)

### Phase 2: Analyze What Was Done

**Concrete accomplishments:**

- Files created/modified (use git status + session log tool calls)
- Key function names/patterns edited (cite file:line)
- Commands run (from Bash tool calls)
- Tests/builds that passed/failed
- Commits made

**Key references (immutable/reproducible):**

- URLs (docs, issues, PRs)
- Function names with file:line references (e.g., `foo.py:123`)
- Git commit SHAs (full 40 chars)
- Specific patterns/regexes discussed
- Error messages encountered

**Keep references immutable where possible:**

- ✅ `foo.py:123` (line number in snapshot)
- ✅ Commit SHA: `abc123...` (full)
- ✅ URL: `https://example.com/docs#section`
- ❌ "the function we edited" (vague)

### Phase 3: Capture Incomplete Work (CRITICAL)

**This is the highest priority section.** Focus on NOT LOSING anything:

**Scan for actual open threads from conversation:**

- User said "we should..." but it wasn't done
- "Let's do X next" but session ended
- Bugs/issues discovered but not fixed
- Tests that failed and weren't resolved
- Design decisions discussed but not implemented
- TODOs mentioned in conversation
- Questions asked but not fully answered

**From session analysis:**

- Modified files not committed
- Work in progress (WIP) states
- Partial implementations
- Known failing tests/builds

**Distinguish clearly:**

- **Actual discussed followups** (high priority) - things explicitly mentioned
- **Potential next actions** (lower priority, separate section) - logical extensions

### Phase 4: Context for Successor Agents

**What does the next agent need to know?**

- **Local conventions**: Style guides, project patterns (reference via file paths)
- **Project documentation**: Where to find authoritative docs (e.g., `@AGENTS.md`, `@README.md`)
- **Build/test commands**: How to verify work (e.g., `pytest`, `npm test`)
- **Key constraints**: Important decisions or limitations from this session
- **Related context**: Links to other sessions/docs if relevant

**Keep this concise** - point to existing docs rather than repeating them.

### Phase 5: Determine File Location

**Find where similar docs live:**

```bash
# Discover markdown files in current project
fd -e md -t f -d 3 .

# Look for session/tombstone patterns
fd -e md . | grep -iE "(session|tombstone|notes|dump)"
```

**Placement strategy:**

1. If a recent dump file exists with similar scope → update it (don't create duplicates)
2. If project has a `docs/` directory → place there
3. If working on a specific component (e.g., `props/core/`) → place near that component
4. Otherwise → place in project root

**File naming:**

- Short topic summary: `<topic>.md` (e.g., `bundle-refactor.md`, `transducer-idea.md`)
- Keep it brief (2-4 words max, lowercase-with-hyphens)
- No dates in filename unless multiple dumps of same topic
- Update existing file if scope matches

### Phase 6: Generate Document

**Template structure:**

````markdown
# <Title Describing Session Work>

**Session ID:** <uuid>
**Session File:** <path to session.jsonl>
**Date:** <YYYY-MM-DD>
**Working Directory:** <path>
**Git Branch:** <branch name> (if applicable)

## What We Accomplished

<Concrete list of what was done, with file:line references>

### Key Changes

- File: `path/to/file.py`
  - Function `foo()` at line 123: <brief description>
  - Pattern at lines 200-210: <brief description>

### Commands Run

<Notable commands with their outcomes>

### References

- <URL with description>
- <Commit SHA with context>
- <Function name with file:line>

## Incomplete Work / Open Threads

**CRITICAL - What's NOT Done Yet:**

### Actual Discussed Items (High Priority)

<Things explicitly mentioned in conversation that weren't completed>

1. **<Clear description>**
   - Context: <why this matters>
   - State: <what's done, what remains>
   - Next step: <concrete action>

### Potential Next Actions (Lower Priority)

<Logical extensions or speculative improvements>

- <Item 1>
- <Item 2>

## Context for Successor Agents

### Project Conventions

- See: `@AGENTS.md` / `@CLAUDE.md`
- Style: <brief pointer to style guide if relevant>

### Build/Test

```bash
<Commands to verify work>
```
````

### Key Decisions/Constraints

<Important context from this session>

## Related Documentation

- <Link to related files/docs>
- <Link to other session notes if relevant>

## Session Metadata

**Total Messages:** <count from session log>
**Tool Calls:** <count from session log>
**Modified Files:** <list from session log>

````

**Content guidelines:**
- Be concise but complete
- Use bullet points and clear headers
- Cite specific locations (file:line)
- Keep "What We Accomplished" factual
- Prioritize "Incomplete Work" - this is the critical section
- Make "Next Steps" actionable

## Implementation Notes

**Session Analysis:**
- Use session-logs skill to extract:
  - Tool calls (Edit, Write, Bash)
  - User messages (scan for "should", "TODO", "next")
  - Modified files list
  - Timestamps for session duration

**Conversation Mining:**
- Look for incomplete threads:
  - "Let's do X" → was X done?
  - "We should..." → was it completed?
  - "TODO" / "FIXME" in conversation
  - Questions without full answers
  - Failed tests/builds not resolved

**File Updates vs. New Files:**
- If existing dump file found with similar scope:
  - Read existing file
  - Check if scope has drifted significantly
  - If not drifted: update in place (add new section, update metadata)
  - If drifted: create new file
- Update criteria:
  - Same general topic/area of work
  - Recent (within ~1 week)
  - Not too large (< 1000 lines)

**Verification:**
- Session ID must be verified correct (use session-logs skill)
- File paths must be accurate (verify they exist)
- Line numbers should be current (best effort)

## Quick Reference Commands

```bash
# Find current session
~/.claude/skills/session-logs/find-current-session.sh

# Get session ID
tail -1 "$SESSION_FILE" | jq -r .sessionId

# List modified files in session
grep '"type":"tool_use"' "$SESSION_FILE" | \
  jq -r 'select(.message.content[0].name == "Edit" or .message.content[0].name == "Write") |
    .message.content[0].input.file_path' | sort -u

# Session statistics
echo "Total entries: $(wc -l < "$SESSION_FILE")"
echo "Tool uses: $(grep -c '"type":"tool_use"' "$SESSION_FILE")"
echo "User messages: $(grep -c '"type":"user"' "$SESSION_FILE")"
````
