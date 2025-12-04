# Make Cheat Critique (Calibration Test)

Generate a **new, independent critique** of the specimen code as if written by a **different, equally competent reviewer**.

**Purpose**: Create a "cheat" critique that should achieve ~100% recall when graded, to verify:
- The grading system can recognize the **same problems described differently**
- A different reviewer's style/grouping/naming doesn't harm recall
- Coverage scoring works with realistic variation
- The baseline for what "good recall" looks like

**Core Concept**: You're simulating what would happen if you gave the same code to a **different human reviewer** who:
- Finds all the same real problems (100% coverage)
- BUT describes them in their own words
- AND groups/names issues differently
- AND has their own style and priorities

**CRITICAL REQUIREMENT**: The cheat critique **MUST** identify **EVERY logical problem** the canonical covers (same code issues, same actual defects), but can (and should) look very different in how it presents them (grouping, naming, description style).

**Input**: Specimen slug (e.g., `ducktape/2025-11-22-01`)

**Output**: `cheat_critique.jsonnet` (annotated):
- **Different reviewer's voice**: Varied wording, style, technical depth, priorities
- **Independent issue naming**: Fresh IDs that this reviewer would choose
- **Alternative grouping**: Merge/split issues differently than canonical
- **Realistic variation**: Adjusted anchors/ranges, different emphasis
- Comments mapping each issue to its ground truth ID (for verification)
- Valid `CriticSubmitPayload` structure (compiles to JSON)
- The grading CLI accepts `.jsonnet` directly (no manual JSON conversion needed)

**Schema**: Read `CriticSubmitPayload`, `ReportedIssue`, `Occurrence`, and `LineRange` from:
- `src/adgn/props/critic.py`
- `src/adgn/props/models/issue.py`

## Task

You are **role-playing as a different code reviewer** who is analyzing the same specimen code independently. Your job is to:

1. **Find all the same problems** the canonical reviewer found (same logical defects)
2. **Describe them in your own way** - different words, different framing, different grouping
3. **Write issues as YOU would naturally write them** - your IDs, your style, your priorities

This tests whether the grading system can recognize when **two reviewers independently found the same problems** even though they wrote about them differently.

### Step 1: Load Ground Truth

**Issue definitions are in the repository, not in snapshot exec:**

The canonical issue files (`.libsonnet`) and manifest are stored in the repository at:
- `src/adgn/props/specimens/<specimen-slug>/manifest.yaml`
- `src/adgn/props/specimens/<specimen-slug>/issues/*.libsonnet`

```bash
# From adgn/ directory:
# Count canonical issues
find src/adgn/props/specimens/<specimen-slug>/issues -name "*.libsonnet" | wc -l

# Read manifest
cat src/adgn/props/specimens/<specimen-slug>/manifest.yaml

# Read a specific issue
cat src/adgn/props/specimens/<specimen-slug>/issues/<issue-name>.libsonnet
```

**Use `snapshot exec` ONLY to verify the actual source code** being reviewed (not to read issue definitions):

```bash
# List source files in the hydrated specimen workspace
adgn-properties snapshot exec <specimen-slug> -- find . -name "*.py" -o -name "*.ts"

# Read specific source file lines to verify issue anchors
adgn-properties snapshot exec <specimen-slug> -- sed -n '10,20p' path/to/file.py
```

**Note**: Run these from the `adgn/` directory where direnv is configured.

Parse **ALL** canonical issues in the specimen (from the repository), noting:
- Issue IDs (from filenames: `issues/iss-001.libsonnet` → `iss-001`)
- Rationales (original phrasing from jsonnet files)
- File paths and line ranges (relative paths from repo root)
- Occurrence structures (one issue can have multiple occurrences)
- The actual specimen code (to verify line ranges are plausible)

**Count the total number of canonical issues** - your cheat critique must cover all of them, but the count of reported issues may differ due to merges/splits (document these changes).

**Important grading semantics**:
- Grader uses **fuzzy LLM-based matching** (not exact string comparison)
- One reported issue can match **multiple canonical issues** (coverage)
- Multiple reported issues can overlap the **same canonical** (only counted once)
- **Coverage credits**: Grader assigns fractional credit (0-1) per canonical
  - 1.0 = fully covered, 0.5 = half covered, etc.
  - Recall = average of per-canonical credits

