# Instructions for Authoring Specimen Files

## File Structure

```
specimen-name/
├── manifest.yaml       # VCS source, commit ref, scope (include patterns)
├── README.md          # Brief overview with issue list (no detailed descriptions)
├── CLAUDE.md          # This file - authoring instructions
└── issues/
    ├── 001.libsonnet  # Detailed issue with rationale, locations
    ├── 002.libsonnet
    └── ...
```

## Critical: Specimens are Frozen Snapshots

**Specimens are training/evaluation data representing code quality issues at a specific commit.**

- Each specimen is pinned to a specific commit (see `manifest.yaml` `ref` field)
- Issue files (`.libsonnet`) describe what was **wrong at that commit**
- **NEVER** update issue files to record resolution status or mark issues "COMPLETED"
- Issue files should remain accurate descriptions of problems as they existed
- Fixes happen on separate branches; specimens remain unchanged historical records
- Think of specimens like labeled training data: the label describes the frozen state

**Example violations:**
- ❌ Adding "Status: COMPLETED" or "Note: This was fixed in commit X"
- ❌ Updating rationale to say "This issue has been resolved"
- ❌ Removing or modifying issue descriptions after fixes are made

**Correct approach:**
- ✅ Record issues as they exist at the snapshot commit
- ✅ Fix issues on separate branches without modifying specimen files
- ✅ Create new specimens for new commits if you want to capture improvements

## Authoring Rules

### 1. Single Source of Truth: Jsonnet Files

**All detailed issue information belongs in `issues/*.libsonnet` files only.**

Each `.libsonnet` file contains:
- **Rationale**: Full explanation of what's wrong and why
- **File locations**: Exact paths and line ranges
- **Comments**: Inline comments at line ranges explaining context

**Do NOT duplicate this information in README.md or other files.**

### 2. README.md: Cross-Cutting Information Only

**Specimens should NOT have READMEs that restate/summarize issues.**

If a README exists, it should ONLY contain:
- **Cross-cutting context** not present in individual issue files
- **Scope/inclusion criteria**: What code was analyzed, what was excluded
- **Patterns across issues**: High-level themes linking multiple issues
- **Specimen-specific setup**: Special tags, branches, or analysis methods
- **Reference line**: "See `issues/*.libsonnet` for issue details."

**Do NOT include**:
- Issue list with one-line summaries (redundant with issue files)
- Full rationale or problem explanations (belongs in libsonnet)
- Code snippets or examples (belongs in libsonnet)
- "Correct behavior" sections (belongs in libsonnet)
- Detailed analysis (belongs in libsonnet)

**When to have NO README:**
- If specimen has no cross-cutting context, skip README entirely
- Issue files are the documentation - README adds no value

