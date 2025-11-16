# Code Health Scan Report - Ducktape Repository

**Scan Date**: 2025-01-16
**Branch Scanned**: `claude/read-scan-prompts-01KJcv4Kab7vRGWwwaMPKgXS`
**Scan Prompts Source**: `claude/prompts-only-018JJNA3pm4G3rqG1uXkXcVh`

---

## Executive Summary

- **Total issues identified**: **350+** across 14 categories
- **Files affected**: **100+** Python files
- **Potential lines saved**: **200+** through refactoring
- **Critical issues**: **3** categories (62 occurrences)
- **High priority**: **4** categories (117+ occurrences)
- **Medium priority**: **6** categories (234+ occurrences)
- **Low priority**: **2** categories (22 occurrences)

---

## Action Items by Priority

### 🚨 CRITICAL - Fix Immediately

#### 1. Datetime Without Timezone (58 occurrences)
- [ ] Review and fix `llm/ultra-long-cot/ultra_long_cot_o4.py` (4 occurrences)
- [ ] Review and fix `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/state.py` (5 occurrences)
- [ ] Review and fix `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/manager.py` (3 occurrences)
- [ ] Fix `llm/mcp/habitify/habitify_mcp_server/utils/date_utils.py:24,47` - utility function returning naive datetime
- [ ] Fix `finance/reconcile/reconcile.py:110`
- [ ] Fix `gatelet/gatelet/server/models.py` timestamp fields (4 occurrences)
- [ ] Fix `gatelet/gatelet/server/conftest.py` test fixtures
- [ ] Fix `claude/claude_optimizer/graders/scoresheet.py:100`
- [ ] Scan and fix remaining 32+ occurrences across other files
- [ ] Create linter rule to prevent `datetime.now()` without timezone argument

#### 2. Enums Exist But Not Enforced (3 critical cases)
- [x] **Habitify Status**: Fix `llm/mcp/habitify/habitify_mcp_server/types.py` - enum exists but models use `str` ✅ FIXED in commit dd1ec34
  - [x] Update `HabitStatus.status` field to use `Status` enum (line 79) ✅
  - [x] Update `StatusResult.status` field to use `Status` enum (line 93) ✅
  - [x] Update function parameters in `tools.py` to use `Status` enum (line 246) ✅
  - [x] Update all other Status usages (HabitStatusResponse, LogResult, DateRangeStatusItem, Habit) ✅
  - [x] Update UnitType enum usage in Goal and Progress models ✅
  - [x] Update Periodicity enum usage in Goal and Progress models ✅
  - [x] Update TimeOfDay enum usage in Habit model ✅
- [ ] **Response Status**: Fix `adgn/src/adgn/rspcache/responses_db.py:109`
  - [ ] Change `status: Mapped[str]` to `status: Mapped[ResponseStatus]`
  - [ ] Update database migration script
- [x] **Hook Type**: Fix `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/hooks/validation.py` ✅ FIXED in commit bb09dd4
  - [x] Update `validate_hook_outcome` parameter type (line 34) ✅
  - [x] Update `_validate_outcome_semantics` parameter type (line 53) ✅
  - [x] Update `validate_final_response` parameter type (line 82) ✅
  - [x] Create HookEventName enum in claude_code_api.py ✅
  - [x] Update VALID_OUTCOMES dict to use enum keys ✅

#### 3. Security Issue
- [ ] **ember/src/ember/config.py:56** - Move pickle_key from TOML to k8s secret
  - [ ] Create k8s secret for pickle_key
  - [ ] Update config to read from secret
  - [ ] Remove from TOML configuration
  - [ ] Update deployment documentation

---

### 🔥 HIGH PRIORITY - This Week

#### 4. Stringly-Typed Code (40+ occurrences)

**Convert Literal types to StrEnum:**
- [ ] `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/parser.py:13` - DiffLine.change_type
- [ ] `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/categorizer.py:15` - CategorizedViolation.category
- [ ] `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/config/models.py:116` - NotificationHookConfig.urgency
- [x] `llm/ducktape_llm_common/ducktape_llm_common/claude_code_api.py` - Convert 5 hook event Literal types to single HookEventName enum ✅ FIXED in commit bb09dd4
- [x] `tana/src/tana/domain/search.py` - Convert 5 SearchKind Literal types to single enum ✅ FIXED in commit f880197

**Fix string status/state fields:**
- [ ] `adgn/src/adgn/inop/runners/containerized_claude.py:338,340` - Create ContainerStatus enum
- [ ] `experimental/claude-history/claude_history_reader.py` - Create MessageType and EntryType enums
- [ ] `ember/src/ember/runtime/python_session.py:92,94,96` - Create JupyterMessageType enum

**Fix string function parameters:**
- [ ] `adgn/src/adgn/inop/runners/containerized_claude.py:393` - script_type parameter
- [ ] `ember/src/ember/matrix_client.py:165` - msgtype parameter
- [ ] `adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py:402,420` - mode parameter

#### 5. Type Untyped Dicts (8 occurrences)

- [ ] **adgn/src/adgn/rspcache/responses_db.py:133-135** - Type ResponseSnapshot fields
  - [ ] Change `response: Mapped[dict[str, Any] | None]` to `response: Mapped[OpenAIResponse | None]`
  - [ ] Change `error: Mapped[dict[str, Any] | None]` to `error: Mapped[ErrorPayload | None]`
  - [ ] Change `token_usage: Mapped[dict[str, Any] | None]` to `token_usage: Mapped[ResponseUsage | None]`
