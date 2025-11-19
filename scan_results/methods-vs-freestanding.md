# Code Quality Scan Report: Methods vs Freestanding Functions

**Scan Date:** 2025-11-19  
**Total Violations Found:** 93

## Executive Summary

This scan identifies functions that should be converted to class methods or instance methods based on the patterns defined in `prompts/scans/methods-vs-freestanding.md`. The analysis covers 65 Python files across the repository, excluding test files.

### Violation Breakdown

| Category | Count | Status |
|----------|-------|--------|
| Factory Pattern | 10 | High Priority |
| State Modifying | 12 | Medium Priority |
| Tight Coupling | 71 | Medium-High Priority |
| **Total** | **93** | - |

---

## 1. Factory Pattern Violations (10 found)

### Overview

Functions that follow the factory pattern (`make_X`, `create_X`, `from_X`, `build_X`, `resolve_X`, `parse_X`) should be implemented as `@classmethod` on the class they construct. This provides:

- **Discoverability**: IDE autocomplete shows methods when typing `ClassName.`
- **Clear Ownership**: The method syntactically belongs to the class
- **Inheritance**: Subclasses can override factory behavior
- **Namespace Cleanliness**: No module-level namespace pollution

### Violations


#### create_grading_strategy → GradingStrategy

**Location:** `adgn/src/adgn/inop/grading/strategies.py:247`

**Current:** Freestanding function `create_grading_strategy`  
**Should be:** `@classmethod create_grading_strategy` on class `GradingStrategy`

**Parameters:** grading_config, config_path

**Fix Pattern:**
```python
# BEFORE
def create_grading_strategy(grading_config, config_path) -> GradingStrategy:
    # Implementation
    return GradingStrategy(...)

# AFTER
class GradingStrategy:
    @classmethod
    def create_grading_strategy(cls, grading_config, config_path):
        # Implementation
        return cls(...)

# Usage: GradingStrategy.create_grading_strategy(...)
```


#### create_optimizer_models → OptimizerModels

**Location:** `adgn/src/adgn/inop/model_factory.py:26`

**Current:** Freestanding function `create_optimizer_models`  
**Should be:** `@classmethod create_optimizer_models` on class `OptimizerModels`

**Parameters:** cfg

**Fix Pattern:**
```python
# BEFORE
def create_optimizer_models(cfg) -> OptimizerModels:
    # Implementation
    return OptimizerModels(...)

# AFTER
class OptimizerModels:
    @classmethod
    def create_optimizer_models(cls, cfg):
        # Implementation
        return cls(...)

# Usage: OptimizerModels.create_optimizer_models(...)
```


#### create_plot_data_point → PlotDataPoint

**Location:** `adgn/src/adgn/inop/plots.py:61`

**Current:** Freestanding function `create_plot_data_point`  
**Should be:** `@classmethod create_plot_data_point` on class `PlotDataPoint`

**Parameters:** iter_data, facet_name

**Fix Pattern:**
```python
# BEFORE
def create_plot_data_point(iter_data, facet_name) -> PlotDataPoint:
    # Implementation
    return PlotDataPoint(...)

# AFTER
class PlotDataPoint:
    @classmethod
    def create_plot_data_point(cls, iter_data, facet_name):
        # Implementation
        return cls(...)

# Usage: PlotDataPoint.create_plot_data_point(...)
```


#### build_status_page → StatusPage

**Location:** `adgn/src/adgn/mcp/git_ro/formatting.py:79`

**Current:** Freestanding function `build_status_page`  
**Should be:** `@classmethod build_status_page` on class `StatusPage`

**Parameters:** entries, slicer

**Fix Pattern:**
```python
# BEFORE
def build_status_page(entries, slicer) -> StatusPage:
    # Implementation
    return StatusPage(...)

# AFTER
class StatusPage:
    @classmethod
    def build_status_page(cls, entries, slicer):
        # Implementation
        return cls(...)

# Usage: StatusPage.build_status_page(...)
```


#### build_changed_files_page → ChangedFilesPage

**Location:** `adgn/src/adgn/mcp/git_ro/formatting.py:122`

**Current:** Freestanding function `build_changed_files_page`  
**Should be:** `@classmethod build_changed_files_page` on class `ChangedFilesPage`

**Parameters:** items, slicer

