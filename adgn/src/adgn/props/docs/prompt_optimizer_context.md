# Context for Prompt Optimizer Agent

**You are optimizing a code review critic agent.** This document explains the dataset, evaluation strategy, and terminal goal.

## What You're Optimizing

**The Critic:** An LLM agent that **behavior-clones the user's code review judgment** - finding issues the user would find, following their subjective preferences and taste.

**Not Generic Review:** You're learning specific preferences:
- What duplication is acceptable vs should be refactored
- What naming is clear vs verbose
- What abstraction level is appropriate
- What comments add value vs are noise
- What patterns are idiomatic vs anti-patterns

**Your Job:** Evolve the critic's system prompt to maximize its ability to find issues the user would flag while avoiding false positives (things that look wrong but the user accepts)

**Optimization Methods:** Multiple approaches can use this dataset:
- **GEPA:** Evolutionary search with reflection-based improvements
- **Prompt-optimizer agent:** LLM-based iterative refinement
- **Manual tuning:** Direct prompt engineering

This document describes the dataset and evaluation strategy common to all approaches.

## Dataset Structure

### Snapshots (Frozen Code States)
- **Snapshot** = codebase at specific commit + labeled ground truth issues
- Example: `ducktape/2025-11-26-00` → commit ab7e9d6... with 58 known issues
- Like ImageNet: immutable training data with labels

### Training Examples
- **Training Example** = `(snapshot, targeted_files)` pair
- **Question:** "Review these specific files in this snapshot - what issues can you find?"
- **Ground truth:** Which TPs are catchable + which FPs are relevant (computed from targeted_files)

**Example:**
```python
TrainingExample(
    snapshot_slug="ducktape/2025-11-26-00",
    targeted_files={Path("src/server.py")},
    true_positives=[...],  # Only issues catchable from server.py
    false_positives=[...], # Known acceptable patterns
)
```

### True Positives (TPs)
**Definition:** Real issues that should be caught

**Key field:** `expect_caught_from` - minimal file sets needed to DETECT the issue

**Detection Standard:** "If a competent code reviewer sees these files and does a thorough review (following imports, checking for duplication, looking for patterns), would they reasonably catch this issue?"

**Examples:**
- **Duplication in A+B:** `expect_caught_from: [[A], [B]]` (OR logic - seeing EITHER file should trigger "search for duplication")
- **Missing abstraction:** `expect_caught_from: [[client.py, utils.py]]` (AND logic - need to see both the ad-hoc implementation AND the existing utility to notice redundancy)
- **Dead code:** `expect_caught_from: [[foo.py]]` (seeing the file is enough - no callers, unused import, etc.)

**Filtering Logic:** A TP is "catchable" from targeted_files if ANY trigger set is a subset:
```python
catchable = any(
    trigger_set <= targeted_files
    for occurrence in tp.occurrences
    for trigger_set in occurrence.expect_caught_from
)
```

### False Positives (FPs)
**Definition:** Things that look wrong but are actually acceptable (intentional patterns)

**Example:** Duplication for visual consistency in UI components (known design choice)

**Currently:** All FPs are included in all training examples (not filtered by scope - there are few of them)

## Two-Level Evaluation Strategy

### 1. Per-File Examples (Training & Hill-Climbing)
**Purpose:** Easier optimization with tighter feedback loops

**What:** Many focused examples per snapshot
- Single files: "Review server.py"
- File pairs: "Review types.py + persist.py" (check for duplication)
- Component sets: "Review all *.svelte files" (UI patterns)

**Metrics:** Recall/precision on catchable issues given targeted_files

**Why This Helps:**
- More training signal: 5 snapshots → 100+ examples (not just 5)
- Clearer feedback: "You missed this specific issue in this file" (not "you missed 20 issues somewhere")
- Easier to hill-climb: Fix one pattern at a time

### 2. Full-Snapshot Examples (Terminal Metric)
**Purpose:** Real-world performance evaluation

**What:** One example per snapshot targeting ALL files
```python
TrainingExample(
    snapshot_slug="ducktape/2025-11-26-00",
    targeted_files=ALL_FILES,  # Everything
    true_positives=ALL_TPS,    # All 58 issues
    false_positives=ALL_FPS,
)
```

**This is the GOAL:** Comprehensive repo review finding 50-100+ issues

**Terminal Metric:** How well does the critic perform on full-repo review after optimization?

## Current State

**Baseline Performance:** 1-4% recall on per-file examples
- The critic is finding 1-4 issues out of every 100 it should catch
- Lots of room for improvement!

**Your Task:** Evolve the prompt to dramatically improve this

## GEPA Optimization Process

**What GEPA does:**
1. Sample mini-batches of training examples (per-file scenarios)
2. Run the critic on each example → collect execution traces
3. Grade the critique → compute recall/precision, identify missed issues
4. You (reflection LM) analyze failures and propose improvements
5. GEPA evolves a population of prompt variants based on your suggestions

**What feedback you get:**

**Execution Traces:**
```
CALL docker__run_command({"command": "ruff check src/"})
  → src/foo.py:42: E501 Line too long...
CALL critic_submit__upsert_issue({"issue_id": "line-too-long", ...})
```

**Grader Analysis:**
```
MISSED ISSUES (TPs not caught):
  - dead-import (server.py:15): Unused import `typing.cast`
  - duplicated-enum (types.py:20-25, persist.py:54-58): Status enum defined in two places

FALSE POSITIVES TRIGGERED:
  - trivial-style-nit: Known FP, this duplication is intentional

SUMMARY: The critic focused on style issues but neglected dead code detection...
```

**Your job:** Synthesize this into concrete prompt improvements
- "Add explicit step: Check for unused imports with AST analysis"
- "Before flagging duplication, check if it's in UI components (known acceptable pattern)"
- "Prioritize semantic issues (dead code, type errors) over style nits"

## Strategy Guidance

**Remember:**
- Per-file examples are for **training/optimization** (easier hill-climbing)
- Full-snapshot examples are the **terminal goal** (comprehensive review)
- Don't over-optimize for single-file scenarios at the expense of cross-cutting patterns
- The critic should generalize: work well on both focused and comprehensive review

**Focus areas** (current 1-4% recall suggests these are all weak):
- Dead code detection
- Duplication finding (across files)
- Type correctness
- Architecture smells
- Naming/clarity issues
- Test quality issues

**Avoid:**
- Over-focusing on style nits (Ruff already catches those)
- False positive triggers on known acceptable patterns
- Missing cross-cutting issues that require seeing multiple files

## Files to Read

Core documentation (recommended reading order):
1. `docs/training_strategy.md` - This strategy in detail
2. `docs/authoring.md` - How ground truth issues are authored
3. `models/training_example.py` - TrainingExample model and filtering logic
4. `gepa/README.md` - GEPA integration details

When analyzing failures, you can inspect:
- Snapshot code (mounted at `/workspace` in container)
- Ground truth issues (mounted at `/props` or via MCP)
- Execution traces (in feedback payload)