- [ ] **adgn/src/adgn/rspcache/responses_db.py:108** - Type request_body field
  - [ ] Change to `request_body: Mapped[ResponseCreateParams]`
- [ ] **adgn/src/adgn/rspcache/admin_app.py:100** - Type ResponseRecordModel.request_body (has TODO!)
- [ ] **adgn/src/adgn/llm/sysrw/schemas.py:42-44** - Type CCRRequest fields using Anthropic SDK types
- [ ] **adgn/src/adgn/llm/sysrw/schemas.py:19** - Type ToolFunction.input_schema
- [ ] **adgn/src/adgn/openai_utils/model.py:114** - Type FunctionToolParam.parameters
- [ ] **adgn/src/adgn/openai_utils/model.py:164** - Type OutputText.annotations
- [ ] **adgn/src/adgn/llm/sysrw/schemas.py:66** - Type EvalSampleRecord fields

#### 6. API Model Design Antipatterns (26 occurrences)

**Remove `_json` suffixes (9 occurrences):**
- [x] `adgn/src/adgn/rspcache/responses_db.py:91` - Rename `frame_json` to `frame` ✅ FIXED in commit 814191c
- [ ] `adgn/src/adgn/agent/server/protocol.py:122` - Rename `args_json` to `arguments` (40 usages across 14 files - large change)
- [ ] `adgn/src/adgn/agent/persist/events.py:23` - Rename ToolCallPayload.args_json
- [ ] `adgn/src/adgn/agent/approvals.py:58` - Rename ApprovalToolCall.args_json
- [ ] `adgn/src/adgn/agent/server/protocol.py:235` - Rename ApprovalPendingEvt.args_json
- [ ] Review and rename remaining 4 `_json` suffix usages

**Fix denormalized/flattened fields (5 occurrences):**
- [ ] `adgn/src/adgn/rspcache/events.py:33-36` - Nest APIKeyCreatedEvent fields into APIKeyInfo object
- [ ] `wt/src/wt/shared/github_models.py:78-86` - Nest PRData fields into PullRequestInfo object
- [ ] `adgn/src/adgn/inop/engine/models.py:262-268` - Nest ToolCall fields

**Separate concerns (4 occurrences):**
- [ ] `adgn/src/adgn/rspcache/admin_app.py:77-105` - Separate ResponseRecordModel into distinct DB and API models
- [ ] `wt/src/wt/shared/github_models.py:166-173` - Split PRInfo into runtime and API models
- [ ] `adgn/src/adgn/agent/server/protocol.py:179-190` - Refactor SnapshotDetails to use discriminated unions

#### 7. Manual Serialization Patterns (32 occurrences)

**Replace json.loads + model_validate with model_validate_json:**
- [ ] `adgn/src/adgn/agent/persist/sqlite.py:165,190,207` - 3 occurrences
- [ ] `adgn/src/adgn/agent/persist/sqlite.py:185,203,272` - 3 occurrences in row parsing
- [ ] `wt/src/wt/shared/protocol.py:475-479` - parse_request function

**Convert dataclasses to Pydantic (5 occurrences):**
- [ ] `inventree_utils/beautifier/config.py:12-56` - Convert InstanceConfig to Pydantic
- [ ] `wt/src/wt/server/types.py:10-40` - Convert GitWorkingStatus and DiscoveredWorktree
- [ ] `tana/src/tana/export/convert.py:48-57` - Convert RenderContext to Pydantic
- [ ] `adgn/src/adgn/agent/agent.py:47-78` - Convert ToolCall result types to discriminated union
- [ ] `wt/src/wt/server/rpc.py:63-83` - Convert ServiceDependencies and InvocationContext

**Fix manual dict construction patterns:**
- [ ] `adgn/src/adgn/agent/agent.py:175-190` - Replace manual tool choice dict with typed union
- [ ] `adgn/src/adgn/rspcache/responses_db.py:145-150` - Use direct model construction
- [ ] `adgn/src/adgn/openai_utils/types.py:52-59` - Fix ReasoningParams manual building

**Replace TypedDict with BaseModel:**
- [ ] `claude/claude_hooks/claude_hooks/actions.py:14-18` - Convert HookOutput
- [ ] `adgn/src/adgn/openai_utils/types.py:31-59` - Convert ReasoningParams
- [ ] `adgn/src/adgn/agent/handler.py:105-114` - Convert JsonlRecord

---

### ⚡ MEDIUM PRIORITY - This Month

#### 8. Library Type Misuse (35 occurrences)

**Remove unnecessary Pydantic casts (4 occurrences):**
- [ ] `wt/src/wt/client/wt_client.py:244` - Remove cast on model_dump()
- [ ] `adgn/src/adgn/openai_utils/probe/main.py:99` - Remove cast on model_dump()
- [ ] `adgn/src/adgn/mcp/testing/typed_stubs.py:67` - Remove cast on model_dump()
- [ ] `adgn/src/adgn/agent/presets.py:38` - Remove cast on validated data

**Remove unnecessary SQLAlchemy casts (5 occurrences):**
- [ ] `adgn/src/adgn/rspcache/responses_db.py:478` - Remove cast on scalar_one_or_none()
- [ ] `adgn/src/adgn/rspcache/responses_db.py:506` - Remove cast on scalars()
- [ ] `adgn/src/adgn/agent/persist/sqlite.py:185,203,272` - Remove casts on row column access