**Fix Pattern:**
```python
# BEFORE
def build_changed_files_page(items, slicer) -> ChangedFilesPage:
    # Implementation
    return ChangedFilesPage(...)

# AFTER
class ChangedFilesPage:
    @classmethod
    def build_changed_files_page(cls, items, slicer):
        # Implementation
        return cls(...)

# Usage: ChangedFilesPage.build_changed_files_page(...)
```


#### build_diff_stat_page → DiffStatPage

**Location:** `adgn/src/adgn/mcp/git_ro/formatting.py:165`

**Current:** Freestanding function `build_diff_stat_page`  
**Should be:** `@classmethod build_diff_stat_page` on class `DiffStatPage`

**Parameters:** items, slicer

**Fix Pattern:**
```python
# BEFORE
def build_diff_stat_page(items, slicer) -> DiffStatPage:
    # Implementation
    return DiffStatPage(...)

# AFTER
class DiffStatPage:
    @classmethod
    def build_diff_stat_page(cls, items, slicer):
        # Implementation
        return cls(...)

# Usage: DiffStatPage.build_diff_stat_page(...)
```


#### build_reasoning_params → ReasoningParams

**Location:** `adgn/src/adgn/openai_utils/types.py:23`

**Current:** Freestanding function `build_reasoning_params`  
**Should be:** `@classmethod build_reasoning_params` on class `ReasoningParams`

**Parameters:** effort, summary

**Fix Pattern:**
```python
# BEFORE
def build_reasoning_params(effort, summary) -> ReasoningParams:
    # Implementation
    return ReasoningParams(...)

# AFTER
class ReasoningParams:
    @classmethod
    def build_reasoning_params(cls, effort, summary):
        # Implementation
        return cls(...)

# Usage: ReasoningParams.build_reasoning_params(...)
```


#### create_profile → Profile

**Location:** `ansible/roles/gnome_terminal_solarized/tasks/apply.py:92`

**Current:** Freestanding function `create_profile`  
**Should be:** `@classmethod create_profile` on class `Profile`

**Parameters:** self

**Fix Pattern:**
```python
# BEFORE
def create_profile(self) -> Profile:
    # Implementation
    return Profile(...)

# AFTER
class Profile:
    @classmethod
    def create_profile(cls, self):
        # Implementation
        return cls(...)

# Usage: Profile.create_profile(...)
```


#### create_error_response → ErrorResponse

**Location:** `wt/src/wt/shared/protocol.py:469`

**Current:** Freestanding function `create_error_response`  
**Should be:** `@classmethod create_error_response` on class `ErrorResponse`

**Parameters:** code, message, request_id, data

**Fix Pattern:**
```python
# BEFORE
def create_error_response(code, message, request_id, data) -> ErrorResponse:
    # Implementation
    return ErrorResponse(...)

# AFTER
class ErrorResponse:
    @classmethod
    def create_error_response(cls, code, message, request_id, data):
        # Implementation
        return cls(...)

# Usage: ErrorResponse.create_error_response(...)
```


#### parse_request → Request

**Location:** `wt/src/wt/shared/protocol.py:475`

**Current:** Freestanding function `parse_request`  
**Should be:** `@classmethod parse_request` on class `Request`

**Parameters:** data

**Fix Pattern:**
```python
# BEFORE
def parse_request(data) -> Request:
    # Implementation
    return Request(...)

# AFTER
class Request:
    @classmethod
    def parse_request(cls, data):
        # Implementation
        return cls(...)

# Usage: Request.parse_request(...)
```


---

## 2. State Modifying Violations (12 found)

### Overview

Functions that modify the state of an instance passed as a parameter should be implemented as instance methods. This improves:

- **Encapsulation**: State modifications are internal to the class
- **Clarity**: Method names suggest the operation (e.g., `ctx.set_response_id(...)`)
- **Cohesion**: Behavior and state live together
- **Discoverability**: Methods appear in IDE autocomplete

### Violations


#### update_tool_decision modifies state

**Location:** `adgn/src/adgn/agent/server/state.py:116`

**Current:** Modifies instance parameter `state`  
**Should be:** Instance method on class of `state`

**Fix Pattern:**
```python
# BEFORE
def update_tool_decision(state: SomeClass, ...):
    state.field = value

# AFTER
class SomeClass:
    def update_tool_decision(self, ...):
        self.field = value

# Usage: state.update_tool_decision(...)
```


#### update_tool_exec_stream modifies state

**Location:** `adgn/src/adgn/agent/server/state.py:128`

