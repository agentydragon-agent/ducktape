# Walrus Operator (`:=`) Refactoring Scan Report

**Scan Date**: 2025-11-19
**Scan File**: `prompts/scans/walrus-get-pattern.md`

## Executive Summary

This scan identifies Python code patterns where the walrus operator (`:=`) could be used to
simplify code by moving dictionary `.get()` calls into conditional statements.

### Scan Results

| Priority | Count | Recommendation |
|----------|-------|-----------------|
| **HIGH** | 8 | Recommended for immediate refactoring |
| **MEDIUM** | 38 | Review context - refactor if straightforward |
| **LOW** | 6 | Not recommended - keep current pattern |
| **SKIP** | 1 | False positive - skip |
|  | **53 total** | |

## Overview

### What is the Walrus Operator?

The walrus operator (`:=`) allows assignment within expressions, available in Python 3.8+.

### Pattern Being Detected

```python
# Current pattern (2 lines)
value = dict.get(key)
if value:
    use(value)

# With walrus operator (1 line)
if (value := dict.get(key)):
    use(value)
```

## HIGH PRIORITY: 8 Violations

These are excellent candidates for walrus operator refactoring. Variables are only used
within the conditional block, making the conversion straightforward and clear.

### 1. adgn/src/adgn/llm/sysrw/leaderboard.py

**Location**: Line 105

**Code:**

```python
     102 |                     t = t2
     103 |         if t.exists():
     104 |             h = sha1_text(t.read_text(encoding="utf-8"))
>>>  105 |             curr = mapping.get(h)
     106 |             label = str(t)
     107 |             if curr is None or label < curr:
     108 |                 mapping[h] = label
```

**Suggested Refactoring**:

```python
# Before:
curr = mapping.get(...)
if curr ['if', 'var']:
    ...

# After:
if (curr := mapping.get(...)) ['if', 'var']:
    ...
```

### 2. adgn/src/adgn/mcp/compositor/server.py

**Location**: Line 244

**Code:**

```python
     241 |             await self.unmount_server(name)
     242 |         # Attach new or changed
     243 |         for name, spec in cfg.mcpServers.items():
>>>  244 |             prev = current_specs.get(name)
     245 |             if prev is None or prev.model_dump(mode="json") != spec.model_dump(mode="json"):
     246 |                 await self.mount_server(name, spec)
     247 | 
```

**Suggested Refactoring**:

```python
# Before:
prev = current_specs.get(...)
if prev ['if', 'var']:
    ...

# After:
if (prev := current_specs.get(...)) ['if', 'var']:
    ...
```

### 3. adgn/src/adgn/openai_utils/probe/main.py

**Location**: Line 388

**Code:**

```python
     385 |     _outputs = data.get("output", [])
     386 |     outputs = _outputs if _outputs is not None else []
     387 |     for item in outputs:
>>>  388 |         typ = item.get("type")
     389 |         name: str | None = None
     390 |         args = None
     391 |         if typ == "function_call":
```

**Suggested Refactoring**:

```python
# Before:
typ = item.get(...)
if typ ['if', 'var']:
    ...

# After:
if (typ := item.get(...)) ['if', 'var']:
    ...
```

### 4. adgn/src/adgn/openai_utils/probe/main.py

**Location**: Line 397

**Code:**

```python
     394 |                 name = fc.get("name")
     395 |                 args = fc.get("arguments")
     396 |             else:
>>>  397 |                 name = item.get("name")
     398 |                 args = item.get("arguments")
     399 |         if name and _tool_ok_if_expected(name, args):
     400 |             return "✓ tool OK"
```

**Suggested Refactoring**:

```python
# Before:
name = item.get(...)
if name ['if', 'var']:
    ...

# After:
if (name := item.get(...)) ['if', 'var']:
    ...
```

### 5. ember/src/ember/integrations/gitea.py

**Location**: Line 106

**Code:**

```python
     103 |         url = self._build_url(f"/api/v1/repos/{repository.api_path}/contents/{encoded_path}", query={"ref": ref})
     104 |         data = self._request_json("GET", url)
     105 |         content = data.get("content")
>>>  106 |         encoding = data.get("encoding", "")
     107 |         if not isinstance(content, str):
     108 |             raise GiteaError(f"File {path} response missing content")
     109 |         if encoding == "base64":
```

**Suggested Refactoring**:

```python
# Before:
encoding = data.get(...)
if encoding ['if', 'var']:
    ...

# After:
if (encoding := data.get(...)) ['if', 'var']:
    ...
```

### 6. k8s/helm/matrix-stack/files/admin_bootstrap.py

**Location**: Line 70

**Code:**

