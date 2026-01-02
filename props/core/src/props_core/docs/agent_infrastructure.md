# Agent Infrastructure: Implementation Notes

This document covers implementation details for agent infrastructure. For agent-facing documentation, see `agent_defs/common/docs/`.

## Directory Structure

```
src/adgn/props/
├── agent_defs/              # Agent definitions (SSOT for agents)
│   ├── common/              # Shared docs, helpers, init scripts
│   ├── critic/              # Critic agent definition
│   ├── grader/              # Grader agent definition
│   ├── prompt_optimizer/    # Prompt optimizer definition
│   ├── improvement/         # Improvement agent definition
│   └── clustering/          # Clustering agent definition
├── critic/                  # Critic runtime (MCP server, persistence)
├── grader/                  # Grader runtime
├── prompt_optimize/         # Optimizer runtime
├── prompt_improve/          # Improvement runtime
├── clustering/              # Clustering runtime
├── db/                      # Database layer (ORM, migrations)
└── cli/                     # CLI commands
```

## Testing Requirements

### Example Script Tests

All example scripts must:

1. Import from helpers (not duplicate logic)
2. Work with zero configuration (auto-detect from environment)
3. Have tests verifying they run correctly

```python
def test_listing_example_runs(synced_test_fixtures):
    """listing.py should run without errors."""
    from props_core.prompt_optimize.examples import listing
    # Example runs during import or has main() that can be called
```

See `tests/props/CLAUDE.md` for comprehensive testing conventions.