**Current:** Modifies instance parameter `state`  
**Should be:** Instance method on class of `state`

**Fix Pattern:**
```python
# BEFORE
def update_tool_exec_stream(state: SomeClass, ...):
    state.field = value

# AFTER
class SomeClass:
    def update_tool_exec_stream(self, ...):
        self.field = value

# Usage: state.update_tool_exec_stream(...)
```


#### update_tool_json_output modifies state

**Location:** `adgn/src/adgn/agent/server/state.py:159`

**Current:** Modifies instance parameter `state`  
**Should be:** Instance method on class of `state`

**Fix Pattern:**
```python
# BEFORE
def update_tool_json_output(state: SomeClass, ...):
    state.field = value

# AFTER
class SomeClass:
    def update_tool_json_output(self, ...):
        self.field = value

# Usage: state.update_tool_json_output(...)
```


#### delete_line modifies input

**Location:** `adgn/src/adgn/mcp/editor_server.py:198`

**Current:** Modifies instance parameter `input`  
**Should be:** Instance method on class of `input`

**Fix Pattern:**
```python
# BEFORE
def delete_line(input: SomeClass, ...):
    input.field = value

# AFTER
class SomeClass:
    def delete_line(self, ...):
        self.field = value

# Usage: input.delete_line(...)
```


#### add_line_after modifies input

**Location:** `adgn/src/adgn/mcp/editor_server.py:208`

**Current:** Modifies instance parameter `input`  
**Should be:** Instance method on class of `input`

**Fix Pattern:**
```python
# BEFORE
def add_line_after(input: SomeClass, ...):
    input.field = value

# AFTER
class SomeClass:
    def add_line_after(self, ...):
        self.field = value

# Usage: input.add_line_after(...)
```


#### remove_file modifies path

**Location:** `adgn/src/adgn/third_party/openai_cookbook/apply_patch.py:416`

**Current:** Modifies instance parameter `path`  
**Should be:** Instance method on class of `path`

**Fix Pattern:**
```python
# BEFORE
def remove_file(path: SomeClass, ...):
    path.field = value

# AFTER
class SomeClass:
    def remove_file(self, ...):
        self.field = value

# Usage: path.remove_file(...)
```


#### add_mcp_server modifies config

**Location:** `ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py:80`

**Current:** Modifies instance parameter `config`  
**Should be:** Instance method on class of `config`

**Fix Pattern:**
```python
# BEFORE
def add_mcp_server(config: SomeClass, ...):
    config.field = value

# AFTER
class SomeClass:
    def add_mcp_server(self, ...):
        self.field = value

# Usage: config.add_mcp_server(...)
```


#### update_mcp_server modifies config

**Location:** `ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py:92`

**Current:** Modifies instance parameter `config`  
**Should be:** Instance method on class of `config`

**Fix Pattern:**
```python
# BEFORE
def update_mcp_server(config: SomeClass, ...):
    config.field = value

# AFTER
class SomeClass:
    def update_mcp_server(self, ...):
        self.field = value

# Usage: config.update_mcp_server(...)
```


#### set_hook_context modifies invocation_id

**Location:** `claude/claude_hooks/claude_hooks/logging_context.py:31`

**Current:** Modifies instance parameter `invocation_id`  
**Should be:** Instance method on class of `invocation_id`

**Fix Pattern:**
```python
# BEFORE
def set_hook_context(invocation_id: SomeClass, ...):
    invocation_id.field = value

# AFTER
class SomeClass:
    def set_hook_context(self, ...):
        self.field = value

# Usage: invocation_id.set_hook_context(...)
```


#### add_external_to_gnucash modifies external_transaction

**Location:** `finance/reconcile/reconcile.py:98`

**Current:** Modifies instance parameter `external_transaction`  
**Should be:** Instance method on class of `external_transaction`

**Fix Pattern:**
```python
# BEFORE
def add_external_to_gnucash(external_transaction: SomeClass, ...):
    external_transaction.field = value

# AFTER
class SomeClass:
    def add_external_to_gnucash(self, ...):
        self.field = value

# Usage: external_transaction.add_external_to_gnucash(...)
```


#### remove_prefix modifies x

**Location:** `inventree_utils/rai_plugin/templatetags/custom_tags.py:48`

**Current:** Modifies instance parameter `x`  
**Should be:** Instance method on class of `x`

