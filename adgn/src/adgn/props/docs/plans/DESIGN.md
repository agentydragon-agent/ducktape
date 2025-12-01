# Props Run Management Design

## Overview

Unified structure for all props evaluation runs with type-safe management, computed paths, and hard-to-misuse APIs.

## Directory Structure

**Note**: All specimen slugs must have exactly one slash (`{project}/{date-sequence}`). Flat specimens (e.g., `2025-08-29-pyright_watch_report`) should be migrated to `misc/{name}` (e.g., `misc/2025-08-29-pyright_watch_report`).

```
runs/
  cluster/
    TIMESTAMP/
      input.json
      output.json
      results/
        SPECIMEN/
          clusters.json
```

## Key Design Principles

1. **Input data is the spec**: No artificial split between spec and input - the input contains all information needed to compute paths
4. **Scope ID computed by run class**: Each run type knows how to encode its input into scope_id
5. **Paths are computed properties**: Lazy evaluation, single source of truth
6. **Status is StrEnum**: Type-safe enum for run states
7. **Reference paths relative to `runs/`**: Easy resolution across run types

## Orchestrated Sessions (Separate Design)

Orchestrated sessions (full-split evals, optimizer) will have their own input/run types that:
- Don't nest under `{split}/{run_type}/`
- Reference atomic runs via `relative_path`
- Have their own input/output models

Example:

```python
class FullSplitEvalInput(BaseModel):
    split: Split
    specimens: list[str]
    system_prompt: str
    model: str

class FullSplitEvalRun(AgentRun[FullSplitEvalInput, FullSplitEvalOutput]):
    @property
    def root(self) -> Path:
        # Override: no split nesting
        return self.runs_root / "evals" / f"full-split:{self.input.split}" / self.timestamp

    async def _execute(self):
        # Launch multiple CriticRun + GraderRun in parallel
        # Collect references and aggregate metrics
        ...
```

## Migration Notes

### Current → New Structure

3. **References**: Update all `critic_run` references to use new relative paths

4. **Cluster-unknowns**: Update glob to `runs/{train,valid,all}/grader/specimen*/*/unknowns/*.yaml`

## Design Rationale

### Why Computed Properties?

Paths are computed on-the-fly from input data instead of being stored:
- Ensures consistency (can't have stale cached paths)
- Makes run objects lightweight (just input + root + timestamp)
- Easy to serialize/deserialize (just save input.json + timestamp)
- Properties are cheap enough for repeated access

## Future Considerations

### Typed Path References

Currently, run references use plain strings (e.g., `critic_run: str`). We could introduce a more specific type:

```python
class RunReference(str):
    """Newtype for run-relative paths (relative to runs/)."""
    pass

class GraderSpecimenInput(SpecimenScopeInput):
    critic_run: RunReference
```

Benefits:
- Type safety: distinguish run references from arbitrary strings
- Static analysis: catch incorrect path usage
- Documentation: self-documenting in function signatures

Trade-offs:
- Additional complexity for marginal benefit
- Plain strings work fine for now
- Can migrate later if needed without breaking serialization (strings are compatible)
