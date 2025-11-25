# Prompt Optimizer Implementation Plan

## Overview

Improve the prompt optimization agent by giving it proper train/valid/test splits and access to training data for analysis.

**Goals:**
- Prevent overfitting: agent optimizes on train+valid, test results hidden
- Enable deep analysis: agent can read specimen code and transcripts
- Focus on recall: primary metric, with precision caveats documented
- Budget-aware: track token usage and enforce $ budget limits
- Granular evaluation: test on single files, specimens, or full splits
- Agent-driven iterations: tools run once; agent can rerun for statistical validity

## Data Splits and Information Isolation

### Train Split
- **Agent sees:** Full per-specimen metrics, all artifacts, transcripts
- **Purpose:** Deep analysis of failures, understanding patterns
- **Access:** Read specimen code, critic/grader transcripts, grades

### Valid Split
- **Agent sees:** Aggregate metrics only (mean recall, mean precision, counts)
- **Purpose:** Check generalization without overfitting
- **Access:** No per-specimen details, no transcripts

### Test Split
- **Agent sees:** Nothing
- **Purpose:** Final evaluation for human review
- **Access:** Results persisted to disk only, never shown to agent

## Directory Structure

```
runs/
  prompt_evals/                       # Shared evaluation results (all optimizer runs)
    eval_<timestamp_a>/
      prompt.txt                      # candidate prompt
      train_results.json              # EvalSplitOutput (train)
      valid_summary.json              # EvalSplitOutput (valid)
      {train_specimen_slug}/          # full train artifacts
        critic.json
        grade.json
        critic/
          events.jsonl
          metadata.json
        grader/
          events.jsonl
          metadata.json
    eval_<timestamp_b>/
      ...

  prompt_evals_test/                  # Test results (NOT mounted to agent)
    eval_<timestamp_a>/
      test_summary.json
      {test_specimen_slug}/
        critic.json
        grade.json
        critic/events.jsonl
        grader/events.jsonl
    eval_<timestamp_b>/
      ...

  prompt_optimize_<session_timestamp>/  # One optimizer session (mounted as /workspace)
    transcript/                       # optimizer agent transcript
      events.jsonl
      metadata.json
    # Agent organizes its work here (e.g., prompts/, notes/, etc.)

  prompt_optimize_<session_timestamp_2>/  # Another session
    ...
```

**Key changes:**
- Evaluations are shared across all optimizer runs in `prompt_evals/`
- Each evaluation gets `eval_<timestamp>` directory (not per-session rounds)
- Each optimizer session in `prompt_optimize_<timestamp>/`
- Agent's session directory mounted as `/workspace` (rw)
- Agent organizes its own work and writes prompts wherever it wants
- All other mounts are read-only
- Agent can learn from all past evaluations across multiple sessions
- Test results isolated in `prompt_evals_test/` (never mounted)

### Optional Future Enhancements

**Final summary generation** (low priority):
- Generate human-readable report comparing train/valid/test metrics
- Track "best prompt so far" across sessions
- Cost breakdown by split

## Key Design Decisions

- Tools track cost via `GroundTruthUsage` → `calculate_cost()`
- Each tool returns `cost`, `total_cost_so_far`, `budget_remaining`

### 3. Granular Evaluation Methods

| Method | Scope | Cost | Use Case |
|--------|-------|------|----------|
| `eval_file()` | One file | Low | Fast iteration on specific failures |
| `eval_specimen()` | One specimen | Medium | Validate fixes on full specimen |
| `eval_split()` | Full split | High | Measure train/valid generalization |

### 4. Split Isolation
- Train: full details (metrics, transcripts, artifacts)
- Valid: aggregates only (no per-specimen details)
- Test: never shown to agent (raises error if requested)

### 5. Docker Security
- NO /repo mount (would leak test specimen definitions via splits.py)

### 6. JSON Persistence
- Train results: `EvalSplitOutput` serialized to `train_results.json`
- Valid results: `EvalSplitOutput` serialized to `valid_summary.json`
- Both use `.model_dump_json(indent=2)` for consistent structure