**Replace hasattr/getattr with isinstance (10 occurrences):**
- [ ] `mcp_starter/test_server.py:15,35,51,53-54` - Replace getattr with direct attribute access
- [ ] `adgn/src/adgn/llm/sysrw/run_eval.py:257` - Use isinstance(part, BaseModel)
- [ ] `adgn/tests/agent/helpers.py:36` - Use isinstance check
- [ ] `adgn/src/adgn/mcp/policy_gateway/middleware.py:159,164,185` - Direct attribute access

**Remove unnecessary type narrowing casts:**
- [ ] `adgn/src/adgn/inop/prompting/truncation_utils.py:49,63,66` - Use type guards properly
- [ ] `adgn/src/adgn/inop/grading/strategies.py:153,156` - Fix type narrowing

#### 9. Pydantic Antipatterns (19 occurrences)

- [ ] `adgn/src/adgn/rspcache/models.py:46-48` - Delete unnecessary @field_serializer for StrEnum
- [ ] `adgn/src/adgn/rspcache/models.py:51-92` - Replace model_dump + dict.get with direct attributes (4 functions)
- [ ] `wt/src/wt/client/wt_client.py:241-246` - Keep typed model instead of dumping to dict
- [ ] `wt/src/wt/shared/fixtures.py:54-62` - Use model_validate instead of manual field copying
- [ ] `wt/src/wt/shared/github_models.py:101-112,125-133,141-149` - Use model_validate (3 occurrences)
- [ ] `tana/src/tana/io/json.py:24-26` - Remove unnecessary serialize/deserialize cycle
- [ ] `gatelet/gatelet/server/config.py:162` - Replace parse_obj() with model_validate()
- [ ] Update test files to use direct attribute access instead of model_dump() (6+ files)

#### 10. Vague Field Names (60+ occurrences)

**High-impact renames:**
- [ ] `adgn/src/adgn/inop/engine/models.py:342` - Refactor RunnerEnvironment to use discriminated union
- [ ] `adgn/src/adgn/rspcache/models.py:29-31` - Rename ErrorPayload fields with error_ prefix
- [ ] `gatelet/gatelet/server/models.py` - Add table name context to all `id` and `name` fields (8 tables)
- [ ] `adgn/src/adgn/rspcache/responses_db.py:384,420,516` - Rename `key` parameter to `cache_key`

**Medium-impact renames:**
- [ ] `experimental/webhook_inbox/webhook_inbox.py:88` - Rename `key` to `encryption_key`
- [ ] `wt/src/wt/shared/models.py:16` - Rename Worktree.name to worktree_name
- [ ] `ember/src/ember/config.py:79` - Rename `model` to `model_name`
- [ ] `finance/reconcile/external_expense.py:8` - Rename `id` to `external_expense_id`

**Trajectory models cleanup:**
- [ ] `adgn/src/adgn/inop/engine/models.py:259-294` - Replace 6 `original: Any | None` fields with `raw_api_response`

#### 11. Timestamp Naming Inconsistency (92 occurrences)

**Database migrations (requires schema changes):**
- [ ] Create migration script for rspcache database
- [ ] `adgn/src/adgn/rspcache/responses_db.py:69` - Rename ClientAPIKey.created_ts to created_at
- [ ] `adgn/src/adgn/rspcache/responses_db.py:70` - Rename ClientAPIKey.revoked_ts to revoked_at
- [ ] `adgn/src/adgn/rspcache/responses_db.py:90` - Rename ResponseFrame.created_ts to created_at
- [ ] `adgn/src/adgn/rspcache/responses_db.py:111` - Rename Response.created_ts to created_at
- [ ] `adgn/src/adgn/rspcache/responses_db.py:114` - Rename Response.last_update_ts to updated_at
- [ ] `adgn/src/adgn/rspcache/responses_db.py:136,139` - Rename ResponseSnapshot timestamps

**API model fixes (no migration needed):**
- [ ] `adgn/src/adgn/rspcache/admin_app.py:129` - **CRITICAL INCONSISTENCY** - Change revoked_ts to revoked_at
- [ ] `adgn/src/adgn/agent/server/protocol.py:29` - Rename event_ts to event_at
- [ ] `adgn/src/adgn/openai_utils/probe/main.py:134-135` - Rename start_ts/end_ts to started_at/ended_at

**Non-DB usages:**
- [ ] `tana/src/tana/domain/nodes.py:51` - Rename modified_ts to modified_at

#### 12. Magic Numbers (Many occurrences)

**Extract timeout constants:**
- [ ] Create `timeouts.py` configuration module
- [ ] Extract sleep intervals: 0.01, 0.5, 5, 30 seconds
- [ ] Extract subprocess timeouts: 2, 5, 10, 30, 60 seconds
- [ ] Extract HTTP timeouts: 10, 30 seconds
- [ ] Extract poll/retry limits: 10, 20, 50, 200 iterations

**Consider making configurable:**
- [ ] Add environment variables for common timeouts
- [ ] Document timeout configuration in README

#### 13. TODO/FIXME Comments (52+ occurrences)

