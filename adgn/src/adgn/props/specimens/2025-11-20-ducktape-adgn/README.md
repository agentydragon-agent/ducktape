# Specimen: ducktape adgn agent (2025-11-20)

## Purpose

This specimen captures code quality findings in the adgn agent codebase, focusing on type correctness and defensive programming anti-patterns.

## Issues

- **001**: Normalization function for type that cannot occur (`_normalize_call_arguments`)
- **002**: Unused `--ui-port` flag misleads users about non-existent Management UI
- **003**: Silent failure when `--mcp-config` or `--initial-policy` file doesn't exist
- **004**: `AgentEntry` should be a dataclass
- **005**: `get_local_runtime` should use walrus operator to avoid intermediate variable
- **006**: `PolicyError.stage` should be StrEnum (if field should exist at all)
- **007**: Unnecessary pre-serialization before persistence (model_dump in multiple locations)
- **008**: Inline `result_model` variable in `on_tool_result_event`
- **009**: Policy model docstring duplicates PolicyStatus enum documentation
- **010**: `Policy.status` should use PolicyStatus StrEnum type
- **011**: `ChatMessage.author` and `mime` should use StrEnum types (if fixed valid values)
- **012**: SQLAlchemy import inside function should be at module top
- **013**: `Agent.id` should be typed as AgentID in SQLAlchemy model
- **014**: `proposal_id` parameters should be int not str (9+ locations)
- **015**: `Run.status` and `Event.type` should use StrEnum types

See `issues/*.libsonnet` for detailed rationale, properties violated, and file locations.

## Scope

Focus on the adgn agent core (`adgn/src/adgn/agent/`), particularly:
- Type correctness in data flow
- Defensive programming that contradicts type system
- Functions that should not exist due to type guarantees