```python
      67 |             data = resp.json()
      68 |         except ValueError:
      69 |             data = {}
>>>   70 |         errcode = data.get("errcode")
      71 |         message = data.get("error", resp.text)
      72 |         if errcode in {"M_USER_IN_USE", "M_CONFLICT"} or "User ID already exists" in message:
      73 |             print("Admin user already exists (password unchanged)", flush=True)
```

**Suggested Refactoring**:

```python
# Before:
errcode = data.get(...)
if errcode ['if', 'var']:
    ...

# After:
if (errcode := data.get(...)) ['if', 'var']:
    ...
```

### 7. k8s/helm/matrix-stack/files/ember_bootstrap.py

**Location**: Line 76

**Code:**

```python
      73 |             data = resp.json()
      74 |         except ValueError:
      75 |             data = {}
>>>   76 |         errcode = data.get("errcode")
      77 |         message = data.get("error", resp.text)
      78 |         if errcode in {"M_USER_IN_USE", "M_CONFLICT"} or "User ID already exists" in message:
      79 |             print("Matrix user already exists", flush=True)
```

**Suggested Refactoring**:

```python
# Before:
errcode = data.get(...)
if errcode ['if', 'var']:
    ...

# After:
if (errcode := data.get(...)) ['if', 'var']:
    ...
```

### 8. llm/mcp/habitify/habitify_mcp_server/tools.py

**Location**: Line 32

**Code:**

```python
      29 |     Returns:
      30 |         ErrorResponse if validation fails, or None if validation passes
      31 |     """
>>>   32 |     id_param = kwargs.get("id")
      33 |     name_param = kwargs.get("name")
      34 | 
      35 |     if not id_param and not name_param:
```

**Suggested Refactoring**:

```python
# Before:
id_param = kwargs.get(...)
if id_param ['if', 'not']:
    ...

# After:
if (id_param := kwargs.get(...)) ['if', 'not']:
    ...
```

## MEDIUM PRIORITY: 38 Violations

These cases have potentially reused variables or complex conditions. Manual review required
to ensure the walrus conversion is appropriate. Only apply if the variable is ONLY used
in the immediate conditional block.

### Files to Review (by directory):

- `adgn/gitea_pr_gate/policy_common.py`: lines 44, 54
- `adgn/src/adgn/agent/agent.py`: lines 330
- `adgn/src/adgn/agent/event_renderer.py`: lines 105
- `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`: lines 511
- `adgn/src/adgn/llm/sysrw/cli.py`: lines 87
- `adgn/src/adgn/llm/sysrw/compare_eval_vs_ccr.py`: lines 68, 133
- `adgn/src/adgn/llm/sysrw/openai_typing.py`: lines 54
- `adgn/src/adgn/mcp/policy_gateway/signals.py`: lines 73
- `adgn/src/adgn/mcp/resources/server.py`: lines 251, 264
- `adgn/src/adgn/props/specimens/registry.py`: lines 113
- `adgn/src/adgn/third_party/openai_cookbook/apply_patch.py`: lines 35
- `adgn/tests/agent/ws_helpers.py`: lines 81
- `adgn/tests/conftest.py`: lines 201
- `adgn/tests/detectors/fixtures/bad/walrus_immediate.py`: lines 2
- `adgn/tests/detectors/fixtures/bad/walrus_ok_reuse.py`: lines 3
- `ember/src/ember/config.py`: lines 139
- `ember/src/ember/runtime/python_session.py`: lines 91, 183, 186
- `ember/src/ember/tool_execution.py`: lines 37, 51, 65
- `experimental/claude-history/claude_history_reader.py`: lines 240
- `gatelet/gatelet/server/auth/webhook_auth.py`: lines 62
- `gatelet/gatelet/server/test_admin_webhook_e2e.py`: lines 26
- `homeassistant/iaqi/custom_components/indoor_aqi/sensor.py`: lines 96
- `k8s/helm/ember/files/rspcache_key_rotator.py`: lines 36
- `tana/src/tana/export/export_node_subset.py`: lines 220
- `tana/src/tana/export/materialize_searches.py`: lines 23
- `tana/src/tana/query/search/evaluator.py`: lines 94
- `tana/src/tana/query/search/parser.py`: lines 49, 68, 123, 150
- `wt/src/wt/client/wt_client.py`: lines 347

### Review Checklist for Medium Priority

For each medium priority item, verify:

1. [ ] Variable is ONLY used in the immediate if/elif block
2. [ ] Variable is NOT used in an else clause
3. [ ] Variable is NOT used after the if block
4. [ ] Condition is simple (not complex boolean logic)
5. [ ] No default value is specified in .get()

