# DSPy-based Prompt Optimization for Props

DSPy is used **only** for generating/optimizing prompt text.
Agent execution uses existing `run_critic()` + `grade_critique_by_id()`.

## Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Optimization Loop                         │
│                                                              │
│  1. Current prompt                                           │
│         │                                                    │
│         ▼                                                    │
│  2. run_critic() on train specimens                          │
│     (MiniCodex + Docker MCP - your existing infrastructure)  │
│         │                                                    │
│         ▼                                                    │
│  3. grade_critique_by_id() for each                          │
│     (LLM grader - your existing grader)                      │
│         │                                                    │
│         ▼                                                    │
│  4. DSPy LM proposes improved prompt based on failures       │
│         │                                                    │
│         ▼                                                    │
│  5. Repeat until target recall or max iterations             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Usage

```python
import dspy
from adgn.openai_utils.client_factory import build_client
from adgn.props.dspy_opt import optimize_critic_prompt
from adgn.props.specimens.registry import SpecimenRegistry

# Configure DSPy LM (for prompt improvement only)
dspy.configure(lm=dspy.LM("openai/gpt-4o"))

# Your existing client for critic/grader execution
client = build_client()
registry = SpecimenRegistry.from_package_resources()

# Load initial prompt
initial_prompt = Path("prompts/critic_system.md").read_text()

# Optimize
best_prompt, history = await optimize_critic_prompt(
    initial_prompt=initial_prompt,
    registry=registry,
    client=client,
    max_iterations=5,
    target_recall=0.95,
    verbose=True,
)

# Evaluate on validation
from adgn.props.dspy_opt.optimize import evaluate_on_validation
valid_eval = await evaluate_on_validation(best_prompt, registry, client)
print(f"Validation recall: {valid_eval.avg_recall:.2%}")
```

## What DSPy does here

DSPy's role is minimal:
- `PromptImprover` signature generates improved prompts based on failure feedback
- `dspy.ChainOfThought(PromptImprover)` is used to propose changes

Everything else uses your existing infrastructure:
- Critic runs in Docker via MCP (your `run_critic`)
- Grading via your LLM grader (`grade_critique_by_id`)
- Specimens from your registry
- Results stored in your Postgres DB

## Key types

- `EvalResult`: Single specimen evaluation (critic_run_id, critique_id, grader_run_id, recall)
- `PromptEvaluation`: Full evaluation of a prompt (results list, avg_recall, failures)