**Fix Pattern:**
```python
# BEFORE
def remove_prefix(x: SomeClass, ...):
    x.field = value

# AFTER
class SomeClass:
    def remove_prefix(self, ...):
        self.field = value

# Usage: x.remove_prefix(...)
```


#### set_part_parameter modifies prt

**Location:** `inventree_utils/samplebooks_import/import_samplebooks2.py:292`

**Current:** Modifies instance parameter `prt`  
**Should be:** Instance method on class of `prt`

**Fix Pattern:**
```python
# BEFORE
def set_part_parameter(prt: SomeClass, ...):
    prt.field = value

# AFTER
class SomeClass:
    def set_part_parameter(self, ...):
        self.field = value

# Usage: prt.set_part_parameter(...)
```


---

## 3. Tight Coupling Violations (71 found)

### Overview

Functions that access 3 or more fields from an instance parameter exhibit tight coupling and should be converted to instance methods. Benefits:

- **Simpler Signatures**: No need to pass the instance and its fields
- **Encapsulation**: Implementation details hidden from callers
- **Maintainability**: Changes to coupling don't affect call sites
- **Cohesion**: Related data and behavior in one place

### Sample Violations (first 30 of 71)


#### _convert_tool_call_record_to_history accesses 3 fields of record

**Location:** `adgn/src/adgn/agent/mcp_bridge/servers/agents.py:57`

**Current:** Function accesses `record.` (3 times)  
**Fields accessed:** call_id, decision, tool_call

**Recommendation:** Convert to instance method on class of `record`


#### load_presets_from_dir accesses 3 fields of root

**Location:** `adgn/src/adgn/agent/presets.py:41`

**Current:** Function accesses `root.` (3 times)  
**Fields accessed:** exists, glob, is_dir

**Recommendation:** Convert to instance method on class of `root`


#### _build_amend_diff accesses 3 fields of repo

**Location:** `adgn/src/adgn/git_commit_ai/cli.py:128`

**Current:** Function accesses `repo.` (3 times)  
**Fields accessed:** TreeBuilder, diff, head

**Recommendation:** Convert to instance method on class of `repo`


#### build_commit_template accesses 3 fields of repo

**Location:** `adgn/src/adgn/git_commit_ai/editor_template.py:21`

**Current:** Function accesses `repo.` (3 times)  
**Fields accessed:** config, head, head_is_detached

**Recommendation:** Convert to instance method on class of `repo`


#### create_grading_strategy accesses 3 fields of grading_config

**Location:** `adgn/src/adgn/inop/grading/strategies.py:247`

**Current:** Function accesses `grading_config.` (3 times)  
**Fields accessed:** criteria, criteria_file, reference

**Recommendation:** Convert to instance method on class of `grading_config`


#### make_prompt_feedback_server_with_state accesses 3 fields of deps

**Location:** `adgn/src/adgn/inop/mcp/prompt_feedback_server.py:31`

**Current:** Function accesses `deps.` (3 times)  
**Fields accessed:** persist_all, run_rollouts_with_prompt, select_seed_tasks

**Recommendation:** Convert to instance method on class of `deps`


#### create_optimizer_models accesses 3 fields of cfg

**Location:** `adgn/src/adgn/inop/model_factory.py:26`

**Current:** Function accesses `cfg.` (3 times)  
**Fields accessed:** grader, prompt_engineer, summarizer

**Recommendation:** Convert to instance method on class of `cfg`


#### create_plot_data_point accesses 3 fields of iter_data

**Location:** `adgn/src/adgn/inop/plots.py:61`

**Current:** Function accesses `iter_data.` (3 times)  
**Fields accessed:** facets, iteration, overall

**Recommendation:** Convert to instance method on class of `iter_data`


#### _compose_sbpl accesses 3 fields of policy

**Location:** `adgn/src/adgn/llm/sandboxer.py:104`

**Current:** Function accesses `policy.` (3 times)  
**Fields accessed:** fs, net, platform

**Recommendation:** Convert to instance method on class of `policy`


#### _row_key accesses 4 fields of r

**Location:** `adgn/src/adgn/llm/sysrw/leaderboard.py:296`

**Current:** Function accesses `r.` (4 times)  
**Fields accessed:** ci95, lcb, mean, ... (4 total)

**Recommendation:** Convert to instance method on class of `r`


#### _derive_ci_from_summary accesses 4 fields of summary

**Location:** `adgn/src/adgn/llm/sysrw/leaderboard.py:364`

