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

### 3. Issue Organization: Logical Problems, Not Locations

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

### 4. Objectivity in Issue Descriptions

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

### 5. Research First: No Open Questions

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

### 6. Verifiable External References

**When referencing specific tools, APIs, or implementation details, provide verifiable links. Well-known frameworks/standards don't need URLs.**

**DO need URLs:**
- Specific tools/packages: npm packages, PyPI packages, CLI tools
- APIs and library methods: Specific API endpoints, method documentation
- Commit references: Full 40-character SHAs or GitHub/GitLab permalinks

**DON'T need URLs:**
- Common frameworks: React, Vue, Angular, Tailwind CSS
- Standard libraries: Python stdlib, Node.js core modules
- Well-known tools: pytest, Jest, Docker, PostgreSQL

### 7. Code Citation Guidelines

**IMPORTANT**: Do NOT include long code blocks in rationale. Readers have snapshot code open - cite file paths and line ranges, briefly summarize what's there.

- Brief summary: "Button styles duplicated across 6 components (AgentsSidebar lines 355-360, GlobalApprovalsList lines 118-146, etc.)"
- Short example (3-5 lines) when illustrating pattern
- Avoid long blocks (10+ lines) copied from source
- Assume reader can look up exact code at cited lines

@quality-checklist.md

## Why This Structure?

1. **DRY**: One authoritative description per issue (in Jsonnet)
2. **Tooling-friendly**: Jsonnet is machine-readable for analysis tools
3. **Human-friendly**: Jsonnet provides full detail in a structured format
4. **Maintainable**: Updates happen in one place only
5. **Composable**: Tools can combine/aggregate issues from multiple snapshots
