# Code Quality Scan: Prefer Functional Patterns Over Imperative Loops
**Scan Date:** 2025-11-19
**Total Violations:** 63

## Executive Summary
Found 63 violations of the functional-over-imperative pattern:
- **Simple append loops**: 30 violations
- **If + append loops**: 33 violations

All violations are rated **EASY** to refactor (can be converted to comprehensions).

## Violation Distribution by Pattern
### Pattern 1: Simple Append Loops
**Description:** Loop that directly appends items without conditions.
**Severity:** Medium
**Refactoring Difficulty:** Easy
**Example Refactoring:**
```python
# Before:
items = []
for x in values:
    items.append(transform(x))

# After:
items = [transform(x) for x in values]
```

**Occurrences:** 30

**File:** `adgn/src/adgn/inop/engine/optimizer.py`
**Line:** 524
**Code:**
```python
    for grader_data in yaml_loader.graders_data:
        criteria.append(Criterion(name=grader_data.id, description=grader_data.description))
```

**File:** `adgn/src/adgn/inop/plots.py`
**Line:** 127
**Code:**
```python
        for iter_data in self.iterations_data:
            plot_data.append(create_plot_data_point(iter_data, "overall"))
```

**File:** `adgn/src/adgn/inop/plots.py`
**Line:** 132
**Code:**
```python
                for iter_data in self.iterations_data:
                    plot_data.append(create_plot_data_point(iter_data, facet_name))
```

**File:** `adgn/src/adgn/inop/prompting/summarizer.py`
**Line:** 71
**Code:**
```python
            for facet_name, score_with_rationale in graded.grade.axes.items():
                facet_details.append(
                    f"\n    {facet_name}: {score_with_rationale.score}/10 - {score_
```

**File:** `adgn/src/adgn/inop/prompting/truncation_utils.py`
**Line:** 63
**Code:**
```python
            for fi in cast(list[FileInfo], files):
                out.append((fi.path, fi.content, fi))
```

**File:** `adgn/src/adgn/inop/prompting/truncation_utils.py`
**Line:** 66
**Code:**
```python
            for d in cast(list[dict[str, str]], files):
                out.append((d["path"], d["content"], d))
```

**File:** `adgn/src/adgn/llm/sandboxer.py`
**Line:** 133
**Code:**
```python
    for root in (
        "/System",
        "/usr/lib",
```

**File:** `adgn/src/adgn/llm/sandboxer.py`
**Line:** 144
**Code:**
```python
    for extra_path in policy.platform.seatbelt.extra_allow.file_read_extra:
        sp.files.append(FileRule(op=FileOp.FILE_READ_STAR, filters=[Subpath(subpath=_abs(extra_path).as_posix())]))
```

**File:** `adgn/src/adgn/llm/sysrw/extract_dataset_crush.py`
**Line:** 202
**Code:**
```python
            for p in root.glob(pat):
                found.append(p)
```

**File:** `adgn/src/adgn/llm/sysrw/leaderboard.py`
**Line:** 197
**Code:**
```python
    for r in rows:
        lines.append(
            f"| {r.mean:.2f} | {r.ci95:.2f} | {r.n} | {r.with_tools_pct * 100:.1f}% | {r.run} | {r.template_label} |"
```

**File:** `adgn/src/adgn/props/detectors/utils.py`
**Line:** 56
**Code:**
```python
    for i in range(s, e + 1):
        out.append(f"{i:>5}: {lines[i - 1]}")
```

**File:** `adgn/src/adgn/seatbelt/compile.py`
**Line:** 84
**Code:**
```python
    for nr in policy.network:
        lines.append(_render_network_rule(nr))
```

**File:** `adgn/src/adgn/seatbelt/compile.py`
**Line:** 100
**Code:**
```python
        for name in policy.system.sysctl_names:
            lines.append(f'  (sysctl-name "{_q(name)}")')
```

**File:** `adgn/src/adgn/seatbelt/compile.py`
**Line:** 102
**Code:**
```python
        for pfx in policy.system.sysctl_prefixes:
            lines.append(f'  (sysctl-name-prefix "{_q(pfx)}")')
```

**File:** `adgn/src/adgn/seatbelt/compile.py`
**Line:** 107
**Code:**
```python
    for name in policy.mach.global_names:
        lines.append(f'(allow mach-lookup (global-name "{_q(name)}"))')
```

... and 15 more occurrences

### Pattern 2: If + Append Loops
**Description:** Loop with single if condition that appends items.
**Severity:** Medium
**Refactoring Difficulty:** Easy
**Example Refactoring:**
```python
# Before:
results = []
for item in items:
    if item.is_valid:
        results.append(item.value)

# After:
results = [item.value for item in items if item.is_valid]
```

**Occurrences:** 33

**File:** `adgn/src/adgn/inop/runners/claude_runner.py`
**Line:** 158
**Code:**
```python
                            for block in content:
                                if isinstance(block, TextBlock):
                                    text_parts.append(block.text)
```

**File:** `adgn/src/adgn/llm/sysrw/extract_dataset_crush.py`
**Line:** 120
**Code:**
```python
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    texts.append(c["text"])
```