**Current:** Function accesses `summary.` (4 times)  
**Fields accessed:** ci95, lcb, mean, ... (4 total)

**Recommendation:** Convert to instance method on class of `summary`


#### validate_template_file accesses 3 fields of template_path

**Location:** `adgn/src/adgn/llm/sysrw/templates/__init__.py:44`

**Current:** Function accesses `template_path.` (3 times)  
**Fields accessed:** exists, is_file, read_text

**Recommendation:** Convert to instance method on class of `template_path`


#### convert_fastmcp_result accesses 3 fields of res

**Location:** `adgn/src/adgn/mcp/_shared/calltool.py:38`

**Current:** Function accesses `res.` (3 times)  
**Fields accessed:** content, is_error, structured_content

**Recommendation:** Convert to instance method on class of `res`


#### make_container_lifespan accesses 5 fields of opts

**Location:** `adgn/src/adgn/mcp/_shared/container_session.py:102`

**Current:** Function accesses `opts.` (5 times)  
**Fields accessed:** ephemeral, image, network_mode, ... (5 total)

**Recommendation:** Convert to instance method on class of `opts`


#### _transfer_mcp_metadata accesses 3 fields of target

**Location:** `adgn/src/adgn/mcp/_shared/fastmcp_flat.py:174`

**Current:** Function accesses `target.` (3 times)  
**Fields accessed:** __signature__, _mcp_flat_input_model, _mcp_flat_output_model

**Recommendation:** Convert to instance method on class of `target`


#### render_outcome_to_result accesses 3 fields of outcome

**Location:** `adgn/src/adgn/mcp/exec/models.py:217`

**Current:** Function accesses `outcome.` (3 times)  
**Fields accessed:** duration_ms, exit, output

**Recommendation:** Convert to instance method on class of `outcome`


#### _done_result accesses 4 fields of t

**Location:** `adgn/src/adgn/mcp/exec/seatbelt.py:181`

**Current:** Function accesses `t.` (4 times)  
**Fields accessed:** cancelled, done, exception, ... (4 total)

**Recommendation:** Convert to instance method on class of `t`


#### git_log accesses 4 fields of input

**Location:** `adgn/src/adgn/mcp/git_ro/server.py:298`

**Current:** Function accesses `input.` (4 times)  
**Fields accessed:** max_count, oneline, rev, ... (4 total)

**Recommendation:** Convert to instance method on class of `input`


#### git_log_entries accesses 4 fields of input

**Location:** `adgn/src/adgn/mcp/git_ro/server.py:325`

**Current:** Function accesses `input.` (4 times)  
**Fields accessed:** include_message, limit, offset, ... (4 total)

**Recommendation:** Convert to instance method on class of `input`


#### _parse_text_event accesses 5 fields of event

**Location:** `adgn/src/adgn/mcp/matrix/server.py:106`

**Current:** Function accesses `event.` (5 times)  
**Fields accessed:** content, event_id, room_id, ... (5 total)

**Recommendation:** Convert to instance method on class of `event`


#### _coerce_error_data accesses 3 fields of obj

**Location:** `adgn/src/adgn/mcp/policy_gateway/signals.py:59`

**Current:** Function accesses `obj.` (3 times)  
**Fields accessed:** code, get, message

**Recommendation:** Convert to instance method on class of `obj`


#### convert_sdk_response accesses 3 fields of sdk_resp

**Location:** `adgn/src/adgn/openai_utils/model.py:265`

**Current:** Function accesses `sdk_resp.` (3 times)  
**Fields accessed:** id, output, usage

**Recommendation:** Convert to instance method on class of `sdk_resp`


#### _simple_test accesses 5 fields of n

**Location:** `adgn/src/adgn/props/detectors/det_flatten_nested_guards.py:14`

**Current:** Function accesses `n.` (5 times)  
**Fields accessed:** comparators, left, op, ... (5 total)

**Recommendation:** Convert to instance method on class of `n`


#### _cmp_name accesses 3 fields of n

**Location:** `adgn/src/adgn/props/detectors/det_optional_string_simplify.py:66`

**Current:** Function accesses `n.` (3 times)  
**Fields accessed:** comparators, left, ops

**Recommendation:** Convert to instance method on class of `n`


#### _is_simple_guard accesses 6 fields of test

**Location:** `adgn/src/adgn/props/detectors/det_walrus_suggest.py:14`

