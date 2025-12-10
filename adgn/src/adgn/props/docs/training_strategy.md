# Training Strategy: Per-File Code Review Examples

## Overview

**Goal:** Train an LLM critic that **behavior-clones my (user's) code review judgment** - finding issues I would find, following my subjective preferences and taste.

**Not a generic code reviewer:** This is about learning MY specific preferences:
- What duplication is acceptable (visual consistency) vs should be refactored
- What naming is clear vs verbose/unclear
- What abstraction level is appropriate vs over/under-engineered
- What comments add value vs are noise
- What patterns are idiomatic vs anti-patterns

**Target performance:** Comprehensively review entire codebases, finding 50-100+ issues across all patterns (duplication, dead code, architecture smells, inconsistency, change-detector tests, etc.) that I would flag.

**Strategy:** Use per-file training examples with ground truth for easier hill-climbing, then evaluate on full-repo review as the terminal metric.

## Dataset Model

### Core Concepts

**Snapshot:** A frozen code state at a specific commit with labeled issues (TPs and FPs)
- Example: `ducktape/2025-11-26-00` → commit `ab7e9d6...`
- Contains: source code bundle + issue files (`.libsonnet`)
- Immutable training data (like ImageNet labels)

**Training Example:** `(snapshot, targeted_files)` pair
- **Input:** Which files should the critic review?
- **Output (computed):** Which TPs are catchable + which FPs are relevant given those files

**True Positive (TP):** A real issue that should be caught
- Has `expect_caught_from`: minimal file sets needed to DETECT the issue
- Example: duplication in A+B → `expect_caught_from: [[A], [B]]` (seeing EITHER file should trigger search)
- Detection standard: "If a competent reviewer sees these files, would they reasonably catch this?"

**False Positive (FP):** Something that looks wrong but isn't (known acceptable pattern)
- Has `relevant_files`: files that make this FP relevant (currently all FPs included in all examples)

### Training Example Generation

**Current (baseline):** 1 example per snapshot
```python
TrainingExample(
    snapshot_slug="ducktape/2025-11-26-00",
    targeted_files=ALL_FILES,  # All files with issues
    true_positives=[...],      # All TPs
    false_positives=[...],     # All FPs
)
```
- 5 training snapshots → 5 training examples
- Current recall: 1-4% (very low!)

**New (per-file):** N examples per snapshot
```python
# Example 1: Review single file
TrainingExample(
    snapshot_slug="ducktape/2025-11-26-00",
    targeted_files={Path("src/server.py")},
    true_positives=[...],  # Only TPs catchable from server.py
    false_positives=[...], # All FPs (not filtered yet)
)

# Example 2: Review cross-cutting concern
TrainingExample(
    snapshot_slug="ducktape/2025-11-26-00",
    targeted_files={Path("src/types.py"), Path("src/persist.py")},
    true_positives=[...],  # TPs needing both files (e.g., duplicated enum)
    false_positives=[...],
)
```
- 5 training snapshots × ~20 examples each → 100+ training examples
- Tighter feedback loop for optimization

### TP Filtering Logic

A TP is "catchable" from `targeted_files` if:
```python
any(
    trigger_set <= targeted_files  # trigger_set is subset of targeted
    for occurrence in tp.occurrences
    for trigger_set in occurrence.expect_caught_from
)
```

**Example:** Duplication across A and B
- `occurrence.expect_caught_from = [[A], [B]]` (OR logic - either file works)
- Catchable from `{A}`: ✅ Yes (`[A] <= {A}`)
- Catchable from `{B}`: ✅ Yes (`[B] <= {B}`)
- Catchable from `{C}`: ❌ No (neither trigger set satisfied)

**Example:** Missing abstraction needing pattern awareness
- `occurrence.expect_caught_from = [[client.py, utils.py]]` (AND logic - need both)
- Catchable from `{client.py}`: ❌ No (incomplete trigger set)
- Catchable from `{client.py, utils.py}`: ✅ Yes
- Catchable from `{client.py, utils.py, other.py}`: ✅ Yes (superset okay)

## Critic Scopes (Training Example Specification)

### Sidecar YAML Format

File: `specimens/critic_scopes.yaml`

```yaml
# Defines which file combinations to use as training examples for each snapshot
# Each entry generates one TrainingExample (snapshot + targeted_files)
# Rationale for groupings documented via comments

ducktape/2025-11-26-00:
  # Server initialization and lifecycle issues
  - files: [src/agent/server.py]

  # Approval hub logic and state management
  - files: [src/agent/approvals.py]

  # Check for duplicated type definitions across layers
  - files: [src/mcp/types.py, src/mcp/persist.py]

  # UI component patterns and style consistency
  - files: [src/agent/web/src/components/*.svelte]

ducktape/2025-11-20-00:
  # ... similar structure
```

**Comments:** Explain why each file combination makes sense (documentation only, not parsed)

**File patterns:** Support globs (`*.py`, `**/*.py`) for convenience, expanded at load time

### Generating Scopes

**Manual curation (initial):**
- For each snapshot, identify natural review boundaries:
  - Individual files with self-contained issues
  - File pairs/groups with cross-cutting concerns (duplication, inconsistent patterns)
  - Component boundaries (e.g., all UI components, all DB layer)

**Heuristics (future):**
- One example per file with issues
- One example per directory with multiple related files
- One example for files sharing common imports/dependencies
- Full snapshot as final example (terminal metric)

**Important:** Always include ONE full-snapshot example per snapshot as the terminal metric

### Default Behavior

If `critic_scopes.yaml` doesn't specify scopes for a snapshot, fall back to:
1. One example per file with issues (naive per-file split)
2. One example with all files (full snapshot)

## Metrics

### Training Metrics (per-file examples)
- **Recall:** TP_found / TP_catchable (given targeted_files)
- **Precision:** TP_found / (TP_found + FP_triggered)
- **F1:** Harmonic mean of recall and precision

### Terminal Metric (full snapshot)
- **Full-repo recall:** How well does the critic perform when targeting ALL files?
- This is the real-world scenario: "review this entire codebase"
- Per-file examples are for easier hill-climbing, not the end goal

## Optimization Strategy

**GEPA evolutionary search:**
1. Sample mini-batches of training examples (snapshot + targeted_files pairs)
2. Run critic on each example, measure recall/precision
3. Reflection LM analyzes failures and proposes prompt improvements
4. Evolve population of prompt variants
5. Validate on held-out examples

**Key insight:** Per-file examples give tighter feedback
- Easier to see "critic missed this specific issue in this file"
- Easier to hill-climb: fix one pattern at a time
- More training signal: 100 examples vs 5

**Terminal evaluation:** After optimization, test on full-snapshot examples
- Does the critic generalize to comprehensive repo review?
- Can it find 50-100+ issues across all patterns?

## Implementation

See:
- `models/training_example.py` - TrainingExample model and filtering logic
- `db/models.py` - ORM models (Snapshot, TruePositive, FalsePositive) for loading issues from database
- `db/sync/_loader.py` - FilesystemLoader (private, sync-only) for syncing jsonnet to database
- `gepa/gepa_adapter.py` - GEPA integration (loads training examples from database via ORM)
- `specimens/critic_scopes.yaml` - Training example specifications (to be created)

**Note:** Training examples are loaded from the database at runtime. The jsonnet files (`.libsonnet`) are synced to the database once via `adgn-properties db sync`.
