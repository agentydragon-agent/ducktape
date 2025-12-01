# CLI App Refactoring Plan

## Current State (Before Refactoring)

```
cli_app/
├── decorators.py            25 lines  (utilities)
├── common_options.py        58 lines  (shared options)
├── shared.py               156 lines  (CLI utilities)
├── cmd_db.py               110 lines  (sync, db-recreate) ✓ DONE
├── cmd_detector.py         329 lines  (run-detector, detector-coverage) ✓ DONE
└── main.py                 844 lines  (17 commands remaining)
Total: 1,522 lines
```

## Target State (After Refactoring)

```
cli_app/
├── decorators.py            25 lines  (utilities)
├── common_options.py        58 lines  (shared options)
├── shared.py               189 lines  (CLI utilities + new helpers)
├── cmd_db.py               110 lines  ✓ DONE
├── cmd_detector.py         329 lines  ✓ DONE
├── cmd_analysis.py          75 lines  (check, lint-issue, cluster-unknowns)
├── cmd_fix.py               34 lines  (fix)
├── cmd_prompt.py            40 lines  (prompt-optimize, prompt-eval, eval-all)
├── cmd_specimen.py         280 lines  (5 specimen commands)
├── cmd_runtime.py          220 lines  (run, list-presets)
└── main.py                  50 lines  (app setup, registrations)
Total: ~1,410 lines
```

**Net change:** -112 lines (more focused modules, eliminated duplication)

---

## Extraction Plan (Recommended Order)

### 1. cmd_analysis.py (~75 lines) - FIRST

**Why first:** Smallest, cleanest extraction. No complex dependencies.

**Commands (3):**
- `check` (lines 105-139, 48 lines) - check path against properties
- `lint-issue` (lines 399-412, 14 lines) - lint issue definitions
- `cluster-unknowns` (lines 287-297, 11 lines) - cluster unknown findings

**Helpers needed:**
- `_load_preset_text` (lines 563-574) - load preset template by name
- `_render_prompt_with_context` (lines 429-450) - render prompt with docker wiring

**Dependencies:**
- Uses `save_prompt_to_tmp` from `shared.py`
- Uses `run_check_minicodex_async` from `shared.py`
- Uses `detect_tools` from `shared.py`
- Uses `cluster_unknowns` from `adgn.props.cluster_unknowns`
- Uses `run_specimen_lint_issue_async` from `adgn.props.lint_issue`

---

### 2. cmd_fix.py (~34 lines) - SECOND

**Why second:** Single standalone command. No shared helpers.

**Commands (1):**
- `fix` (lines 364-397, 34 lines) - refactor code to satisfy properties

**Dependencies:**
- Uses `BuildOptions`, `build_cmd` from `shared.py`
- Uses `build_enforce_prompt` from `adgn.props.prompts.builder`
- Uses `build_input_schemas_json` from `adgn.props.prompts.schemas`

---

### 3. cmd_prompt.py (~40 lines) - THIRD

**Why third:** Small, self-contained. Calls external modules.

**Commands (3):**
- `prompt-optimize` (lines 299-309, 11 lines) - optimize prompt
- `prompt-eval` (lines 311-332, 22 lines) - evaluate prompt
- `eval-all` (lines 414-417, 5 lines) - run all evaluations

**Dependencies:**
- Uses `run_prompt_optimizer` from `adgn.props.prompt_optimizer`
- Uses `grade_critique_by_id` from `adgn.props.grader`
- Uses `run_all_evals` from `adgn.props.eval_harness`

---

### 4. cmd_specimen.py (~280 lines) - FOURTH

**Why fourth:** Medium complexity, contains specimen-specific logic.

**Commands (5):**
- `specimen-discover` (lines 252-285, 34 lines) - discover new issues vs notes
- `specimen-grade` (lines 334-362, 29 lines) - grade critique by ID
- `specimen-dump` (lines 674-710, 37 lines) - dump specimen JSON
- `specimen-exec` (lines 712-765, 54 lines) - exec command in specimen container
- `capture-ducktape-specimen` (lines 767-845, 78 lines) - capture ducktape as specimen

**Helpers to move:**
- `_run_specimen_minicodex_async` (lines 192-249, 57 lines) - ONLY used by specimen-discover
- `read_embedded_paths` (lines 142-151, 9 lines) - embed files in prompt (shared with runtime)

**Note:** `read_embedded_paths` is also used by `cmd_runtime` (run command), so extract to `shared.py`.

---

### 5. cmd_runtime.py (~220 lines) - FIFTH (LAST)

**Why last:** Largest extraction. Most helper functions. Most complex dependencies.

**Commands (2):**
- `run` (lines 577-666, 90 lines) - unified runner (largest single command)
- `list-presets` (lines 668-672, 5 lines) - list available presets

**Helpers to move:**
- `_open_run_context` (lines 452-473, 21 lines) - open path or specimen context
- `_exec_agent` (lines 475-556, 81 lines) - execute MiniCodex agent
- `_print_presets` (lines 558-561, 3 lines) - print preset list

**Dependencies:**
- Uses `read_embedded_paths` (extract to `shared.py`)
- Uses `_load_preset_text` (extract to `shared.py`)
- Uses `_render_prompt_with_context` (extract to `shared.py`)

---