### Step 2: Verify All Files and Anchors

**CRITICAL**: Before paraphrasing any issue, verify that all referenced files and line ranges actually exist in the specimen:

```bash
# List all Python files to confirm structure
adgn-properties snapshot exec <specimen-slug> -- find . -name "*.py" -o -name "*.ts" -o -name "*.tsx"

# For each file referenced in a canonical issue, verify it exists
adgn-properties snapshot exec <specimen-slug> -- ls -l path/to/file.py

# For each line range, verify the lines exist and match what the issue describes
adgn-properties snapshot exec <specimen-slug> -- sed -n '10,20p' path/to/file.py
```

**DO NOT**:
- ❌ Adjust file paths when paraphrasing (keep exact paths from canonical)
- ❌ Reference line ranges without verifying them via snapshot exec
- ❌ Invent new files that don't exist in the specimen
- ❌ Create paraphrased anchors pointing to non-existent code

**DO**:
- ✅ Use exact file paths from canonical issues (they are always correct)
- ✅ Use `snapshot exec` with sed/cat to read the actual code at line ranges before adjusting them
- ✅ Verify adjusted line ranges still point to valid code
- ✅ When adjusting ranges (expanding/contracting), check the new range exists via snapshot exec

**Example workflow for one issue**:
```bash
# Canonical says: "adgn/src/adgn/agent/mcp_bridge/servers/agents.py lines 50-59"

# Step 1: Read the canonical's code at original range
adgn-properties snapshot exec ducktape/2025-11-22-01 -- sed -n '50,59p' adgn/src/adgn/agent/mcp_bridge/servers/agents.py

# Step 2: If paraphrasing strategy is "expand range", verify expanded range exists
adgn-properties snapshot exec ducktape/2025-11-22-01 -- sed -n '48,61p' adgn/src/adgn/agent/mcp_bridge/servers/agents.py

# Step 3: Read the code to understand context for rationale paraphrasing
adgn-properties snapshot exec ducktape/2025-11-22-01 -- sed -n '45,65p' adgn/src/adgn/agent/mcp_bridge/servers/agents.py
```

**This verification step is mandatory for calibration validity** - a cheat critique that references non-existent files or invalid line ranges will fail grading and invalidate the test.

### Step 3: Alternative Reviewer Strategy

For each ground truth issue (after verifying files exist), write how a **different reviewer** would describe it:

**Think like a different reviewer** - not just rephrasing, but genuinely different perspective:
- **What would THEY notice first?** Lead with impact vs. technical detail vs. pattern
- **What language would THEY use?** Academic vs. practical vs. terse vs. conversational
- **What would THEY emphasize?** Maintainability vs. correctness vs. performance vs. readability
- **How would THEY explain it?** Examples-first vs. principle-first vs. consequences-first