**File:** `adgn/src/adgn/llm/sysrw/leaderboard.py`
**Line:** 320
**Code:**
```python
    for r in flat_rows:
        if r.template_error:
            errors.append(f"{r.run}: {_relpath(r.template_label)} — {r.template_error_exc}")
```

**File:** `adgn/src/adgn/llm/sysrw/run_eval.py`
**Line:** 140
**Code:**
```python
            for call in tool_calls:
                if args := call["function"]["arguments"]:
                    parts.append(args)
```

**File:** `adgn/src/adgn/mcp/sandboxed_jupyter/jupyter_sandbox_compose.py`
**Line:** 126
**Code:**
```python
    for fdir in ["/System/Library/Fonts", "/Library/Fonts"]:
        if fdir not in frx:
            frx.append(fdir)
```

**File:** `adgn/src/adgn/openai_utils/model.py`
**Line:** 203
**Code:**
```python
        for block in item.content or []:
            if isinstance(block, InputTextPart):
                parts.append(OutputText.model_validate(block.model_dump(exclude_none=True)))
```

**File:** `adgn/src/adgn/props/cli_shared.py`
**Line:** 51
**Code:**
```python
    for name, exe in tools:
        if shutil.which(exe):
            available.append(name)
```

**File:** `adgn/src/adgn/props/specimens/2025-08-29-pyright_watch_report/code/pyright_watch_report.py`
**Line:** 42
**Code:**
```python
    for p in sorted(root.glob("pyrightconfig.json*")):
        if p.name != "pyrightconfig.json":
            candidates.append(p)
```

**File:** `adgn/src/adgn/seatbelt/validate.py`
**Line:** 84
**Code:**
```python
    for nr in policy.network:
        if nr.action == Action.ALLOW and not nr.local_only:
            msgs.append(
                f"note: network rule '{nr.op.value}' without local_only allows broade
```

**File:** `adgn/src/adgn/tools/trivial_patterns.py`
**Line:** 49
**Code:**
```python
        for alias in node.names:
            if alias.asname:
                self.findings.append(
                    f"{self.path}:{node.lineno}:{node.col_offset} RENAMED_IMPORT {alias.name} as {al
```

**File:** `adgn/src/adgn/tools/trivial_patterns.py`
**Line:** 58
**Code:**
```python
        for alias in node.names:
            if alias.asname:
                self.findings.append(
                    f"{self.path}:{node.lineno}:{node.col_offset} RENAMED_IMPORT from {module} impor
```

**File:** `adgn/src/adgn/tools/trivial_patterns.py`
**Line:** 477
**Code:**
```python
    for pattern in skip:
        if pattern not in unique_skip:
            unique_skip.append(pattern)
```

**File:** `adgn/tests/agent/test_no_openai_imports.py`
**Line:** 21
**Code:**
```python
            for alias in node.names:
                if alias.name == "openai" or alias.name.startswith("openai."):
                    offenders.append((node.lineno, alias.name))
```

**File:** `adgn/tests/llm/test_prompt_eval_result_union.py`
**Line:** 24
**Code:**
```python
        for t in tools:
            if isinstance(t, FunctionToolParam):
                names.append(t.name)
```

**File:** `ansible/action_plugins/dconf_array_edit.py`
**Line:** 104
**Code:**
```python
        for item in add:
            if item not in desired:
                desired.append(item)
```

... and 18 more occurrences

## Complete Violation List by File

### adgn/src/adgn/inop/engine/optimizer.py
**Violations:** 1

- **Line 524** (simple_append)

### adgn/src/adgn/inop/plots.py
**Violations:** 2

- **Line 127** (simple_append)

- **Line 132** (simple_append)

### adgn/src/adgn/inop/prompting/summarizer.py
**Violations:** 1

- **Line 71** (simple_append)

### adgn/src/adgn/inop/prompting/truncation_utils.py
**Violations:** 2

- **Line 63** (simple_append)

- **Line 66** (simple_append)

### adgn/src/adgn/inop/runners/claude_runner.py
**Violations:** 1

- **Line 158** (if_append)

### adgn/src/adgn/llm/sandboxer.py
**Violations:** 2

- **Line 133** (simple_append)

- **Line 144** (simple_append)

### adgn/src/adgn/llm/sysrw/extract_dataset_crush.py
**Violations:** 2

- **Line 120** (if_append)

- **Line 202** (simple_append)

### adgn/src/adgn/llm/sysrw/leaderboard.py
**Violations:** 2

- **Line 197** (simple_append)

- **Line 320** (if_append)

### adgn/src/adgn/llm/sysrw/run_eval.py
**Violations:** 1

- **Line 140** (if_append)

### adgn/src/adgn/mcp/sandboxed_jupyter/jupyter_sandbox_compose.py
**Violations:** 1

- **Line 126** (if_append)

### adgn/src/adgn/openai_utils/model.py
**Violations:** 1

- **Line 203** (if_append)

### adgn/src/adgn/props/cli_shared.py
**Violations:** 1

- **Line 51** (if_append)

