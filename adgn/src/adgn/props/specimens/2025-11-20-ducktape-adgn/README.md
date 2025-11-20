# Specimen: ducktape adgn agent (2025-11-20)

## Purpose

This specimen captures code quality findings in the adgn agent codebase, focusing on type correctness and defensive programming anti-patterns.

## Key Findings

### Issue 001: Normalization function for type that cannot occur

**Function**: `_normalize_call_arguments` in `adgn/src/adgn/agent/agent.py:149-160`

This function accepts `dict[str, Any] | str | None` but is only ever called with `str | None` (from `FunctionCallItem.arguments`). The defensive `json.dumps()` fallback is unreachable because all construction paths guarantee string format.

**Key insight**: There should never be a code path where one doesn't know whether they hold a JSON dict, a string, or None. A caller should always be reduced to *either* a `json.dumps()` *or* identity operation, never both in a runtime type check.

**Properties violated**:
- `type-correctness-and-specificity`: Type signature is too wide (includes `dict[str, Any]` which never occurs)
- `no-dead-code`: The `json.dumps()` branch is unreachable
- `truthfulness`: Function contract suggests ambiguity that doesn't exist in practice

## Scope

Focus on the adgn agent core (`adgn/src/adgn/agent/`), particularly:
- Type correctness in data flow
- Defensive programming that contradicts type system
- Functions that should not exist due to type guarantees