**Rationale variation strategies** (vary across issues):
- **Dense → verbose**: Expand terse descriptions with context, examples, impact
- **Verbose → terse**: Compress to just the essential problem statement
- **Technical → practical**: "Violates SRP" → "Makes changes risky when requirements evolve"
- **Practical → technical**: "Hard to test" → "Tight coupling prevents dependency injection"
- **Abstract → concrete**: "Poor separation" → "Business logic mixed with HTTP handling in line 45"
- **Concrete → abstract**: "Lines 10-20 duplicate 50-60" → "Extraction opportunity for common validation pattern"
- **Problem-focused**: "This causes X" (emphasize what's wrong)
- **Solution-focused**: "Replace with Y" (emphasize the fix)

**Location adjustments** (realistic variations):
- **Expand ranges**: Widen line ranges by 1-3 lines to include context (e.g., `[10,12]` → `[9,14]`)
- **Contract ranges**: Narrow to the exact problem line (e.g., `[50,60]` → `[55,56]`)
- **Shift slightly**: Move anchor up/down by 1-2 lines if the issue spans multiple statements
- **Split occurrences**: If one ground truth occurrence spans 20+ lines, split into 2 smaller ranges
- **Merge occurrences**: If ground truth has 3 adjacent occurrences in same file, merge into one broader range

**Style variations** (pick 2-3 per issue):
- Bullet points → prose paragraph
- Code example → description of the pattern
- "Why it matters" → "Impact"
- Imperative ("Use X") → Declarative ("X is preferred")
- Add/remove specific tool mentions (e.g., "mypy reports..." → "type checker flags...")

### Step 4: Jsonnet Structure

Write a valid `cheat_critique.jsonnet` file:

**Issue ID Guidelines**: Choose IDs that **THIS reviewer** would naturally write (not based on canonical IDs):
- Name what THIS reviewer sees: their framing of the problem
- Canonical: `duplicate-mount-logic` → Cheat might use: `redundant-compositor-setup` or `mounting-duplication`
- Canonical: `imperative-list-building` → Cheat might use: `list-comprehension-opportunities` or `loop-append-pattern`
- Keep them concise but meaningful: 2-4 words, hyphen-separated
- Don't mirror canonical ID structure - be independent
- Examples: `exception-swallowing`, `shell-injection-risk`, `type-annotation-gaps`, `test-case-bundling`

```jsonnet
// Cheat critique for calibration: <specimen>
// Generated: <timestamp>
// Canonical issues: N (ALL logical problems must be identified!)
// This review: M reported issues (different grouping/framing)
// Reviewer style: [terse/verbose/technical/practical/impact-focused/etc.]
// Variation applied: X merged, Y split, Z reframed
// Coverage map: List all canonical IDs → reported IDs below
// Expected: 0.90-1.0 recall (tests if grader recognizes same problems described differently)

{
  issues: [
    // ====================================================================
    // Canonical: canon-tp-001 (broad exception handling)
    // This reviewer's take: Focus on debugging impact, use their preferred term
    // Style: verbose, impact-focused, practical consequences
    // Location: expanded [45,47] → [44,48] to show try block
    // ====================================================================
    {
      id: "exception-swallowing",  // Different reviewer might call it "swallowing" not "broad"
      rationale: |||
        Multiple functions catch broad exception types (Exception or bare except),
        which silences programming errors and makes debugging extremely difficult.
        When these catch legitimate bugs, the only symptom is silent failure or
        incorrect behavior far from the actual error site. Narrow to specific
        exception types (ValueError, IOError, etc.) or add logging before continue.
      |||,
      occurrences: [
        {
          files: {
            "src/foo.py": [
              { start_line: 44, end_line: 48 }  // Original: [45,47]
            ]
          },
          note: null
        },
        {
          files: {
            "src/bar.py": [
              { start_line: 102, end_line: 105 }  // Original: [103,104]
            ]
          }
        }
      ]
    },

    // ====================================================================
    // Canonical: canon-tp-002 (subprocess shell=True security)
    // This reviewer's take: Lead with security risk, terse style
    // Style: security-focused, direct, assumes reader knows the vulnerability
    // Location: contracted [89,95] → [91,92] to just the call
    // ====================================================================
    {
      id: "shell-injection-risk",  // Security-focused reviewer names by the threat
      rationale: "subprocess.run with shell=True enables shell injection. Pass command as list.",
      occurrences: [
        {
          files: {
            "src/runner.py": [
              { start_line: 91, end_line: 92 }  // Original: [89,95]
            ]
          }
        }
      ]
    },

    // ====================================================================
    // Canonical: canon-tp-003 + canon-tp-004 (MERGED by this reviewer)
    // This reviewer groups: "str(path) casts" + "os.path usage" → single modernization issue
    // Rationale: Different reviewer sees these as one pattern (inconsistent Path usage)
    // Style: examples-driven, practical, shows the better way
    // ====================================================================
    {
      id: "inconsistent-path-handling",  // This reviewer frames as consistency issue
      rationale: |||
        Path handling mixes pathlib, os.path, and str conversions inconsistently.
        Examples: str(path) casts nullify pathlib benefits, os.path.join when
        path / "subdir" works, open() when path.read_text() is cleaner.
        Standardize on pathlib throughout for better type safety and readability.
      |||,
      occurrences: [
        // This reviewer naturally groups related Path issues together
        {
          files: {
            "src/utils.py": [
              { start_line: 20, end_line: 23 },
              { start_line: 67, end_line: 69 }
            ]
          }
        },
        {
          files: {
            "src/config.py": [
              { start_line: 15 }  // end_line optional for single-line
            ]
          }
        }
      ]
    }

    // ... continue for remaining issues
  ]
}
```

**Key points**:
- Use `|||` for multi-line rationales (jsonnet syntax)
- File paths must be **relative** to repo root (not absolute)
- Comment each issue with ground truth mapping and paraphrase strategy

### Step 5: Validation

Before finalizing:
- **COMPLETE COVERAGE** (CRITICAL): Have you included **EVERY** canonical issue from the specimen?
  - Count canonical issues: `find issues -name "*.libsonnet" | wc -l`
  - Verify each canonical ID appears in your comments
  - Your reported issue count may be different (merges/splits are valid!)
  - If you merged issues, document which canonical IDs are covered by which reported issue ID
  - If you split issues, document which canonical ID was split into which reported issue IDs
  - **Missing even one canonical issue fails the calibration test**
  - **Having a different number of reported issues is OK** as long as coverage is complete
- **Jsonnet compilation**: Does the file compile without errors?
  ```bash
  # From adgn/ directory:
  jsonnet src/adgn/props/specimens/<specimen>/cheat_critique.jsonnet | jq . > /dev/null
  ```
- **Occurrence coverage**: Are all canonical occurrences covered by at least one reported issue occurrence?
  - Note: One reported issue can cover MULTIPLE canonical issues
  - Note: Multiple reported issues can overlap the SAME canonical (it's only counted once)
  - The grader matches via semantic similarity + file/line overlap (fuzzy)
- **Schema**: Does the structure match `CriticSubmitPayload`?
- **Paths**: Are all file paths relative (not absolute) and valid?
- **Ranges**: Are line ranges plausible (within file bounds, start ≤ end)?

### Step 6: Grouping Strategy (Valid Variation)

Since the grader handles flexible mappings, you can and should vary the grouping:
- **Merge related canonicals**: Combine 2-3 similar canonical issues into one reported issue
  - Example: Merge "broad except" + "swallowed exceptions" into one "exception handling" issue
  - Comment which canonicals are merged (e.g., "// Covers: iss-001, iss-003")
  - This is a **valid real-world pattern** - critics often group related issues
- **Split large canonicals**: Break one canonical with many occurrences into 2-3 focused issues
  - Example: Split "pathlib migration" into "str(path) casts" + "os.path usage"
  - Comment which canonical is being split (e.g., "// Part 1 of iss-007")
  - This is a **valid real-world pattern** - critics often break down large issues

**The reported issue count will differ from canonical count, and that's expected!** What matters is complete coverage of all canonical issues.

### Step 7: Write Output

Write **one file** in the specimen directory (`src/adgn/props/specimens/<specimen>/`):

**Annotated critique**: `cheat_critique.jsonnet`

Include:
- Valid jsonnet that compiles to `CriticSubmitPayload` schema
- Detailed comments mapping to ground truth IDs
- Comments on paraphrase strategies used per issue
- Comments on location adjustments (expanded/contracted/shifted ranges)
- Comments on any merges/splits

Header comment summarizing:
- Number of ground truth issues in specimen (emphasize: ALL must be covered)
- Number of reported issues in cheat critique (may differ due to merges/splits)
- Paraphrase strategies used (counts: e.g., "5 dense→verbose, 3 terse, 2 restructured")
- Grouping changes (e.g., "2 merges, 1 split")
- **Coverage verification**: List all canonical IDs covered (e.g., "Covers: iss-001, iss-002, iss-003, ...")
- Expected recall range: "0.85-1.0 if grader handles fuzzy matching well"

## Example: Different Reviewer's Perspective

**Canonical (original reviewer)**:
```
ID: broad-exception-handling
Rationale: Broad except blocks hide errors; replace with specific exception types or
narrow catches. Avoid except Exception: pass patterns.
Location: src/foo.py lines 45-47
```

**Cheat critique (different reviewer, multiple valid approaches)**:

**Approach 1 - Impact-focused reviewer** (emphasizes consequences):
```jsonnet
{
  id: "error-hiding",
  rationale: |||
    Bare except clauses and overly broad catches make debugging near-impossible.
    When bugs occur, they're silently swallowed rather than surfacing as exceptions.
    This leads to hours wasted chasing symptoms far from the actual error.
    Use specific exception types or at minimum log before continuing.
  |||,
  occurrences: [{ files: { "src/foo.py": [{ start_line: 45, end_line: 47 }] } }]
}
```

**Approach 2 - Terse security-focused reviewer** (assumes expertise):
```jsonnet
{
  id: "exception-swallowing",
  rationale: "Broad exception handlers mask bugs. Narrow to specific types (ValueError, IOError).",
  occurrences: [{ files: { "src/foo.py": [{ start_line: 45 }] } }]  // Just the except line
}
```

**Approach 3 - Pattern-focused reviewer** (sees it as anti-pattern):
```jsonnet
{
  id: "catch-all-antipattern",
  rationale: |||
    Multiple instances of the catch-all exception anti-pattern. This violates
    error handling best practices by treating all exceptions equally regardless
    of whether they're expected errors (FileNotFoundError) or programming bugs
    (AttributeError). Refactor to catch specific exceptions only.
  |||,
  occurrences: [{ files: { "src/foo.py": [{ start_line: 44, end_line: 48 }] } }]  // Include try line for context
}
```

All three identify the **same logical problem** but frame it differently based on the reviewer's perspective.

## Notes

- **COMPLETE COVERAGE IS MANDATORY**: Every logical problem in the canonical must be identified in your cheat critique. This is non-negotiable for calibration testing.
- **Think like a different reviewer**: Don't just rephrase - reimagine how someone else would see and describe these problems:
  - What lens do they view code through? (security, maintainability, performance, readability)
  - What's their communication style? (academic, practical, terse, detailed)
  - How would they naturally group related issues?
  - What terminology feels natural to them?
- **Issue IDs should be independent**: Don't mirror or modify canonical IDs - choose what THIS reviewer would naturally name things
- **Grouping should differ**: Merge issues differently, split differently - what makes sense to THIS reviewer's mental model
- **Natural variation in precision**: Some reviewers cite broad context, others pinpoint exact lines - be consistent with your chosen style
- **Stay technically accurate**: Different framing, but same actual problems - don't introduce new issues or miss real ones
- **Track your work**: Comments map back to canonicals for verification, but the critique itself should stand alone as a coherent review
- **Before submitting**: Verify every canonical problem is covered (check your coverage map)

## Example Usage

```bash
# In Claude Code, from the props directory:
/make-cheat-critique ducktape/2025-11-22-01

# Then grade it (from adgn/ directory):
adgn-properties snapshot-grade ducktape/2025-11-22-01 \
  --critique src/adgn/props/specimens/ducktape/2025-11-22-01/cheat_critique.jsonnet

# The CLI automatically compiles .jsonnet to JSON before grading

# Expected output:
# {
#   "specimen": "ducktape/2025-11-22-01",
#   "expected": 15,
#   "reported": 14,
#   "true_positives": 14,
#   "false_positive": 0,
#   "unknown": 0,
#   "false_negatives": 1,
#   "precision": 0.95,
#   "recall": 0.93,
#   "coverage_recall": 0.95
# }
```

**Interpreting results**:
- **recall ≥ 0.90**: Excellent! Grader recognizes same problems despite different framing
- **recall 0.70-0.89**: Good, but grader struggled with some variations
- **recall < 0.70**: Problem! Either:
  1. **You missed logical problems** (verify complete coverage first!)
  2. Variation too extreme (changed what the problem actually is)
  3. Line ranges drifted too far from actual problem locations
  4. Grader can't recognize same problem described differently (calibration failure)

**If recall is low despite all problems being covered**, this reveals the grader can't handle realistic reviewer variation - that's what we're testing!

**Coverage recall vs regular recall**:
- `coverage_recall` uses fractional credits (more accurate for partial matches)
- `recall` uses binary TP counting (more conservative)
- Expect `coverage_recall ≥ recall` in most cases