**High-priority TODOs:**
- [ ] `adgn/src/adgn/rspcache/admin_app.py:99` - Type request_body field
- [ ] `mcp_starter/manual_test_sdk.py:39` - Verify if upstream fix is available
- [ ] `ember/src/ember/history.py:71` - Implement out-of-context error handling

**Medium-priority:**
- [ ] `trilium/search_hack.py:64` - Investigate API support for empty search
- [ ] `llm/ducktape_llm_common/...claude_linter_v2/cli.py:357` - Implement profile activation
- [ ] Review and prioritize remaining 45+ TODOs

#### 14. String Path Concatenation (7 occurrences)

- [ ] `adgn/src/adgn/rspcache/__init__.py:277` - URL concatenation (OK, but review)
- [ ] `trilium/papers/papers_trilium_to_remarkable.py:205-206` - Use Path objects (2 occurrences)
- [ ] `llm/ducktape_llm_common/...claude_linter_v2/cli.py:418` - Use Path.relative_to()
- [ ] `adgn/src/adgn/props/specimens/.../pyright_watch_report.py:74` - Use Path concatenation
- [ ] `adgn/src/adgn/mcp/approval_policy/server.py:152` - URI pattern (review)
- [ ] `adgn/gitea_pr_gate/policy_common.py:7` - URL construction (review)

---

### 📋 LOW PRIORITY - As Time Permits

#### 15. Test Assertion Antipatterns (20 files)

- [ ] `gatelet/gatelet/server/test_report_battery.py:36-37` - Combine assertions
- [ ] `claude/claude_hooks/tests/test_models.py:95-96` - Combine assertions
- [ ] `adgn/tests/mcp/test_notifications_envelope.py:36-42,61-64` - Simplify assertions
- [ ] `adgn/tests/agent/test_parallel_calls.py:126-132` - Combine kind counts
- [ ] `experimental/webhook_inbox/test_webhook_inbox.py:44-45` - Combine assertions
- [ ] `claude/claude_optimizer/tests/test_optimizer.py:261-263,339-341` - Combine assertions
- [ ] `adgn/tests/agent/test_exec_roundtrip.py:26-29` - Combine assertions
- [ ] `adgn/tests/seatbelt/test_runner_async.py:65-69` - Combine assertions
- [ ] `adgn/tests/mcp/test_pg_middleware.py:35-36` - Combine assertions
- [ ] `difftree/tests/test_parser.py:13-17,52-54` - Combine assertions
- [ ] `adgn/tests/agent/test_mcp_resources_flow.py:43-46` - Combine assertions
- [ ] `claude/claude_optimizer/tests/test_e2e_database.py` - Multiple assertion combinations
- [ ] Review and refactor remaining 7 test files

#### 16. Pytest Tmp Paths (2 occurrences)

- [ ] `claude/claude_optimizer/tests/unit/test_config.py:4` - Replace tempfile with tmp_path fixture
- [ ] `llm/mcp/habitify/examples/test_mcp_dev.py:16` - Replace tempfile with tmp_path fixture

#### 17. Type: Ignore Comments Review (34 occurrences)

- [ ] Review all `type: ignore[import-untyped]` - check if stubs are available
- [ ] Review test monkey-patching type ignores - consider better patterns
- [ ] Review override mismatches - verify they're intentional
- [ ] Document why each type: ignore is necessary

#### 18. Useless Documentation Review (30+ files)

- [ ] Audit `difftree/` files for redundant docstrings
- [ ] Audit `tana/` files for redundant docstrings
- [ ] Audit `wt/` files for redundant docstrings
- [ ] Audit `adgn/src/adgn/inop/` files for redundant docstrings
- [ ] Audit `claude/claude_hooks/` files for redundant docstrings
- [ ] Create guideline: Only document non-obvious behavior, not type signatures

---

## Preventive Measures

### Add Pre-commit Hooks/Linters

- [ ] Add ruff rule to prevent `datetime.now()` without timezone
- [ ] Add ruff rule to detect `_json` suffix on field names
- [ ] Add mypy strict mode configuration
- [ ] Add custom linter for detecting stringly-typed patterns
- [ ] Add pre-commit hook to check for new TODO comments
- [ ] Add linter rule for magic numbers in specific contexts

### Documentation Updates

- [ ] Create CONTRIBUTING.md with code style guidelines
- [ ] Document enum usage policy (when to use StrEnum vs Literal)
- [ ] Document Pydantic best practices (no manual model_dump + dict.get)
- [ ] Document timezone handling policy (always use UTC)
- [ ] Create type annotation guide for API models

### Code Review Checklist

- [ ] Create PR template with code quality checks
- [ ] Add checklist item: "No naive datetime objects"
- [ ] Add checklist item: "Enums used instead of string literals"
- [ ] Add checklist item: "Pydantic models for structured data"
- [ ] Add checklist item: "No `_json` suffix on field names"

---

## Detailed Findings

### 1. Timestamp Naming Issues (_ts suffix)

**Count**: 92 occurrences across 19 files
**Impact**: Inconsistency with Rails/Django/SQLAlchemy conventions

**Industry Standard**: `created_at`, `updated_at`, `deleted_at`
**Current Usage**: `created_ts`, `last_update_ts`, `revoked_ts`

**Primary Offenders**:

