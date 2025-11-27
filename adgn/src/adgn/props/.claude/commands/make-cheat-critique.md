# Make Cheat Critique (Calibration Test)

Generate a paraphrased critique.jsonnet from a specimen's ground truth issues.

**Purpose**: Create a "cheat" critique that should achieve ~100% recall when graded, to verify:
- The grading system can match paraphrased issues correctly
- Coverage scoring works as expected
- The baseline for what "good recall" looks like

**CRITICAL REQUIREMENT**: The cheat critique **MUST** cover **EVERY** canonical issue in the specimen. Missing even one issue invalidates the calibration test.

**Input**: Specimen slug (e.g., `ducktape/2025-11-22-01`)

**Output**: `cheat_critique.jsonnet` (annotated):
- Paraphrased rationales (different wording, style, density)
- Slightly adjusted anchors/line ranges (realistic variation)
- Comments mapping each issue to its ground truth ID
- Valid `CriticSubmitPayload` structure (compiles to JSON)
- The grading CLI accepts `.jsonnet` directly (no manual JSON conversion needed)

**Schema**: Read `CriticSubmitPayload`, `ReportedIssue`, `Occurrence`, and `LineRange` from:
- `src/adgn/props/critic.py`
- `src/adgn/props/models/issue.py`

## Task

You are creating a calibration critique from ground truth to test the grading system.

### Step 1: Load Ground Truth

**Use `specimen-exec` to read the specimen files:**

```bash
adgn-properties2 specimen-exec <specimen-slug> -- ls -la
adgn-properties2 specimen-exec <specimen-slug> -- cat manifest.yaml
adgn-properties2 specimen-exec <specimen-slug> -- find issues -name "*.libsonnet"
adgn-properties2 specimen-exec <specimen-slug> -- cat issues/<issue-file>.libsonnet
```

This runs commands inside the specimen's hydrated workspace (with the actual code checked out).

**Note**: Run these from the `adgn/` directory where direnv is configured.

Parse **ALL** canonical issues in the specimen, noting:
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

### Step 2: Paraphrase Strategy

For each ground truth issue, create a paraphrased version:

**Rationale transformations** (vary across issues):
- **Dense → verbose**: Expand terse descriptions with more context
- **Verbose → terse**: Compress long explanations to key points
- **Technical → plain**: Rephrase jargon in simpler terms (but keep technical accuracy)
- **Passive → active**: Change voice ("X should be avoided" → "Avoid X")
- **Restructure**: Move supporting details before/after main point
- **Add examples**: Include inline code snippets or "e.g., ..." clarifications
- **Remove meta-commentary**: Strip phrases like "we should" or "it's important to"

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

### Step 3: Jsonnet Structure

Write a valid `cheat_critique.jsonnet` file:

**Issue ID Guidelines**: Use realistic, descriptive IDs that a real critic would write:
- Based on the problem type: `exception-handling`, `subprocess-injection`, `pathlib-str-cast`
- Keep them concise but meaningful: 2-4 words, hyphen-separated
- Don't use numbers unless the canonical uses them
- Examples: `unchecked-subprocess-return`, `missing-timeout`, `sql-injection-risk`

