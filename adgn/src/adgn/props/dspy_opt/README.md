# Prompt Optimization for Props Critic

Two approaches available for optimizing the critic system prompt:

## Option 1: Simple Loop (optimize.py)

Iterative improvement using DSPy ChainOfThought for prompt proposals.

```python
import dspy
from adgn.props.dspy_opt import optimize_critic_prompt

dspy.configure(lm=dspy.LM("openai/gpt-4o"))

best_prompt, history = await optimize_critic_prompt(
    initial_prompt=initial_prompt,
    registry=registry,
    client=client,
    max_iterations=5,
    target_recall=0.95,
)
```

## Option 2: GEPA Integration (gepa_adapter.py)

Full evolutionary optimization using [gepa-ai/gepa](https://github.com/gepa-ai/gepa).

```bash
pip install gepa
```

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

For full control over GEPA's parameters:

```python
import gepa
from adgn.props.dspy_opt import CriticAdapter, load_datasets

# Load specimens
trainset, valset = await load_datasets(registry)

# Create adapter
adapter = CriticAdapter(registry, client)

# Configure GEPA
reflection_lm = gepa.LM(model="gpt-4o", temperature=1.0)

result = gepa.optimize(
    seed_candidate={"system_prompt": initial_prompt},
    trainset=trainset,
    valset=valset,
    adapter=adapter,
    reflection_lm=reflection_lm,
    max_metric_calls=200,
    reflection_minibatch_size=3,
    perfect_score=1.0,
    use_wandb=True,
)

best_prompt = result.best_candidate["system_prompt"]
```

## How It Works

Both approaches use the same feedback sources:

### 1. Execution Traces (from `events` table)
```
CALL docker__run_command({"command": "ruff check src/"})
  → src/foo.py:42: E501 Line too long...
CALL critic_submit__upsert_issue({"issue_id": "line-too-long", ...})
```

### 2. Grader Analysis (full `GradeSubmitInput`)
```
MISSED ISSUES:
  - dead-import: The critic didn't check for unused imports
  - missing-type-annotation: No type checking performed
FALSE POSITIVES TRIGGERED:
  - trivial-style-nit: Known FP, should be ignored
SUMMARY: The critic focused on runtime issues but neglected...
```

### 3. Ground Truth (from specimen)
```
- dead-import: Unused import 'os' at line 3 (in src/module.py)
- missing-annotation: Function bar() needs return type (in src/api.py)
```

## GEPA Adapter Implementation

The `CriticAdapter` implements GEPA's `GEPAAdapter` protocol:

```python
class CriticAdapter:
    def evaluate(self, batch, candidate, capture_traces):
        """Run critic on specimens, return scores and traces."""
        # Calls run_critic() + grade_critique_by_id()
        # Returns EvaluationBatch(outputs, scores, trajectories)

    def make_reflective_dataset(self, candidate, eval_batch, components):
        """Format traces and grader feedback for GEPA's reflection."""
        # Returns structured dataset for the reflection LM
```

## Comparison

| Feature | Simple Loop | GEPA |
|---------|-------------|------|
| Optimization | Greedy improvement | Evolutionary + Pareto |
| Population | Single candidate | Population-based |
| Reflection | DSPy ChainOfThought | GEPA's reflection LM |
| Multi-objective | No | Yes (Pareto frontier) |
| Complexity | Simple | More configuration |

## Key Types

- `SpecimenInput`: Input for evaluation (slug, target_files, ground_truth)
- `CriticTrajectory`: Execution trace (events, critique payload)
- `CriticOutput`: Evaluation result (issues found, grader output, recall)
- `CriticAdapter`: GEPA adapter wrapping MiniCodex + grader