**Current:** Function accesses `test.` (6 times)  
**Fields accessed:** comparators, id, left, ... (6 total)

**Recommendation:** Convert to instance method on class of `test`


#### _run accesses 3 fields of spec

**Location:** `adgn/src/adgn/props/detectors/registry.py:44`

**Current:** Function accesses `spec.` (3 times)  
**Fields accessed:** finder, name, target_property

**Recommendation:** Convert to instance method on class of `spec`


#### _issue_with_id_prefix accesses 3 fields of ri

**Location:** `adgn/src/adgn/props/grade_runner.py:58`

**Current:** Function accesses `ri.` (3 times)  
**Fields accessed:** id, occurrences, rationale

**Recommendation:** Convert to instance method on class of `ri`


#### _render_grade_submit_payload accesses 5 fields of obj

**Location:** `adgn/src/adgn/props/grader.py:260`

**Current:** Function accesses `obj.` (5 times)  
**Fields accessed:** false_positive_ids, message_md, metrics, ... (5 total)

**Recommendation:** Convert to instance method on class of `obj`


#### _render_lint_submit_payload accesses 3 fields of obj

**Location:** `adgn/src/adgn/props/lint_issue.py:50`

**Current:** Function accesses `obj.` (3 times)  
**Fields accessed:** findings, message_md, suggested_rationale

**Recommendation:** Convert to instance method on class of `obj`


#### _relay_error_response accesses 3 fields of resp

**Location:** `adgn/src/adgn/rspcache/__init__.py:293`

**Current:** Function accesses `resp.` (3 times)  
**Fields accessed:** content, headers, status_code

**Recommendation:** Convert to instance method on class of `resp`


#### Additional Violations (showing 30 of 71)

The following 41 additional violations follow the same pattern:

- `adgn/src/adgn/rspcache/admin_app.py:154` — `_to_response_model` (11 field accesses)
- `adgn/src/adgn/rspcache/admin_app.py:173` — `_to_api_key_model` (6 field accesses)
- `adgn/src/adgn/seatbelt/compile.py:29` — `_render_file_rule` (3 field accesses)
- `adgn/src/adgn/seatbelt/compile.py:38` — `_render_network_rule` (3 field accesses)
- `adgn/src/adgn/seatbelt/compile.py:43` — `compile_sbpl` (8 field accesses)
- `adgn/src/adgn/seatbelt/validate.py:46` — `validate` (3 field accesses)
- `adgn/src/adgn/tools/arg0_setup.py:9` — `_write_file` (3 field accesses)
- `adgn/src/adgn/tools/trivial_patterns.py:199` — `_walk` (3 field accesses)
- `ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py:68` — `save_claude_config` (4 field accesses)
- `claude/claude_optimizer/graders/requirement_templates.py:29` — `create_behavioral_requirement` (8 field accesses)
- `difftree/src/difftree/tree.py:88` — `propagate_stats` (4 field accesses)
- `difftree/src/difftree/tree.py:106` — `to_frozen` (7 field accesses)
- `difftree/src/difftree/tree.py:121` — `sort_tree` (7 field accesses)
- `experimental/diagnose_open_fds.py:170` — `format_process_summary` (5 field accesses)
- `experimental/ember_evals/gitea.py:36` — `verify_issue_comment` (3 field accesses)
- `experimental/ember_evals/gitea.py:82` — `verify_branch_file` (3 field accesses)
- `experimental/ember_evals/runner.py:337` — `plan_runs` (15 field accesses)
- `finance/gnucash_util.py:21` — `gnc_numeric_to_python_decimal` (3 field accesses)
- `finance/reconcile/reconcile.py:98` — `add_external_to_gnucash` (3 field accesses)
- `finance/reconcile/splitwise_lib.py:39` — `assign_token` (3 field accesses)
- `gatelet/gatelet/server/test_admin_webhook_e2e.py:63` — `test_admin_login_and_view_webhooks` (5 field accesses)
- `inventree_utils/beautifier/config.py:59` — `api_from_config` (3 field accesses)
- `inventree_utils/samplebooks_import/import_samplebooks2.py:95` — `get_quantity` (3 field accesses)
- `inventree_utils/samplebooks_import/import_samplebooks2.py:158` — `build_part_name` (4 field accesses)
- `inventree_utils/samplebooks_import/import_samplebooks2.py:257` — `create_part_in_inventree` (4 field accesses)
- `k8s/helm/gitea/files/ember_pat.py:80` — `ensure_user` (3 field accesses)
- `k8s/helm/gitea/files/ember_pat.py:98` — `create_token` (3 field accesses)
- `k8s/helm/gitea/files/ember_pat.py:124` — `upsert_secret` (3 field accesses)
- `k8s/helm/matrix-stack/files/admin_bootstrap.py:50` — `register_admin` (4 field accesses)
- `k8s/helm/matrix-stack/files/ember_bootstrap.py:56` — `register_user` (4 field accesses)
- `k8s/helm/matrix-stack/files/ember_bootstrap.py:85` — `login` (3 field accesses)
- `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/cli.py:321` — `_display_session` (3 field accesses)
- `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/parser.py:66` — `_parse_hunk` (5 field accesses)
- `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/parser.py:146` — `parse_tool_response` (3 field accesses)
- `llm/ducktape_llm_common/ducktape_llm_common/prompts/validation.py:233` — `validate_prompt_file` (4 field accesses)
- `llm/ducktape_llm_common/ducktape_llm_common/prompts/validation.py:270` — `validate_prompt_collection` (3 field accesses)
- `llm/mcp/habitify/habitify_mcp_server/utils/date_utils.py:89` — `format_date_for_api` (3 field accesses)
- `trilium/papers/papers_trilium_to_remarkable.py:144` — `build_filename` (3 field accesses)
- `wt/src/wt/cli.py:103` — `_root` (3 field accesses)
- `wt/src/wt/client/handlers.py:104` — `on_progress` (3 field accesses)
- `wt/src/wt/shared/github_models.py:121` — `coerce_prdata` (8 field accesses)

