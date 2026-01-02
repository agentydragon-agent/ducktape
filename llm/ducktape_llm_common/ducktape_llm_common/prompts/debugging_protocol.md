---
title: Debugging Protocol
description: Systematic approach to debugging issues
variables:
  - error_description
  - context
  - stack_trace
  - attempted_solutions
  - timestamp
category: Development
---

# Debugging Protocol

**Timestamp**: {timestamp}

## Error Description

{error_description}

## Context

{context}

## Stack Trace

```
{stack_trace}
```

## Attempted Solutions

{attempted_solutions}

## Debugging Approach

### 1. Reproduce the Issue

- Verify the error can be consistently reproduced
- Document the exact steps to trigger the error
- Note any environmental factors

### 2. Isolate the Problem

- Identify the minimal code that triggers the error
- Remove unrelated components
- Test with simplified inputs

### 3. Gather Evidence

- Collect all error messages and stack traces
- Add logging/debugging output
- Check system state before and after error

### 4. Form Hypotheses

- List possible causes based on evidence
- Prioritize by likelihood
- Consider edge cases and assumptions

### 5. Test Solutions

- Start with the most likely hypothesis
- Make one change at a time
- Verify the fix doesn't break other functionality

### 6. Document the Fix

- Explain what caused the issue
- Document the solution
- Add tests to prevent regression
- Update any relevant documentation

## Common Debugging Patterns

- **Off-by-one errors**: Check loop boundaries and array indices
- **Type mismatches**: Verify data types at interfaces
- **Race conditions**: Look for timing-dependent behavior
- **State corruption**: Check for unintended mutations
- **External dependencies**: Verify API responses and file contents