1. **adgn/src/adgn/rspcache/responses_db.py**
   - Line 69: `created_ts: Mapped[datetime]` → Should be `created_at`
   - Line 70: `revoked_ts: Mapped[datetime | None]` → Should be `revoked_at`
   - Line 90: `created_ts: Mapped[datetime]` → Should be `created_at`
   - Line 111: `created_ts: Mapped[datetime]` → Should be `created_at`
   - Line 114: `last_update_ts: Mapped[datetime]` → Should be `updated_at`
   - Line 136: `created_ts: Mapped[datetime]` → Should be `created_at`
   - Line 139: `updated_ts: Mapped[datetime]` → Should be `updated_at`
   - Lines 162-163: DataClass fields `created_ts`, `revoked_ts`

2. **CRITICAL INCONSISTENCY - adgn/src/adgn/rspcache/admin_app.py:128-129**
   ```python
   class APIKeyModel(BaseModel):
       created_at: datetime  # Uses _at convention
       revoked_ts: datetime | None = None  # Uses _ts convention!
   ```
   Same model uses BOTH conventions!

**Other Files**:
- `adgn/src/adgn/agent/server/protocol.py:29`: `event_ts`
- `adgn/src/adgn/openai_utils/probe/main.py`: `start_ts`, `end_ts` (lines 134-135, 436-437)
- `tana/src/tana/domain/nodes.py:51`: `modified_ts`

**Rationale for _at**:
- Rails, Django, PostgreSQL guides all prefer `_at`
- More readable: "created at [timestamp]"
- Shorter: `updated_at` (10 chars) vs `last_update_ts` (14 chars)
- Industry dominant convention (GitHub API, Stripe API, etc.)

---

### 2. Vague Field Names

**Count**: 60+ occurrences across 25 files

#### Generic `id` Fields (15+ occurrences)

All SQLAlchemy models in `gatelet/gatelet/server/models.py`:
- Line 18: `WebhookIntegration.id` → Should be `integration_id`
- Line 44: `WebhookPayload.id` → Should be `payload_id`
- Line 55: `AuthKey.id` → Should be `auth_key_id`
- Line 90: `AuthCRSession.id` → Should be `session_id`
- Line 110: `AuthNonce.id` → Should be `nonce_id`
- Line 132: `AdminSession.id` → Should be `admin_session_id`

Pydantic/dataclass models:
- `finance/reconcile/external_expense.py:8`: `id: str` → Should be `expense_id` or `transaction_id`
- `adgn/src/adgn/inop/engine/models.py`: Multiple `id: str` fields without context

#### Generic `name` Fields (8+ occurrences)

- `wt/src/wt/shared/models.py:16`: `Worktree.name: str` → Should be `worktree_name` or `directory_name`
- `ember/src/ember/config.py:79`: `model: str` → Should be `model_name` or `llm_model_id`
- `adgn/src/adgn/inop/engine/models.py:37`: `Criterion.name: str` → Should be `criterion_name`

#### Generic `key` Fields (5 occurrences)

- `experimental/webhook_inbox/webhook_inbox.py:88`: `key: str | None` → Should be `encryption_key` or `fernet_key`
- `adgn/src/adgn/rspcache/responses_db.py:384,420,516`: Function parameter `key: str` → Should be `cache_key`

#### Generic `data`/`value` Fields (10+ occurrences)

- `adgn/src/adgn/inop/engine/models.py:342`:
  ```python
  class RunnerEnvironment:
      type: str  # Should be Literal or Enum
      data: dict[str, Any]  # EXTREMELY VAGUE - should be discriminated union
  ```
- `llm/html/llm_html/server.py:40`: `STATS_CACHE = {"data": None, ...}` → Should be `stats_snapshot`

#### Complex Nested Issues

**adgn/src/adgn/rspcache/models.py:29-31** - ErrorPayload:
```python
class ErrorPayload(BaseModel):
    message: str | None = None  # Should be error_message
    code: str | None = None  # Should be error_code
    detail: Any | None = None  # Should be error_details
```

**adgn/src/adgn/inop/engine/models.py:259-294** - Trajectory models:
```python
# Pattern repeated across 6 models:
original: Any | None = None  # Should be raw_api_response or provider_format
```

---

### 3. API Model Design Antipatterns

**Count**: 26 occurrences across 11 files

#### Pattern 1: `_json` Suffix (9 occurrences)

Leaking implementation details into field names.

**Examples**:
1. `adgn/src/adgn/rspcache/responses_db.py:91`
   ```python
   frame_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
   # Should be: frame: Mapped[ResponseStreamEvent]
   ```

2. `adgn/src/adgn/agent/server/protocol.py:122`
   ```python
   class ToolCall(BaseModel):
       args_json: str | None = None
   # Should be: arguments: dict[str, Any]
   ```

3. Multiple occurrences in:
   - `adgn/src/adgn/agent/persist/events.py:23`
   - `adgn/src/adgn/agent/approvals.py:58`
   - `adgn/src/adgn/agent/server/protocol.py:235`

**Why it's wrong**:
- Type system already indicates JSON storage
- API clients shouldn't know storage format
- If you change DB storage (e.g., to BSON), API name becomes misleading

#### Pattern 2: Untyped Dicts (8 occurrences)

Using `dict[str, Any]` when proper types exist.

**Critical Example - adgn/src/adgn/rspcache/responses_db.py:133-135**:
```python
class ResponseSnapshot(Base):
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

**Proper types available**:
```python
from openai.types.responses import Response as OpenAIResponse, ResponseUsage