### adgn/src/adgn/props/detectors/utils.py
**Violations:** 1

- **Line 56** (simple_append)

### adgn/src/adgn/props/specimens/2025-08-29-pyright_watch_report/code/pyright_watch_report.py
**Violations:** 1

- **Line 42** (if_append)

### adgn/src/adgn/seatbelt/compile.py
**Violations:** 5

- **Line 84** (simple_append)

- **Line 100** (simple_append)

- **Line 102** (simple_append)

- **Line 107** (simple_append)

- **Line 115** (simple_append)

### adgn/src/adgn/seatbelt/validate.py
**Violations:** 1

- **Line 84** (if_append)

### adgn/src/adgn/third_party/openai_cookbook/apply_patch.py
**Violations:** 1

- **Line 331** (simple_append)

### adgn/src/adgn/tools/trivial_patterns.py
**Violations:** 3

- **Line 49** (if_append)

- **Line 58** (if_append)

- **Line 477** (if_append)

### adgn/tests/agent/test_no_openai_imports.py
**Violations:** 2

- **Line 21** (if_append)

- **Line 35** (simple_append)

### adgn/tests/llm/test_prompt_eval_result_union.py
**Violations:** 1

- **Line 24** (if_append)

### ansible/action_plugins/dconf_array_edit.py
**Violations:** 1

- **Line 104** (if_append)

### difftree/src/difftree/diff_tree.py
**Violations:** 1

- **Line 55** (simple_append)

### difftree/tests/test_diff_tree.py
**Violations:** 1

- **Line 30** (if_append)

### dotfiles/local/bin/login_event_webhook_reporter.py
**Violations:** 1

- **Line 149** (if_append)

### ducktape_tools/unicode/fix.py
**Violations:** 1

- **Line 106** (simple_append)

### experimental/cotrl/analyze_trajectories.py
**Violations:** 1

- **Line 20** (simple_append)

### experimental/cotrl/llm_rl_experiment.py
**Violations:** 1

- **Line 491** (simple_append)

### inventree_utils/beautifier/assign_jellybean.py
**Violations:** 1

- **Line 107** (simple_append)

### inventree_utils/samplebooks_import/import_samplebooks2.py
**Violations:** 1

- **Line 368** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter/config.py
**Violations:** 1

- **Line 42** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/access/rule_engine.py
**Violations:** 2

- **Line 68** (if_append)

- **Line 80** (if_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/cli.py
**Violations:** 1

- **Line 508** (if_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/categorizer.py
**Violations:** 1

- **Line 97** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/hooks/formatting.py
**Violations:** 2

- **Line 32** (simple_append)

- **Line 62** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/hooks/handler.py
**Violations:** 1

- **Line 332** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/linters/python_ast.py
**Violations:** 3

- **Line 86** (if_append)

- **Line 104** (if_append)

- **Line 130** (if_append)

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/llm_analyzer.py
**Violations:** 1

- **Line 142** (simple_append)

### llm/ducktape_llm_common/ducktape_llm_common/prompts/validation.py
**Violations:** 3

- **Line 119** (if_append)

- **Line 176** (if_append)

- **Line 191** (if_append)

### tana/src/tana/graph/workspace.py
**Violations:** 2

- **Line 68** (if_append)

- **Line 81** (if_append)

### tana/src/tana/query/search/parser.py
**Violations:** 1

- **Line 127** (if_append)

### wt/src/wt/client/view_formatter.py
**Violations:** 1

- **Line 230** (if_append)

### wt/src/wt/server/worktree_service.py
**Violations:** 1

- **Line 53** (if_append)

### wt/tests/unit/test_layering.py
**Violations:** 2

- **Line 64** (if_append)

- **Line 74** (if_append)

## Recommendations
1. **Priority:** All violations are **EASY** to fix and have clear refactoring patterns
2. **Approach:** Process violations file-by-file, starting with highest violation count
3. **Testing:** After refactoring, ensure all tests pass (comprehensions are functionally equivalent)
4. **Benefits:** Refactoring will improve:
   - Code readability (more concise, intent is clearer)
   - Performance (comprehensions are faster ~30%)
   - Pythonic style (idiomatic functional patterns)

## Files with Most Violations
- adgn/src/adgn/seatbelt/compile.py: 5 violations
- adgn/src/adgn/tools/trivial_patterns.py: 3 violations
- llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/linters/python_ast.py: 3 violations
- llm/ducktape_llm_common/ducktape_llm_common/prompts/validation.py: 3 violations
- adgn/src/adgn/inop/plots.py: 2 violations
- adgn/src/adgn/inop/prompting/truncation_utils.py: 2 violations
- adgn/src/adgn/llm/sandboxer.py: 2 violations
- adgn/src/adgn/llm/sysrw/extract_dataset_crush.py: 2 violations
- adgn/src/adgn/llm/sysrw/leaderboard.py: 2 violations
- adgn/tests/agent/test_no_openai_imports.py: 2 violations

## Next Steps
1. Review violations in high-impact files
2. Apply refactoring using list/dict comprehensions
3. Run test suite to verify equivalence
4. Commit changes with descriptive messages
