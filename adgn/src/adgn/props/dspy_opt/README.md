# DSPy-based Prompt Optimization with GEPA-style Feedback

DSPy optimizes prompt text using rich structured feedback from your existing infrastructure.

## Feedback Sources

The optimizer receives three types of structured feedback for each failed specimen:

### 1. Execution Traces (from `events` table)
```
[0] CALL docker__run_command({"command": "ruff check src/"})
[1] → src/foo.py:42: E501 Line too long...
[2] CALL critic_submit__upsert_issue({"issue_id": "line-too-long", ...})
...
```

### 2. Grader Analysis (full `GradeSubmitInput`)
```
Covered 2/5 canonical issues (recall=40%)

**Missed Issues (CRITICAL):**
- dead-import: The critic didn't check for unused imports in module.py
- missing-type-annotation: Function bar() lacks return type annotation

**False Positives Triggered:**
- trivial-style-nit: This is a known FP, prompt should ignore
```

### 3. Ground Truth Issues (from specimen)
```
- **dead-import**: Unused import 'os' at line 3 (in src/module.py)
- **missing-type-annotation**: Function bar() needs return type (in src/api.py)
```

## Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Optimization Loop                         │
│                                                              │
│  1. run_critic() on train specimens                          │
│     └─ Logs events to DB (tool calls, outputs)              │
│                                                              │
│  2. grade_critique_by_id()                                   │
│     └─ Returns full GradeSubmitInput (coverage, rationales) │
│                                                              │
│  3. Format rich feedback:                                    │
│     - Execution trace (what agent did)                       │
│     - Grader analysis (what was missed/covered)              │
│     - Ground truth (what should be found)                    │
│                                                              │
│  4. DSPy PromptImprover analyzes failures, proposes fix      │
│                                                              │
│  5. Repeat until target recall                               │
└─────────────────────────────────────────────────────────────┘
```

## Usage

```python
import dspy
from adgn.openai_utils.client_factory import build_client
from adgn.props.dspy_opt import optimize_critic_prompt
from adgn.props.specimens.registry import SpecimenRegistry

# Configure DSPy LM for prompt improvement
dspy.configure(lm=dspy.LM("openai/gpt-4o"))

# Your existing infrastructure
client = build_client()
registry = SpecimenRegistry.from_package_resources()

# Initial prompt
initial_prompt = Path("prompts/critic_system.md").read_text()

# Optimize with rich feedback
best_prompt, history = await optimize_critic_prompt(
    initial_prompt=initial_prompt,
    registry=registry,
    client=client,
    max_iterations=5,
    target_recall=0.95,
)

# Check validation performance
from adgn.props.dspy_opt.optimize import evaluate_on_validation
valid_eval = await evaluate_on_validation(best_prompt, registry, client)
print(f"Validation recall: {valid_eval.avg_recall:.2%}")
```

## Key Types

- `RichEvalResult`: Full evaluation with grader output, ground truth, and trace
- `PromptEvaluation`: Aggregated results with `avg_recall` and `failures`
- `PromptImprover`: DSPy signature that analyzes feedback and proposes improvements

## What the Optimizer Sees

For each failed specimen, the `PromptImprover` receives:

```markdown
# Specimen: ducktape/2025-11-20-00
**Recall: 40%**

### Ground Truth Issues (what should be found):
- **dead-import**: Unused import detected... (in src/module.py)
- **missing-annotation**: Function lacks type hints... (in src/api.py)

### Grader Analysis:
Covered 2/5 canonical issues (recall=40%)

**Missed Issues (CRITICAL - prompt must address these):**
- dead-import: The critic checked imports but missed the unused 'os' import
- missing-annotation: No type checking was performed on function signatures

**Grader Summary:** The critic focused on runtime issues but neglected...

### Execution Trace (what the agent did):
[0] CALL docker__run_command({"command": "ruff check ."})
[1] → All checks passed
[2] CALL docker__run_command({"command": "mypy src/"})
...
```

The optimizer uses this to understand:
- **What** was missed (grader analysis)
- **Why** it was missed (execution trace shows agent behavior)
- **What** should have been found (ground truth)