class ResponseSnapshot(Base):
    response: Mapped[OpenAIResponse | None]
    error: Mapped[ErrorPayload | None]  # Already defined!
    token_usage: Mapped[ResponseUsage | None]
```

**Other Examples**:
- `adgn/src/adgn/rspcache/responses_db.py:108` - `request_body: Mapped[dict[str, Any]]`
- `adgn/src/adgn/rspcache/admin_app.py:100` - Has TODO comment!
- `adgn/src/adgn/llm/sysrw/schemas.py:42-44` - Anthropic messages and tools

#### Pattern 3: Denormalized Fields (5 occurrences)

**Example - adgn/src/adgn/rspcache/events.py:33-36**:
```python
class APIKeyCreatedEvent(EventBase):
    type: Literal["api_key_created"] = "api_key_created"
    id: str  # Flattened
    name: str  # Flattened
    upstream_alias: str  # Flattened

# Should be:
class APIKeyCreatedEvent(EventBase):
    type: Literal["api_key_created"] = "api_key_created"
    api_key: APIKeyInfo  # Nested object
```

#### Pattern 4: Mixed Concerns (4 occurrences)

**Example - adgn/src/adgn/rspcache/admin_app.py:77-105**:
```python
class ResponseRecordModel(BaseModel):
    """API model for cached OpenAI API responses."""
    model_config = ConfigDict(from_attributes=True)  # DB mapping concern!

    cache_key: str  # Internal DB detail exposed to API
    created_at: datetime  # Doesn't match DB (created_ts)
    request_body: dict[str, Any]  # Untyped despite TODO
```

**Issue**: Mixes ORM mapping, DB field names, and API representation.

---

### 4. Library Type Misuse

**Count**: 35 occurrences across 15 files

#### Category 1: Unnecessary Casts on Pydantic (4 occurrences)

```python
# WRONG:
return cast(dict[str, Any], model.model_dump(mode="json"))

# Pydantic's model_dump already returns dict[str, Any]!
```

**Examples**:
- `wt/src/wt/client/wt_client.py:244`
- `adgn/src/adgn/openai_utils/probe/main.py:99`
- `adgn/src/adgn/mcp/testing/typed_stubs.py:67`

#### Category 2: Unnecessary Casts on SQLAlchemy (5 occurrences)

```python
# WRONG:
return cast(Response | None, result.scalar_one_or_none())

# SQLAlchemy 2.x already provides proper types
```

**Examples**:
- `adgn/src/adgn/rspcache/responses_db.py:478,506`
- `adgn/src/adgn/agent/persist/sqlite.py:185,203,272`

#### Category 3: hasattr/getattr on Typed Objects (10 occurrences)

```python
# WRONG:
assert not getattr(result, "is_error", False)

# CallToolResult has typed is_error attribute:
assert not result.is_error
```

**Examples**:
- `mcp_starter/test_server.py:15,35,51,53-54` - 5 occurrences
- `adgn/src/adgn/mcp/policy_gateway/middleware.py:159,164,185` - 3 occurrences
- `adgn/src/adgn/llm/sysrw/run_eval.py:257,432-438` - 2 occurrences

**Better Pattern**:
```python
# Instead of hasattr(obj, "model_dump"):
if isinstance(obj, BaseModel):
    obj.model_dump()
```

---

### 5. Manual Serialization (Should Use Pydantic)

**Count**: 32 occurrences across 20 files

#### Pattern 1: json.loads + model_validate (7 occurrences)

```python
# WRONG:
mcp_config = MCPConfig.model_validate(json.loads(r["specs"]))

# RIGHT:
mcp_config = MCPConfig.model_validate_json(r["specs"])
```

**Examples**:
- `adgn/src/adgn/agent/persist/sqlite.py:165,190,207`
- `wt/src/wt/shared/protocol.py:479`

#### Pattern 2: Dataclasses with Manual Serialization (5 occurrences)

```python
# WRONG:
@dataclass
class UserData:
    id: str
    email: str

    def to_dict(self) -> dict:
        return {"id": self.id, "email": self.email}

# RIGHT - Use Pydantic:
class UserData(BaseModel):
    id: str
    email: str
# Now: user.model_dump() automatically
```

**Examples**:
- `inventree_utils/beautifier/config.py:12-56`
- `wt/src/wt/server/types.py:10-40`
- `adgn/src/adgn/agent/agent.py:47-78`

#### Pattern 3: Manual Dict Construction for Nested Structures (10 occurrences)

```python
# WRONG:
def build_request(user_id: str, items: list[str]) -> dict:
    return {
        "user": {"id": user_id, "preferences": {"lang": "en"}},
        "items": [{"name": item, "qty": 1} for item in items],
    }

# RIGHT - Nested Pydantic models:
class User(BaseModel):
    id: str
    preferences: Preferences = Field(default_factory=Preferences)

def build_request(user_id: str, items: list[str]) -> Request:
    return Request(user=User(id=user_id), items=[Item(name=i) for i in items])
```

#### Pattern 4: TypedDict Where BaseModel Better (6 occurrences)

```python
# WRONG:
class EventPayload(TypedDict):
    event_type: str
    timestamp: str  # No validation!

# RIGHT:
class EventPayload(BaseModel):
    event_type: str
    timestamp: datetime  # Auto-parsed and validated!
