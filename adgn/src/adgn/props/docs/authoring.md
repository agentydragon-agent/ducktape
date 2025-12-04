# Instructions for Authoring Snapshot Issue Files

## File Structure

```
specimens/
  snapshots.yaml                  # All snapshots defined here
  lib.libsonnet                   # Jsonnet helpers
  ducktape/
    2025-11-26-00/
      dead-code.libsonnet         # Issues directly in snapshot dir
      missing-types.libsonnet
      fp-intentional-duplication.libsonnet  # FPs mixed with TPs
```

**Naming convention:** Issue files use descriptive slugs (lowercase with hyphens), not numerical indices. Slugs should be short (0-30 characters) and convey the issue type. Examples: `dead-code.libsonnet`, `missing-error-handling.libsonnet`, `duplicate-logic.libsonnet`.

## Critical: Snapshots are Frozen Code States

**Snapshots are training/evaluation data representing code quality issues at a specific commit.**

- Each snapshot is pinned to a specific commit (see `snapshots.yaml` source field)
- Issue files (`.libsonnet`) describe what was **wrong at that commit**
- **NEVER** update issue files to record resolution status or mark issues "COMPLETED"
- Issue files should remain accurate descriptions of problems as they existed
- Fixes happen on separate branches; snapshots remain unchanged historical records
- Think of snapshots like labeled training data: the label describes the frozen state

**Example violations:**
- Adding "Status: COMPLETED" or "Note: This was fixed in commit X"
- Updating rationale to say "This issue has been resolved"
- Removing or modifying issue descriptions after fixes are made

**Correct approach:**
- Record issues as they exist at the snapshot commit
- Fix issues on separate branches without modifying snapshot files
- Create new snapshots for new commits if you want to capture improvements

## Authoring Rules

### 1. Single Source of Truth: Jsonnet Files

**All detailed issue information belongs in `*.libsonnet` files only.**

Each `.libsonnet` file contains:
- **Rationale**: Full explanation of what's wrong and why
- **File locations**: Exact paths and line ranges
- **expect_caught_from** (TPs): Files required to catch the issue
- **relevant_files** (FPs): Files that make the FP relevant

**Do NOT duplicate this information in README.md or other files.**

### 2. Issue File Templates

**True Positive (issue that should be caught):**
```jsonnet
local I = import 'lib.libsonnet';

I.issue(
  rationale='Dead code should be removed',
  filesToRanges={'src/cli.py': [[145, 167]]},
  // expect_caught_from auto-inferred for single-file issues
)
```

**Multi-file issue (requires explicit expect_caught_from):**
```jsonnet
local I = import 'lib.libsonnet';

I.issue(
  rationale='Duplicated enum definitions',
  filesToRanges={
    'src/types.py': [[6, 10]],
    'src/persist.py': [[54, 58]],
  },
  expect_caught_from=[
    ['src/types.py'],      // Catch from either
    ['src/persist.py'],
  ],
)
```

**Multiple occurrences:**
```jsonnet
local I = import 'lib.libsonnet';

I.issueMulti(
  rationale='Imperative list building should use comprehensions',
  occurrences=[
    {
      files: {'src/agents.py': [[50, 59]]},
      note: 'In _convert_pending_approvals()',
      expect_caught_from: [['src/agents.py']],
    },
    {
      files: {'src/bridge.py': [[64, 108]]},
      note: 'In list_approvals()',
      expect_caught_from: [['src/bridge.py']],
    },
  ],
)
```

**False Positive:**
```jsonnet
local I = import 'lib.libsonnet';

I.falsePositive(
  rationale='Intentional duplication for visual consistency',
  filesToRanges={
    'src/Button.svelte': [[45, 60]],
    'src/Link.svelte': [[32, 47]],
  },
  // relevant_files auto-inferred from filesToRanges keys
)
```

### 3. Detection Standard for `expect_caught_from`

**The key question:** "If I gave a high-quality critic this file set to review, and they failed to find this issue, would that be a failure on their part?"

**What "reviewing a file" includes:**
- Reading the file thoroughly line by line
- Following imports and calls to check APIs
- Searching the codebase for existing helpers/patterns
- Looking for duplication or similar patterns
- All normal thorough code review activities

**What it does NOT mean:**
- "Can you detect this reading ONLY these files in complete isolation?"
- "Without following any imports or doing any searches?"

**Examples:**

**Example 1: Test creating `Compositor("comp")` directly**
- File: `test_notifications.py` with `comp = Compositor("comp")`
- Question: "Should this use a pytest fixture?"
- Expected action: Critic searches for existing fixtures and patterns
- Result: Finds 12 other instances, flags duplication
- `expect_caught_from: [['test_notifications.py']]` ✓

**Example 2: Wrapper calling implementation with silent fallback**
- Files: `cli.py` (wrapper) and `local_tools.py` (implementation with fallback logic)
- From `cli.py` alone: See wrapper name, but not fallback behavior
- From `local_tools.py` alone: See the silent fallback directly
- Result: Only detectable from implementation file
- `expect_caught_from: [['local_tools.py']]` ✓

**Example 3: Unused CLI flag**
- File: `cli.py` defines `--ui-port` flag with logs saying "Management UI available"
- Question: "Does this flag actually work?"
- Expected action: Critic traces code to verify the flag is properly wired up
- Result: Discovers server serves only stubs, flag misleads users
- `expect_caught_from: [['cli.py']]` ✓