## LOW PRIORITY: 6 Violations

These cases have characteristics that make walrus operator NOT recommended:

### 1. adgn/src/adgn/llm/sandboxer.py (Line 300)

**Reason**: Chained .get() calls with fallback logic

**Code:**
```python
tmp_hint = env_set.get("TMPDIR") or env_set.get("TMP") or env_set.get("TEMP")
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

### 2. adgn/src/adgn/mcp/policy_gateway/signals.py (Line 131)

**Reason**: Complex conditional expression with multiple .get() calls

**Code:**
```python
kind = _CODE_TO_KIND.get(code) if code is not None else _MSG_TO_KIND.get(msg)
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

### 3. gatelet/gatelet/server/endpoints/activitywatch.py (Line 55)

**Reason**: Chained .get() calls - walrus would reduce readability

**Code:**
```python
url = ev.get("data", {}).get("url")
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

### 4. gatelet/gatelet/server/endpoints/activitywatch.py (Line 61)

**Reason**: Chained .get() calls with default value

**Code:**
```python
status = ev.get("data", {}).get("status", "unknown")
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

### 5. homeassistant/iaqi/custom_components/indoor_aqi/sensor.py (Line 160)

**Reason**: Complex default value or chained .get() with fallback

**Code:**
```python
monitors = yaml_cfg.get("monitors", [])
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

### 6. wt/src/wt/shared/fixtures.py (Line 51)

**Reason**: Chained .get() calls with fallback (or operator)

**Code:**
```python
entry = fixtures.get(branch_name) or fixtures.get("*")
```

**Recommendation**: Keep current pattern. Walrus operator would reduce clarity.

## Implementation Guide

### When to Use Walrus Operator

✅ **Good candidates:**

```python
# Pattern 1: Simple truthiness check
value = dict.get(key)
if value:
    use(value)
→ if (value := dict.get(key)):
    use(value)

# Pattern 2: None check
value = dict.get(key)
if value is None:
    handle_missing()
→ if (value := dict.get(key)) is None:
    handle_missing()

# Pattern 3: Negation check
value = dict.get(key)
if not value:
    handle_missing()
→ if not (value := dict.get(key)):
    handle_missing()
```

### When NOT to Use Walrus Operator

❌ **Avoid in these cases:**

1. **Variable reuse**: Used outside the conditional block
   ```python
   value = data.get('key')
   if value:
       process(value)
   log(value)  # ← Used after if block
   ```

2. **Chained .get() calls**: Reduces readability
   ```python
   # Keep as-is, don't use walrus
   value = dict.get('key1').get('key2')
   if value:
       use(value)
   ```

3. **Complex conditions**: Multiple checks on same variable
   ```python
   value = data.get('key')
   if value is None:
       return default
   if not validate(value):
       return fallback
   return value
   ```

4. **Fallback chains**: Multiple .get() with or operator
   ```python
   # Keep as-is for clarity
   value = dict.get('a') or dict.get('b') or dict.get('c')
   ```

## Python Version Requirements

The walrus operator requires **Python 3.8+**.

Project uses **Python 3.12** as minimum (from AGENTS.md), so all refactorings are safe.

## Recommended Refactoring Process

1. **Start with HIGH priority violations**
   - These are safest to refactor with minimal risk
   - 8 items total

2. **Review MEDIUM priority violations**
   - Examine each file's context before refactoring
   - Use the checklist above to verify safety
   - 38 items total

3. **Skip LOW priority violations**
   - Keep current pattern for clarity
   - 6 items total

4. **Testing**
   - Run linter/formatter: `pre-commit run --all-files`
   - Run tests: `pytest` in affected module directories
   - Verify behavior unchanged

## Scan Methodology

This scan used the detection strategy defined in `prompts/scans/walrus-get-pattern.md`:

1. **Pattern Detection**: Searched for assignments matching `variable = dict.get(...)`
2. **Conditional Verification**: Verified immediate `if` statements using the variable
3. **Scope Analysis**: Checked if variable is only used in the immediate conditional
4. **Complexity Assessment**: Identified complex patterns unsuitable for walrus

## Statistics by Directory

| Directory | Count |
|-----------|-------|
| `adgn/` | 19 |
| `ember/` | 7 |
| `tana/` | 8 |
| `k8s/` | 3 |
| `gatelet/` | 4 |
| `homeassistant/` | 2 |
| `llm/` | 1 |
| `wt/` | 2 |
| `experimental/` | 2 |
| Others | 5 |
|  | **53 total** |

---

**Report Generated**: 2025-11-19
**Scan Tool**: walrus-get-pattern.md
**Repository**: ducktape