```

**Examples**:
- `claude/claude_hooks/claude_hooks/actions.py:14-18` - HookOutput
- `adgn/src/adgn/openai_utils/types.py:31-59` - ReasoningParams

---

### 6. Pydantic Antipatterns

**Count**: 19 occurrences across 10 files

#### Antipattern 1: Unnecessary @field_serializer

```python
# WRONG - adgn/src/adgn/rspcache/models.py:46-48
@field_serializer("status")
def serialize_status(self, value: ResponseStatus) -> str:
    return value.value

# Pydantic v2 automatically serializes StrEnum to string!
# Just delete this entire decorator and method.
```

#### Antipattern 2: Manual model_dump + dict.get (6 occurrences)

```python
# WRONG:
payload = event.model_dump(mode="python")
event_id = payload.get("event_id")
return event_id if isinstance(event_id, str) else None

# RIGHT:
return event.event_id if isinstance(event.event_id, str) else None
```

**Files**:
- `adgn/src/adgn/rspcache/models.py` - 4 functions doing this (lines 51-92)
- `wt/src/wt/client/wt_client.py:241-246`

#### Antipattern 3: Manual Field-by-Field Copying (4 occurrences)

```python
# WRONG:
return PRData(
    pr_number=entry.number,
    pr_state=PRState(entry.state),
    draft=entry.draft,
    mergeable=entry.mergeable,
    # ... 5 more fields manually copied
)

# RIGHT:
return PRData.model_validate({
    "pr_number": entry.number,
    "pr_state": entry.state,
    # ... Pydantic handles validation and conversion
})
```

**Examples**:
- `wt/src/wt/shared/fixtures.py:54-62`
- `wt/src/wt/shared/github_models.py:101-112,125-133,141-149`

#### Antipattern 4: Deprecated Pydantic v1 API

```python
# WRONG:
return cls.parse_obj(config_dict)

