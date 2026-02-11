# GEPA-based Prompt Optimization for Props Critic

Uses [gepa-ai/gepa](https://github.com/gepa-ai/gepa) for evolutionary optimization of the critic system prompt.

## Installation

```bash
pip install gepa
```

## Usage

### High-level API

```python
from adgn.props.dspy_opt import optimize_with_gepa

optimized_prompt, result = await optimize_with_gepa(
    initial_prompt=initial_prompt,
    registry=registry,
    client=client,
    reflection_model="gpt-4o",
    max_metric_calls=100,
)
```

### Direct GEPA API

For full control:

```python
import gepa
from adgn.props.dspy_opt import CriticAdapter, load_datasets

trainset, valset = await load_datasets(registry)
adapter = CriticAdapter(registry, client)

result = gepa.optimize(
    seed_candidate={"system_prompt": initial_prompt},
    trainset=trainset,
    valset=valset,
    adapter=adapter,
    reflection_lm=gepa.LM(model="gpt-4o", temperature=1.0),
    max_metric_calls=200,
    reflection_minibatch_size=3,
    perfect_score=1.0,
    use_wandb=True,
)

best_prompt = result.best_candidate["system_prompt"]
```

## How It Works

The `CriticAdapter` implements GEPA's `GEPAAdapter` protocol:

```python
class CriticAdapter:
    def evaluate(self, batch, candidate, capture_traces):
        """Run critic on specimens via run_critic() + grade_critique_by_id()."""
        # Returns EvaluationBatch(outputs, scores, trajectories)

    def make_reflective_dataset(self, candidate, eval_batch, components):
        """Format traces + grader feedback for GEPA's reflection LM."""
```

### Feedback Sources

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
- `CriticAdapter`: GEPA adapter wrapping MiniCodex + grader

## What GEPA Provides

- **Evolutionary search**: Population-based optimization over prompt variants
- **Reflection**: LLM analyzes traces to propose targeted improvements
- **Pareto optimization**: Multi-objective optimization (recall + precision)
- **Efficient**: Outperforms RL with fewer rollouts
