# Specimen: ducktape adgn agent (2025-11-20)

## Purpose

This specimen captures code quality findings in the adgn agent codebase, focusing on type correctness and defensive programming anti-patterns.

## Issues

- **001**: Normalization function for type that cannot occur (`_normalize_call_arguments`)
- **002**: Unused `--ui-port` flag misleads users about non-existent Management UI
- **003**: Silent failure when `--mcp-config` or `--initial-policy` file doesn't exist

See `issues/*.libsonnet` for detailed rationale, properties violated, and file locations.

## Scope

Focus on the adgn agent core (`adgn/src/adgn/agent/`), particularly:
- Type correctness in data flow
- Defensive programming that contradicts type system
- Functions that should not exist due to type guarantees