```jsonnet
// Cheat critique for calibration: <specimen>
// Generated: <timestamp>
// Ground truth: N canonical issues (EVERY issue must be covered!)
// This critique: M reported issues (may differ if merged/split)
// Paraphrase strategies: X dense→verbose, Y terse, Z restructured
// Grouping: A merges, B splits
// Coverage verification: List all canonical IDs covered below
// Expected: 0.85-1.0 recall if grader handles fuzzy matching well

{
  issues: [
    // ====================================================================
    // Ground truth: canon-tp-001 (broad exception handling)
    // Original rationale: "Broad except blocks hide errors; replace..."
    // Paraphrase: dense → verbose, technical → plain
    // Location: expanded [45,47] → [44,48] to include context
    // ====================================================================
    {
      id: "broad-exception-handling",
      rationale: |||
        The codebase uses overly broad exception handling in several places,
        catching `Exception` or using bare `except:` clauses. This silences
        all errors including programming bugs, making debugging difficult.
        Replace with specific exception types or at minimum log before continuing.
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
    // Ground truth: canon-tp-002 (subprocess shell=True)
    // Original rationale: "Pass argv list instead of shell=True..."
    // Paraphrase: terse, active voice
    // Location: contracted [89,95] → [91,92] to exact problem
    // ====================================================================
    {
      id: "subprocess-shell-injection",
      rationale: "Avoid shell=True in subprocess calls to prevent injection risks. Use argv lists.",
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
    // Ground truth: canon-tp-003 + canon-tp-004 (MERGED)
    // Merged: "pathlib migration" (003) + "os.path usage" (004)
    // Rationale: Both are about Path usage, grouped for efficiency
    // Paraphrase: restructured, added examples
    // ====================================================================
    {
      id: "pathlib-migration",
      rationale: |||
        Use pathlib.Path consistently instead of str and os.path.
        Examples: Path.read_text() instead of open(), path / "subdir"
        instead of os.path.join(). Eliminates str(path) casts.
      |||,
      occurrences: [
        // Covers occurrences from both canon-tp-003 and canon-tp-004
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

### Step 4: Validation

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

### Step 5: Grouping Strategy (Valid Variation)

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

### Step 6: Write Output

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

## Example Paraphrasing

**Original (ground truth)**:
```
ID: canon-tp-001
Rationale: Broad except blocks hide errors; replace with specific exception types or
narrow catches. Avoid except Exception: pass patterns.
Location: src/foo.py lines 45-47
```

**Paraphrased (dense → verbose)**:
```jsonnet
{
  id: "exception-handling-broad",
  rationale: |||
    The codebase uses overly broad exception handling in several places, catching
    `Exception` or using bare `except:` clauses. This silences all errors including
    programming bugs, making debugging difficult. Replace with specific exception
    types (e.g., `ValueError`, `IOError`) or at minimum log before continuing.
  |||,
  occurrences: [
    {
      files: {
        "src/foo.py": [
          { start_line: 44, end_line: 48 }  // Original: [45,47], expanded to show full try block
        ]
      }
    }
  ]
}
```

## Notes

- **COMPLETE COVERAGE IS MANDATORY**: Every canonical issue must appear in your cheat critique. This is non-negotiable for calibration testing.
- **Make it look realistic**: The critique should look like something a real critic would write:
  - Natural issue IDs (descriptive, not prefixed with "cheat" or sequential numbers)
  - Varied styles across issues (mix terse and verbose)
  - Realistic grouping decisions (merge related, split large)
  - Natural variation in line range precision
- **Be creative with paraphrasing**: The goal is to test if the grader can handle realistic variation, not to create exact copies
- **Stay technically accurate**: Don't change the meaning or introduce errors
- **Vary difficulty**: Mix obvious paraphrases with subtle ones
- **Track your work**: Comments should make it easy to verify later which ground truth issue each cheat issue represents
- **Before submitting**: Double-check your header comment lists all canonical IDs

## Example Usage

```bash
# In Claude Code, from the props directory:
/make-cheat-critique ducktape/2025-11-22-01

# Then grade it (from adgn/ directory):
adgn-properties2 specimen-grade ducktape/2025-11-22-01 \
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
- **recall ≥ 0.90**: Excellent! Grader correctly matched paraphrases
- **recall 0.70-0.89**: Good, but some fuzzy matches failed
- **recall < 0.70**: Problem! Either:
  1. **You missed canonical issues** (verify complete coverage first!)
  2. Paraphrasing too aggressive (semantics changed)
  3. Location adjustments broke overlap detection
  4. Grading logic has issues

**If recall is low despite verifying complete coverage**, the grading system may have issues with fuzzy matching.

**Coverage recall vs regular recall**:
- `coverage_recall` uses fractional credits (more accurate for partial matches)
- `recall` uses binary TP counting (more conservative)
- Expect `coverage_recall ≥ recall` in most cases