## Shared Utilities to Extract

### Move to `shared.py`:
1. `_load_preset_text` (12 lines) - used by check, run, specimen-discover
2. `_render_prompt_with_context` (21 lines) - used by check, run
3. `read_embedded_paths` (9 lines) - used by specimen-discover, run

**Total added to shared.py:** +42 lines (156 → 189)

### Consolidate Duplicates:
- `_filter_files` exists in both `main.py` and `cmd_detector.py`
  - Keep in `cmd_detector.py` (already there)
  - Remove from `main.py` (saves 35 lines)
  - Import from `cmd_detector` where needed (specimen-discover, run)

---

## Command Registration Pattern

**Before (inline decorators):**
```python
@app.command("check")
@async_run
async def cmd_check(...):
    ...
```

**After (import and register):**
```python
from adgn.props.cli_app.cmd_analysis import cmd_check, cmd_cluster_unknowns, cmd_lint_issue

app.command("check")(cmd_check)
app.command("cluster-unknowns")(cmd_cluster_unknowns)
app.command("lint-issue")(cmd_lint_issue)
```

---

## Testing Strategy

After each extraction:
1. Run `ruff check --fix` on modified files
2. Run `mypy --config-file pyproject.toml` on modified files
3. Test CLI: `python -c "from adgn.props.cli_app.main import app; from typer.testing import CliRunner; runner = CliRunner(); result = runner.invoke(app, ['--help']); print(result.output)"`
4. Verify all commands appear in help output

---

## Final main.py (~50 lines)

```python
"""Typer-based CLI entry for adgn-properties."""

from __future__ import annotations

import typer
from rich.traceback import install as rich_traceback_install

from adgn.llm.logging_config import configure_logging
from adgn.props.cli_app.cmd_analysis import cmd_check, cmd_cluster_unknowns, cmd_lint_issue
from adgn.props.cli_app.cmd_db import cmd_db_recreate, cmd_sync
from adgn.props.cli_app.cmd_detector import cmd_detector_coverage, cmd_run_detector
from adgn.props.cli_app.cmd_fix import cmd_fix
from adgn.props.cli_app.cmd_prompt import cmd_eval_all, cmd_prompt_eval, cmd_prompt_optimize
from adgn.props.cli_app.cmd_runtime import cmd_list_presets, cmd_run
from adgn.props.cli_app.cmd_specimen import (
    cmd_capture_ducktape_specimen,
    cmd_specimen_discover,
    cmd_specimen_dump,
    cmd_specimen_exec,
    cmd_specimen_grade,
)

app = typer.Typer(help="adgn-properties — properties tooling", add_completion=False)


@app.callback()
def _init_logging() -> None:
    configure_logging()
    rich_traceback_install(show_locals=False, max_frames=12, extra_lines=1, width=100)


# Database commands
app.command("sync")(cmd_sync)
app.command("db-recreate")(cmd_db_recreate)

# Detector commands
app.command("run-detector")(cmd_run_detector)
app.command("detector-coverage")(cmd_detector_coverage)

# Analysis commands
app.command("check")(cmd_check)
app.command("lint-issue")(cmd_lint_issue)
app.command("cluster-unknowns")(cmd_cluster_unknowns)

# Fix command
app.command("fix")(cmd_fix)

# Prompt commands
app.command("prompt-optimize")(cmd_prompt_optimize)
app.command("prompt-eval")(cmd_prompt_eval)
app.command("eval-all")(cmd_eval_all)

# Specimen commands
app.command("specimen-discover")(cmd_specimen_discover)
app.command("specimen-grade")(cmd_specimen_grade)
app.command("specimen-dump")(cmd_specimen_dump)
app.command("specimen-exec")(cmd_specimen_exec)
app.command("capture-ducktape-specimen")(cmd_capture_ducktape_specimen)

# Runtime commands
app.command("run")(cmd_run)
app.command("list-presets")(cmd_list_presets)
```

---

## Benefits

1. **Clear organization:** Command grouped by domain (analysis, specimen, runtime, etc.)
2. **Easier navigation:** Find commands by logical grouping, not alphabetical order
3. **Better testing:** Test command groups in isolation
4. **Reduced duplication:** Shared helpers extracted once to `shared.py`
5. **Simpler main.py:** Just app setup and registrations (~50 lines vs 844)

---

## Risks and Mitigations

**Risk:** Breaking existing imports/tests
**Mitigation:** No external modules import commands directly; only `main.py` does

**Risk:** Circular imports between cmd_* modules
**Mitigation:** Commands don't import from each other; shared code goes to `shared.py`

**Risk:** Helper function placement ambiguity
**Mitigation:**
- Used by 1 command → keep in that cmd_*.py
- Used by 2+ commands → extract to `shared.py`

---

## Progress Tracking

- [x] cmd_db.py (sync, db-recreate)
- [x] cmd_detector.py (run-detector, detector-coverage)
- [ ] cmd_analysis.py (check, lint-issue, cluster-unknowns) — NEXT
- [ ] cmd_fix.py (fix)
- [ ] cmd_prompt.py (prompt-optimize, prompt-eval, eval-all)
- [ ] cmd_specimen.py (5 specimen commands)
- [ ] cmd_runtime.py (run, list-presets)
- [ ] Finalize main.py (~50 lines)