**Example of useful README content:**
```markdown
# Specimen: post-refactor-analysis

Analyzed after refactoring MCP compositor to 2-level architecture.
Focuses on inconsistencies between new architecture and legacy code.

Scope: `adgn/src/adgn/agent/` and `adgn/src/adgn/mcp/` only.
Excluded: third-party integrations (not yet migrated).

See `issues/*.libsonnet` for issue details.
```

### 3. Issue Organization: Logical Problems, Not Locations

**CRITICAL PRINCIPLE: Group by LOGICAL ISSUE, not by location.**

Each issue file should describe ONE logical problem type, which may occur in multiple locations:

**✅ CORRECT - One logical issue:**
- "Trivial alias functions that should be inlined" → lists 5 occurrences across different files
- "Imports not at top of file" → lists 8 occurrences in different components
- "Dead code that should be removed" → lists all unused functions
- "Manual JSON parsing without validation" → lists all `JSON.parse()` without schema checks

**❌ WRONG - One location:**
- "Problems in ServersPanel.svelte" → mixing thin wrappers + manual parsing + duplicate styles
- "Issues in app.py lines 100-200" → mixing type annotations + dead code + useless comments

**Issue organization rules:**
1. **One logical problem** = one issue file (may have N occurrences)
2. **Multiple problems in one location** = separate issue files (one per problem type)
3. **Same problem across locations** = single issue with multiple occurrences
4. **Different problems** = separate issues even if in adjacent lines

**Examples of logical problem groupings:**
- Code duplication (same pattern repeated)
- Type safety violations (missing annotations, `as any` casts)
- Dead code (unused imports, unreachable functions)
- Architectural violations (bypassing abstraction layers)
- Missing error handling (swallowed exceptions)
- Useless comments (historical notes, obvious statements)
- Naming violations (inconsistent, misleading names)

**When splitting issues:**
- If a location has 3 problems → create 3 separate issues
- Each issue describes ONE problem type across ALL its occurrences
- Don't create "ServersPanel issues" - create "thin wrapper issues" that happen to include ServersPanel

### 4. Objectivity in Issue Descriptions

**Avoid subjective phrasing** - describe problems objectively:

**❌ Wrong:**
- "User mentioned 'pretty mechanism for parsing Pydantic models'"
- "This is a nice pattern"
- "Would be better to..."

**✅ Correct:**
- "Manual `isinstance()` validation instead of Pydantic `TypeAdapter`"
- "This pattern duplicates validation logic"
- "Use `TypeAdapter` for automatic validation"

Present facts and technical rationale, not opinions or attributed suggestions.

### 5. Research First: No Open Questions

**Specimens must not leave open research questions.** All investigation should be completed before authoring the issue.

**❌ WRONG - Leaving research questions open:**
```jsonnet
rationale=|||
  Lines 700-704 manually discover the git directory. Check if `pygit2.Repository()`
  can discover automatically.

  **Investigation needed:** Check if either of these works:
  - `pygit2.Repository(Path.cwd())` (auto-discovers from current dir)
  - `pygit2.Repository()` (auto-discovers from current dir)

  **If auto-discovery works:** [suggested fix]
  **If auto-discovery doesn't work:** Close this issue as invalid.
|||
```

**✅ CORRECT - Research completed, findings documented:**
```jsonnet
rationale=|||
  Lines 700-704 manually discover the git directory using `pygit2.discover_repository()`.
  Per pygit2 docs, `Repository()` accepts a path and auto-discovers the .git directory,
  making manual discovery unnecessary.

  Replace:
    gitdir = pygit2.discover_repository(Path.cwd())
    if not gitdir: [error handling]
    repo = pygit2.Repository(gitdir)

  With:
    try:
      repo = pygit2.Repository(Path.cwd())
    except pygit2.GitError: [error handling]
|||
```

**Research checklist before authoring:**
- ✅ Check library documentation for existing solutions
- ✅ Verify claims about "better approaches" with concrete evidence
- ✅ Test suggested fixes if uncertain about correctness
- ✅ Remove issues that turn out to be invalid after research

**Example from specimen 2025-11-26-code-quality:**
Issue 039 asks "Check if auto-discovery works" and includes "If auto-discovery doesn't work: Close this issue as invalid." This research should have been completed first - either document that auto-discovery works (with evidence), or don't create the issue.

### 6. Jsonnet Issue File Template

**IMPORTANT**: Do NOT include long code blocks in rationale. Readers have specimen code open - cite file paths and line ranges, briefly summarize what's there. Long code citations bloat issue files unnecessarily.

**Code citation guidelines:**
- ✅ Brief summary: "Button styles duplicated across 6 components (AgentsSidebar lines 355-360, GlobalApprovalsList lines 118-146, etc.)"
- ✅ Short example (3-5 lines) when illustrating pattern: "Pattern: `.btn-primary { background: ...; color: ...; }`"
- ❌ Long blocks (10+ lines) copied from source
- ❌ Multiple large code blocks showing variations
- Assume reader can look up exact code at cited lines

```jsonnet
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale=|||
    Full explanation of the problem.

    Why it's wrong and what the correct approach should be.
    Cite file:line ranges, briefly summarize patterns.

    Do NOT paste long code blocks - reader has specimen open.
    All context and fix recommendations go in rationale.
  |||,
  filesToRanges={
    'path/to/file.py': [
      123,              // Brief context (when needed)
      [200, 210],       // Brief note (when needed)
    ],
    'other/file.py': [
      [45, 50],         // Multiple locations OK
    ],
  },
)
```

### 7. Comments: Use Sparingly

**Ideal: Zero comments.** All information should go in structured fields (`rationale`, `filesToRanges`).

**When to use comments (rare cases):**
- Uncertainty about proper issue categorization
- Historical context on how issue arose (if not suitable for rationale)
- Temporary notes during specimen authoring
- Clarification that doesn't fit structured format

**✅ Acceptable inline comments at line ranges:**
```jsonnet
filesToRanges={
  'foo.py': [
    [86, 89],   // --mcp-config flag parsing
    [92, 93],   // --initial-policy flag
  ],
}
```
Brief labels for code location context only.

**❌ FORBIDDEN - Comments duplicating structured fields:**
```jsonnet
// Problem: Silent fallback without error
// Fix: Remove exists() check or raise error
```
This information belongs in `rationale`, not comments. **Delete such blocks.**

**Rule**: If information can go in a structured field, it MUST go there, not in comments.

## Why This Structure?

1. **DRY**: One authoritative description per issue (in Jsonnet)
2. **Tooling-friendly**: Jsonnet is machine-readable for analysis tools
3. **Human-friendly**: README provides navigation, Jsonnet provides depth
4. **Maintainable**: Updates happen in one place only
5. **Composable**: Tools can combine/aggregate issues from multiple specimens

## When Adding New Issues

1. Create `issues/NNN.libsonnet` with full details
2. Add one-line summary to README.md issue list
3. Commit with message: `feat(props): add issue NNN - brief-title`
4. **DO NOT** copy rationale/analysis into README.md or commit message details