# RIGHT (Pydantic v2):
return cls.model_validate(config_dict)
```

**Example**: `gatelet/gatelet/server/config.py:162`

---

### 7. Stringly-Typed Code

**Count**: 40+ occurrences across 30 files

#### Critical: Enums Exist But Not Enforced (3 cases)

**Case 1: Habitify Status**
- Enum defined: `llm/mcp/habitify/habitify_mcp_server/types.py:15-22`
- But fields use `str`: Lines 79, 93, 203, 214, 230
- Function parameters use `str`: Line 246

```python
# DEFINED:
class Status(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    # ...

# BUT USED AS:
class HabitStatus(BaseModel):
    status: str  # Should be Status!

def set_habit_status(status: str = "completed"):  # Should be Status!
```

**Case 2: Response Status**
- Enum defined: `adgn/src/adgn/rspcache/models.py:21-23`
- DB uses string: `adgn/src/adgn/rspcache/responses_db.py:109,132`

**Case 3: Hook Type**
- Enum exists but functions take `str`:
- `llm/ducktape_llm_common/.../hooks/validation.py:34,53,82`

#### Literal Types Should Be StrEnum (15+ occurrences)

```python
# WRONG:
class DiffLine:
    change_type: Literal["added", "removed", "context"]

# RIGHT:
class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CONTEXT = "context"

class DiffLine:
    change_type: ChangeType
```

**Examples**:
- `llm/.../claude_linter_v2/diff/parser.py:13`
- `llm/.../claude_linter_v2/diff/categorizer.py:15`
- `llm/.../claude_linter_v2/config/models.py:116`
- `llm/.../claude_code_api.py` - 5 hook event Literals
- `tana/src/tana/domain/search.py` - 5 search kind Literals

#### String Status Fields (10+ occurrences)

```python
# Container status - no enum defined
if c.status == "running":  # Typo-prone!
if c.status in ["exited", "dead"]:  # List of strings!

# Should be:
class ContainerStatus(StrEnum):
    RUNNING = "running"
    EXITED = "exited"
    DEAD = "dead"

if c.status == ContainerStatus.RUNNING:
```

**Examples**:
- `adgn/src/adgn/inop/runners/containerized_claude.py:338,340,552,554`
- `experimental/claude-history/claude_history_reader.py` - Multiple comparisons
- `ember/src/ember/runtime/python_session.py:92,94,96`

---

### 8. Test Assertion Antipatterns

**Count**: 20 test files
**Lines Saved**: 35+ lines

#### Pattern: Field-by-Field Assertions

```python
# VERBOSE (BAD):
assert response.status_code == 200
assert response.data["id"] == "test_id"
assert response.data["name"] == "test_name"

# CONCISE (GOOD):
assert (response.status_code, response.data["id"], response.data["name"]) == \
       (200, "test_id", "test_name")
```

**Benefits**:
- Single assertion shows complete expected state
- Tuple comparison shows all expected vs actual on failure
- Fewer lines, easier to read
- Consistent with recent refactoring (commit: "Refactor tests: replace field-by-field assertions with tuple comparisons")

**Files to Update**:
- `gatelet/gatelet/server/test_report_battery.py:36-37` (1 line saved)
- `claude/claude_hooks/tests/test_models.py:95-96` (1 line)
- `adgn/tests/mcp/test_notifications_envelope.py:36-42,61-64` (5 lines)
- `difftree/tests/test_parser.py:13-17,52-54` (5 lines)
- `claude/claude_optimizer/tests/test_e2e_database.py` (multiple instances, 10+ lines)

---

### 9. Additional Code Smells

#### 9.1 Datetime Without Timezone (**CRITICAL**)

**Count**: 58+ occurrences
**Risk**: Production timezone bugs

**Pattern**:
```python
# WRONG:
datetime.now()  # Naive datetime!

# RIGHT:
datetime.now(UTC)  # Python 3.11+
# OR
datetime.now(timezone.utc)  # Python 3.9+
```

**Critical Files**:
1. `llm/ultra-long-cot/ultra_long_cot_o4.py` - 4 occurrences in session tracking
2. `llm/.../claude_linter_v2/session/state.py` - 5 occurrences
3. `llm/.../claude_linter_v2/session/manager.py` - 3 occurrences
4. `llm/mcp/habitify/habitify_mcp_server/utils/date_utils.py:24,47` - **Utility function returns naive datetime!**

**Impact**:
- Session timestamps may be inconsistent across timezones
- Comparison failures when servers in different timezones
- Daylight saving time bugs

#### 9.2 Type: Ignore Comments

**Count**: 34+ occurrences

**Breakdown**:
- `import-untyped` (9): External libraries without type stubs
- `no-untyped-def` (6): Functions missing annotations
- `assignment` (4): Type mismatches
- `method-assign` (2): Monkey-patching
- `override` (9): Intentional signature changes in tests
- Other (4): Return values, call arguments

**Most Justified**:
- Untyped external libraries (`aiofiles`, etc.)
- Test monkey-patching (`pathlib.Path.iterdir = _safe_iterdir`)

**Should Review**:
- Assignment type ignores - may indicate real type errors
- Check if newer library versions have type stubs

#### 9.3 TODO/FIXME Comments

**Count**: 52+ occurrences

**High Priority**:
1. **Security**: `ember/src/ember/config.py:56` - Pickle key in TOML
2. **API Typing**: `adgn/src/adgn/rspcache/admin_app.py:99` - Type request_body
3. **Error Handling**: `ember/src/ember/history.py:71` - Out-of-context errors

**Medium Priority**:
- API limitations workarounds (Trilium search)
- Missing features (profile activation in linter)
- Test coverage gaps

**Low Priority**:
- Enhancement ideas
- Optional parameters to add

#### 9.4 Magic Numbers

**Well-Defined Constants** (Good examples):
```python
MAX_LIST_LIMIT = 200
MAX_PROMPT_CONTEXT_BYTES = 100 * 1024
MAX_FILE_LINES = 400
```

**Hardcoded Values** (Should be constants):
```python
# Timeouts
await asyncio.sleep(0.01)  # Polling interval
timeout=30  # HTTP timeout
for _ in range(20):  # Max poll attempts

# Should be:
POLL_INTERVAL_SECONDS = 0.01
HTTP_TIMEOUT_SECONDS = 30
MAX_POLL_ATTEMPTS = 20
```

---

## Metrics Summary

### By Severity

| Severity | Categories | Occurrences | Estimated Hours |
|----------|-----------|-------------|-----------------|
| Critical | 3 | 62 | 8-12 hours |
| High | 4 | 117+ | 15-20 hours |
| Medium | 6 | 234+ | 12-18 hours |
| Low | 2 | 22 | 2-4 hours |
| **Total** | **15** | **350+** | **40-60 hours** |

### By Category

| Category | Count | Priority | Effort |
|----------|-------|----------|--------|
| Datetime timezone | 58 | Critical | Medium |
| Enums not enforced | 3 | Critical | Low |
| Security TODO | 1 | Critical | Medium |
| Timestamp naming | 92 | Medium | High (needs migration) |
| Vague fields | 60+ | Medium | High |
| API design | 26 | High | Medium |
| Library misuse | 35 | Medium | Low |
| Manual serialization | 32 | High | Medium |
| Pydantic antipatterns | 19 | Medium | Low |
| Stringly-typed | 40+ | High | Medium |
| Test assertions | 20 | Low | Low |
| Pytest tmp paths | 2 | Low | Low |
| TODOs | 52+ | Medium | Varies |
| Magic numbers | Many | Medium | Medium |
| Type ignores | 34 | Medium | Low |

### Impact Analysis

**Type Safety**: 190+ issues affecting type safety
- Stringly-typed: 40+
- Untyped dicts: 8
- Library misuse: 35
- Manual serialization: 32
- Vague names: 60+
- Enums not enforced: 3

**Maintainability**: 160+ issues affecting maintainability
- Timestamp naming: 92
- Vague fields: 60+
- Magic numbers: Many
- TODOs: 52+

**Correctness**: 62 issues with production impact
- Datetime timezone: 58
- Security: 1
- Enums not enforced: 3

---

## References

- Scan prompts source: `claude/prompts-only-018JJNA3pm4G3rqG1uXkXcVh`
- Industry standards:
  - [Pydantic Documentation](https://docs.pydantic.dev/)
  - [Python StrEnum](https://docs.python.org/3/library/enum.html#enum.StrEnum)
  - [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)
  - [Rails Timestamp Conventions](https://guides.rubyonrails.org/active_record_basics.html#timestamps)

---

## Change Log

- 2025-01-16: Initial comprehensive scan completed
  - Scanned 100+ Python files
  - Identified 350+ issues across 14 categories
  - Created action item checklist
  - Established priority matrix

---

*End of Report*