---

## Refactoring Strategy

### Phase 1: Factory Pattern (High Priority)
1. For each factory function, create a classmethod with the same name
2. Update all call sites from `make_config(...)` to `Config.make(...)`
3. Run type checker to verify no regressions
4. Update any related documentation

### Phase 2: State Modifying (Medium Priority)
1. Identify the class that owns the modified state
2. Move function into that class as instance method
3. Replace instance parameter with `self`
4. Update all call sites: `update_state(ctx, ...)` → `ctx.update_state(...)`

### Phase 3: Tight Coupling (Medium-High Priority)
1. For each function with 3+ field accesses, find the instance parameter type
2. Move function into that class as instance method
3. Replace field accesses: `instance.field` → `self.field`
4. Remove instance parameter from method signature
5. Update all call sites to use method form

---

## Benefits of Refactoring

✅ **Improved Discoverability** - IDEs show methods in autocomplete  
✅ **Better Encapsulation** - Implementation details hidden from callers  
✅ **Cleaner Namespaces** - Fewer module-level functions  
✅ **Shorter Call Sites** - No repeated parameter passing  
✅ **Clear Ownership** - Obvious which class "owns" the behavior  
✅ **Inheritance Support** - Subclasses can override behavior  
✅ **Type Safety** - Tighter coupling to type system  

---

## When Freestanding Functions ARE Appropriate

Keep functions freestanding when:

- **Pure Functions**: No instance state, operates only on parameters
  ```python
  def compute_hash(data: bytes) -> str:
      return hashlib.sha256(data).hexdigest()
  ```

- **Utilities**: Generic operations not tied to a specific class
  ```python
  def format_timestamp(ts: float) -> str:
      return datetime.fromtimestamp(ts).isoformat()
  ```

- **Composition**: Combining multiple unrelated classes
  ```python
  def sync_database_to_cache(db: Database, cache: RedisCache):
      data = db.fetch_all()
      cache.bulk_set(data)
  ```

- **Top-level Orchestration**: High-level workflows
  ```python
  async def run_batch_processing(config: Config, queue: Queue):
      # Orchestrates multiple services
  ```

---

## References

- **Scan Definition:** `prompts/scans/methods-vs-freestanding.md`
- **Python Classmethods:** https://docs.python.org/3/library/functions.html#classmethod
- **SOLID SRP:** https://en.wikipedia.org/wiki/Single-responsibility_principle
- **Refactoring: Move Method:** https://refactoring.com/catalog/moveMethod.html

---

## Implementation Notes

- Start with factory patterns (cleanest refactoring)
- Use IDE refactoring tools to batch rename/move
- Run full test suite after each phase
- Consider impact on public APIs (if applicable)
- Update docstrings to reflect new structure