**Example 4: Cross-file duplication of enum definitions**
- Files: `types.py` and `persist.py` both define same enum
- From either file alone: Cannot detect duplication (only see one instance)
- Need both files: See duplicate definitions
- `expect_caught_from: [['types.py', 'persist.py']]` ✓ (AND logic)

**General principle: Include problem code, not reference/solution code**

When an issue is about "absence of use" or "should use existing X":
- **Include:** Code that needs to change (the violators/problems)
- **Don't include:** Code that's already correct and just needs to be used/referenced

Examples:
- Tests not using fixtures → Include test files, not conftest
- Code not using helper function → Include duplicated code, not the helper module
- Code not using base class → Include implementations, not the base class
- Code duplicating utility logic → Include duplicators, not the utility module
- Code reinventing stdlib feature → Include reinvention, not stdlib
- Code with hardcoded values → Include literals, not the constants file
- Code not following pattern → Include non-conforming code, not the exemplar
- Code not calling cleanup → Include leaky code, not the cleanup util

**Exceptions - include the "solution" file when:**
- It itself has a problem (broken/misleading API, incomplete implementation, missing docs)
- The issue is about improving the solution, not just using it
- **Internal contradiction:** File's docstring/comments promise something the code doesn't deliver
  - Example: `server.py` docstring says "provides Management UI" but code only has stubs
  - The file IS the problem (broken promise), not just "unused affordance"
  - Contrast with: Tests not using `server.py` fixture → fixture is fine, tests are the problem

### 4. Issue Organization: Logical Problems, Not Locations

**CRITICAL PRINCIPLE: Group by LOGICAL ISSUE, not by location.**

Each issue file should describe ONE logical problem type, which may occur in multiple locations:

**CORRECT - One logical issue:**
- "Trivial alias functions that should be inlined" -> lists 5 occurrences across different files
- "Imports not at top of file" -> lists 8 occurrences in different components
- "Dead code that should be removed" -> lists all unused functions

**WRONG - One location:**
- "Problems in ServersPanel.svelte" -> mixing thin wrappers + manual parsing + duplicate styles
- "Issues in app.py lines 100-200" -> mixing type annotations + dead code + useless comments

**Issue organization rules:**
1. **One logical problem** = one issue file (may have N occurrences)
2. **Multiple problems in one location** = separate issue files (one per problem type)
3. **Same problem across locations** = single issue with multiple occurrences
4. **Different problems** = separate issues even if in adjacent lines

### 5. Objectivity in Issue Descriptions

**Avoid subjective phrasing** - describe problems objectively:

**Wrong:**
- "User mentioned 'pretty mechanism for parsing Pydantic models'"
- "This is a nice pattern"
- "Would be better to..."

**Correct:**
- "Manual `isinstance()` validation instead of Pydantic `TypeAdapter`"
- "This pattern duplicates validation logic"
- "Use `TypeAdapter` for automatic validation"

Present facts and technical rationale, not opinions or attributed suggestions.

### 6. Research First: No Open Questions

**Snapshots must not leave open research questions.** All investigation should be completed before authoring the issue.

**WRONG - Leaving research questions open:**
```jsonnet
rationale=|||
  Lines 700-704 manually discover the git directory. Check if `pygit2.Repository()`
  can discover automatically.

  **Investigation needed:** Check if either of these works...
|||
```

**CORRECT - Research completed, findings documented:**
```jsonnet
rationale=|||
  Lines 700-704 manually discover the git directory using `pygit2.discover_repository()`.
  Per pygit2 docs, `Repository()` accepts a path and auto-discovers the .git directory,
  making manual discovery unnecessary.
|||
```

### 7. Verifiable External References

**When referencing specific tools, APIs, or implementation details, provide verifiable links. Well-known frameworks/standards don't need URLs.**

**DO need URLs:**
- Specific tools/packages: npm packages, PyPI packages, CLI tools
- APIs and library methods: Specific API endpoints, method documentation
- Commit references: Full 40-character SHAs or GitHub/GitLab permalinks

**DON'T need URLs:**
- Common frameworks: React, Vue, Angular, Tailwind CSS
- Standard libraries: Python stdlib, Node.js core modules
- Well-known tools: pytest, Jest, Docker, PostgreSQL

### 8. Code Citation Guidelines

**IMPORTANT**: Do NOT include long code blocks in rationale. Readers have snapshot code open - cite file paths and line ranges, briefly summarize what's there.

- Brief summary: "Button styles duplicated across 6 components (AgentsSidebar lines 355-360, GlobalApprovalsList lines 118-146, etc.)"
- Short example (3-5 lines) when illustrating pattern
- Avoid long blocks (10+ lines) copied from source
- Assume reader can look up exact code at cited lines

**Per-range context:** Currently, notes are only supported at the occurrence level. Use Jsonnet comments for per-range context:
```jsonnet
filesToRanges={
  'file.py': [
    [10, 20],  // definition site
    [30, 40],  // call site
  ],
}
```
Note: These comments help human readers but aren't parsed into the data model.

TODO: Add support for structured per-range notes in both Jsonnet and Pydantic schemas.

@quality-checklist.md

## Why This Structure?

1. **DRY**: One authoritative description per issue (in Jsonnet)
2. **Tooling-friendly**: Jsonnet is machine-readable for analysis tools
3. **Human-friendly**: Jsonnet provides full detail in a structured format
4. **Maintainable**: Updates happen in one place only
5. **Composable**: Tools can combine/aggregate issues from multiple snapshots
