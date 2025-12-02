# DSPy Integration for Props

This module adapts the props evaluation framework to DSPy's optimization paradigm.

## Concept

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Specimens     │ ──▶ │   DSPy ReAct     │ ──▶ │    Grader       │
│   (train/valid) │     │   Critic         │     │   (metric)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                      │                        │
         │                      ▼                        │
         │              ┌──────────────────┐             │
         └────────────▶ │  Teleprompter    │ ◀───────────┘
                        │  (optimization)  │
                        └──────────────────┘
                                │
                                ▼
                        Optimized Prompt
```

## Key Components

### Specimens → DSPy Examples

```python
from adgn.props.dspy_opt import load_specimens_as_examples
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import Split

registry = SpecimenRegistry.from_package_resources()
train_examples = await load_specimens_as_examples(registry, Split.TRAIN)
```

### Workspace-Aware Tools

DSPy tools need access to the specimen workspace. We use contextvars:

```python
from adgn.props.dspy_opt.tools import workspace_context, WorkspaceTools

async with registry.load_and_hydrate(slug) as hydrated:
    async with workspace_context(hydrated):
        # Tools now have access to the workspace
        content = WorkspaceTools.read_file("src/module.py")
        output = WorkspaceTools.run_command("ruff check .")
```

### Grader as Metric

Two options:
- **Simple metric** (fast): Set intersection on issue IDs
- **LLM grader** (slow): Full semantic matching with your existing grader

```python
from adgn.props.dspy_opt.metric import simple_recall_metric, GraderMetricWithContext

# Fast (for optimization)
score = simple_recall_metric(example, prediction)

# Full (for final eval)
metric = GraderMetricWithContext(example, hydrated_specimen)
score = await metric.evaluate(prediction)
```

## Usage

### CLI

```bash
# Optimize
python -m adgn.props.dspy_opt.cli optimize --output optimized.json

# Evaluate
python -m adgn.props.dspy_opt.cli evaluate optimized.json --split valid

# List specimens
python -m adgn.props.dspy_opt.cli list-specimens
```

### Python API

```python
import dspy
from adgn.props.dspy_opt import optimize_critic
from adgn.props.specimens.registry import SpecimenRegistry

# Configure DSPy
dspy.configure(lm=dspy.LM("openai/gpt-4o"))

# Run optimization
registry = SpecimenRegistry.from_package_resources()
result = await optimize_critic(registry)

print(f"Train: {result.train_avg:.2%}")
print(f"Valid: {result.valid_avg:.2%}")

# Save optimized prompt
save_optimized_prompt(result.optimized_module, Path("optimized.json"))
```

## Limitations & TODOs

### Async/Sync Boundary

DSPy's teleprompter is synchronous, but our workspace tools are designed for async
Docker execution. Current workaround:
- Tools use sync subprocess calls during optimization
- Full async Docker is available for final evaluation

### Container Execution

The tools currently fall back to local execution. To use Docker:

```python
async with workspace_context(hydrated, container_exec=docker_exec_fn):
    # Tools now use Docker
    ...
```

### DSPy ReAct Limitations

DSPy ReAct is simpler than your MiniCodex agent:
- No MCP servers (tools are plain functions)
- No structured output schema (uses free-form issue list)
- No multi-turn conversation (single ReAct episode)

For more complex agent behavior, consider:
1. Using DSPy just for prompt optimization
2. Plugging the optimized prompt back into MiniCodex

## Architecture Comparison

| Component | Props (current) | DSPy Integration |
|-----------|-----------------|------------------|
| Agent | MiniCodex + MCP | dspy.ReAct |
| Tools | MCP servers (Docker) | Plain functions (contextvar) |
| Output | CriticSubmitPayload | dict (issues list) |
| Metric | LLM Grader | simple_recall_metric (fast) or LLM grader |
| Optimization | Custom prompt_optimizer | DSPy teleprompter |
| State | Postgres + events | In-memory |

## Next Steps

1. **Test on real specimens** - Verify the integration works end-to-end
2. **Docker tool execution** - Wire up container_exec properly
3. **Structured output** - Add Pydantic output parsing to DSPy
4. **MIPRO teleprompter** - Try instruction optimization (not just few-shot)
5. **Hybrid approach** - Use DSPy-optimized prompt in MiniCodex
