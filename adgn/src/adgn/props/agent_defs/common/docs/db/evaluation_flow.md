# Evaluation Flow: Critic → Grader → Metrics

This document describes the end-to-end evaluation pipeline for prompt optimization.

## Pipeline Overview

```
Critic Run                    Grader Run                 Metrics
───────────                   ──────────                 ───────
Source code ─┐
             ├─> Critique ────> Match to TPs/FPs ────> Recall
System prompt┘   (reported_issues)  (grading_decisions)    (aggregate views)
```

## snapshots

!psql -c "\d+ snapshots"

## 1. Critic Run

**What the critic sees:**
- Source code mounted at `/workspace` (read-only)
- System prompt with task description
- Database access for writing issues

**What the critic DOES NOT see:**
- Ground truth issues (TPs/FPs)
- Expected output or "answers"
- Grader feedback or metrics

**Critic's task:** Review code, report issues, and call submit when done.

## 2. Grader Run

**Input:**
- Critique from critic (query `reported_issues`)
- Ground truth from snapshot (query `true_positives`, `false_positives`)

**Process:**
1. Match each reported issue to TPs (assign credit)
2. Check for FPs (flag incorrect complaints)
3. Mark unmatched issues as unknowns

**Output:** `grading_decisions` table populated, `grader_run.output` contains aggregated results.

## 3. Metrics Computation

**Per-run:** Recall = sum(found_credit) / count(occurrences)

**Aggregate:** Query views like `aggregated_recall_by_definition`

## Optimization Modes

The prompt optimizer supports two modes that control validation data access.

### Whole-Repo Mode

**Philosophy:** Black-box validation - agent only sees aggregate recall, no filenames.

**Characteristics:**
- Validation examples: Only full-snapshot (comprehensive review)
- Examples table: RLS-blocked for VALID split (no filenames visible)
- Ground truth: Hidden
- Execution traces: Hidden

**Query method:**
```sql
SELECT * FROM get_validation_full_snapshot_aggregates()
WHERE critic_definition_id = '<def_id>';
```

**Use case:** Final evaluation, measuring true generalization without risk of overfitting.

### Targeted Mode

**Philosophy:** White-box iteration - agent can see filenames and target specific files.

**Characteristics:**
- Validation examples: Both per-file and full-snapshot
- Examples table: Accessible for VALID split (filenames visible)
- Ground truth: Still hidden
- Execution traces: Still hidden

**Query method:**
```sql
SELECT (occurrences_caught_stats).mean AS recall, n_examples,
       (occurrences_caught_stats).ucb95 AS ucb, (occurrences_caught_stats).lcb95 AS lcb
FROM aggregated_recall_by_definition
WHERE critic_definition_id = '<def_id>' AND split = 'valid';
```

**Use case:** Rapid iteration, debugging specific patterns.

**IMPORTANT:** Always check `n_examples >= 5` before trusting metrics (small samples = high variance).

## Data Access Patterns

### For Training Split

Full access to everything:
```python
# Get examples
examples = session.query(Example).join(Snapshot).filter(Snapshot.split == "train").all()

# Get critic runs with grader results
critic_run = session.query(AgentRun).filter_by(agent_run_id=critic_run_id).one()

# Access ground truth
tps = session.query(TruePositive).filter_by(snapshot_slug=slug).all()

# Read execution traces
events = session.query(Event).filter_by(agent_run_id=agent_run_id).order_by(Event.sequence_num).all()
```

### For Validation Split

Access varies by mode:

**Whole-Repo Mode:**
```python
# Can run critic on validation whole-snapshot only
# Query for whole-snapshot example
example = session.query(Example).filter_by(
    snapshot_slug="ducktape/2025-11-26-01",
    example_kind=ExampleKind.WHOLE_SNAPSHOT
).one()

result = await run_critic_on_example(example=example, ...)

# Query aggregate metrics via SECURITY DEFINER function
results = session.execute(text("""
    SELECT * FROM get_validation_full_snapshot_aggregates()
    WHERE critic_definition_id = :def_id
"""), {"def_id": definition_id})

# CANNOT see examples table (RLS blocked)
# CANNOT inspect ground truth or execution traces
```

**Targeted Mode:**
```python
# Can see example filenames
examples = session.query(Example).join(Snapshot).filter(Snapshot.split == "valid").all()

# Can run per-file evaluations
# Choose a specific example from the list
example = examples[0]  # Example with (snapshot_slug, example_kind, files_hash) composite key
result = await run_critic_on_example(example=example, ...)

# Query metrics via views
results = session.execute(text("""
    SELECT (occurrences_caught_stats).mean AS recall, n_examples,
           (occurrences_caught_stats).ucb95 AS ucb, (occurrences_caught_stats).lcb95 AS lcb
    FROM aggregated_recall_by_definition
    WHERE critic_definition_id = :def_id AND split = 'valid'
"""), {"def_id": definition_id})

# Can see filenames but CANNOT inspect ground truth or traces
```
