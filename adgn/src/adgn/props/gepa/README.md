# GEPA-based Prompt Optimization for Props Critic

Uses [gepa-ai/gepa](https://github.com/gepa-ai/gepa) for evolutionary optimization of the critic system prompt.

## What GEPA Provides

- **Evolutionary search**: Population-based optimization over prompt variants
- **Reflection**: LLM analyzes traces to propose targeted improvements
- **Pareto optimization**: Multi-objective optimization (recall + precision)
- **Efficient**: Outperforms RL with fewer rollouts

## CLI Usage

```bash
# Default: full-snapshot examples
adgn-properties gepa --max-metric-calls 100
```

## Feedback

GEPA receives rich feedback for each evaluation:

**1. Execution Traces** (from `events` table):
```
CALL docker__run_command({"command": "ruff check src/"})
  → src/foo.py:42: E501 Line too long...
CALL critic_submit__upsert_issue({"issue_id": "line-too-long", ...})
```

**2. Grader Analysis** (full `GradeSubmitInput`):
```
MISSED ISSUES:
  - dead-import: The critic didn't check for unused imports
  - missing-type-annotation: No type checking performed
FALSE POSITIVES TRIGGERED:
  - trivial-style-nit: Known FP, should be ignored
SUMMARY: The critic focused on runtime issues but neglected...
```

## Key Types

- `SnapshotInput`: Input for evaluation (slug, target_files, known_true_positives, known_false_positives)
- `CriticTrajectory`: Execution trace (transcript_id, events, critique_payload)
- `CriticOutput`: Evaluation result (issues_found, grader_output, recall)
- `CriticAdapter`: GEPA adapter wrapping Agent + grader
