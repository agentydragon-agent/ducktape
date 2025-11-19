# Code Quality Scan Report: Useless Test Classes

**Scan Date**: 2025-11-19
**Repository**: ducktape
**Total Violations Found**: 41
**Files Affected**: 19

## Overview

This scan identifies pytest test classes that don't provide value and should be converted to module-level test functions. These classes:

1. Don't define any class-level fixtures (via `@pytest.fixture` decorators)
2. Don't have setup/teardown methods (`setup_method`, `teardown_method`, `setup_class`, `teardown_class`)
3. Don't maintain shared state between tests
4. Only use module-level fixtures from conftest.py
5. Are just containers for grouping related tests

### Why This Matters

- **Readability**: Unnecessary indentation and boilerplate obscure actual test logic
- **Misleading semantics**: Tests appear to have shared state/setup when they don't
- **Performance**: Class-based tests have a minimal but measurable performance cost
- **YAGNI principle**: The infrastructure isn't being used ("You Aren't Gonna Need It")
- **Pytest organization**: Module-level functions with naming conventions work just as well

## Detailed Violations


### adgn/tests/agent/server/test_mcp_routing.py

**Class:** `TestMCPRouting` (line 52)

**Documentation:** Tests for token-based MCP routing middleware.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestTokenTable` (line 187)

**Documentation:** Tests for the token table structure.

**Test Methods:** 3 total
- test_default_token_table_structure
- test_human_token_no_agent_id
- test_agent_token_has_agent_id

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### adgn/tests/mcp/approval_policy/test_policy_resources.py

**Class:** `TestPolicyListResource` (line 67)

**Documentation:** Test the policy list resource.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestPolicyDetailResource` (line 122)

**Documentation:** Test the policy detail resource.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestCreatePolicyTool` (line 156)

**Documentation:** Test the create_policy admin tool.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestUpdatePolicyTool` (line 224)

**Documentation:** Test the update_policy admin tool.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestDeletePolicyTool` (line 296)

**Documentation:** Test the delete_policy admin tool.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestPolicyPagination` (line 337)

**Documentation:** Test pagination in policy list.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestErrorHandling` (line 363)

**Documentation:** Test error handling in policy CRUD operations.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### claude/claude_optimizer/tests/test_e2e_database.py

**Class:** `TestYamlDatabaseSync` (line 23)

**Documentation:** Test YAML file synchronization with database.

**Test Methods:** 3 total
- test_sync_seed_tasks
- test_sync_grading_criteria
- test_content_hash_change_detection

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestDatabaseModels` (line 100)

**Documentation:** Test database models and relationships.

**Test Methods:** 3 total
- test_optimization_run_creation
- test_system_prompt_with_content_hash
- test_rollout_file_integrity_checking

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### claude/claude_optimizer/tests/test_file_truncation.py

**Class:** `TestFileTruncation` (line 9)

**Documentation:** Test centralized file truncation logic.

**Test Methods:** 9 total
- test_files_under_limit_unchanged
- test_single_large_file_truncated
- test_multiple_files_some_skipped
- test_token_limit_assertion
- test_largest_files_truncated_first
- test_empty_files_list
- test_preserves_file_structure
- test_binary_search_truncation_efficiency
- test_real_world_scenario

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### claude/claude_optimizer/tests/test_optimizer.py

**Class:** `TestPatternSummarizer` (line 37)

**Documentation:** Test pattern summarization functionality.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestPromptEngineer` (line 120)

**Documentation:** Test prompt engineering conversation management.

**Test Methods:** 4 total
- test_initialization_full_rollouts
- test_initialization_summary_mode
- test_context_trimming
- test_build_grades_message

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestOptimizerConfig` (line 235)

**Documentation:** Test configuration management.

**Test Methods:** 2 total
- test_config_from_file_like
- test_config_validation

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestDockerManager` (line 271)

**Documentation:** Test Docker management functionality.

**Test Methods:** 4 total
- test_docker_manager_init
- test_docker_not_found
- test_setup_wrapper
- test_cleanup

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestHelperFunctions` (line 329)

**Documentation:** Test helper functions.

**Test Methods:** 3 total
- test_logging_openai_model
- test_log_openai_request_response
- test_log_anthropic_request_event

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestMessageLogging` (line 379)

**Documentation:** Test message logging functionality.

**Test Methods:** 2 total
- test_log_system_message
- test_log_assistant_message_with_tools

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter/test_claude_linter.py

**Class:** `TestUnifiedLinter` (line 15)

**Documentation:** Test cases for the unified linter entry point.

**Test Methods:** 7 total
- test_pre_mode
- test_post_mode
- test_invalid_mode
- test_no_mode
- test_help
- test_debug_logs_not_created_by_default
- test_debug_logs_created_when_enabled

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter/test_claude_post_hook.py

**Class:** `TestPostHook` (line 63)

**Documentation:** Test cases for the post-hook.

**Test Methods:** 7 total
- test_fixes_violations
- test_reports_fixes
- test_handles_clean_files
- test_ignores_non_python
- test_handles_edit_tool
- test_ignores_other_tools
- test_formats_code

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter/test_claude_pre_hook.py

**Class:** `TestPreHook` (line 44)

**Documentation:** Test cases for the pre-hook.

**Test Methods:** 6 total
- test_blocks_non_fixable_violations
- test_allows_clean_files
- test_allows_auto_fixable_only
- test_ignores_non_python_files
- test_ignores_other_tools
- test_invalid_json

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter/test_hooks.py

**Class:** `TestHooks` (line 104)

**Documentation:** Consolidated hook tests using parametrization.

**Test Methods:** 3 total
- test_pre_hook_approve
- test_pre_hook_block
- test_post_hook_with_change

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence.py

**Class:** `TestDiffParser` (line 14)

**Documentation:** Test diff parsing functionality.

**Test Methods:** 3 total
- test_parse_edit_tool
- test_parse_multiedit_tool
- test_parse_other_tools_returns_none

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestViolationCategorizer` (line 77)

**Documentation:** Test violation categorization.

**Test Methods:** 3 total
- test_categorize_in_diff
- test_categorize_near_diff
- test_filter_by_priority

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestDiffIntelligence` (line 152)

**Documentation:** Test the main diff intelligence module.

**Test Methods:** 1 total
- test_format_violations_by_category

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence_edge_cases.py

**Class:** `TestDiffParserEdgeCases` (line 11)

**Documentation:** Test edge cases in diff parsing.

**Test Methods:** 5 total
- test_parse_edit_with_context_lines
- test_parse_multiedit_with_line_shifts
- test_parse_empty_structured_patch
- test_parse_no_structured_patch_field
- test_parse_special_diff_markers

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestDiffIntelligenceEdgeCases` (line 117)

**Documentation:** Test edge cases in diff intelligence.

**Test Methods:** 4 total
- test_no_violations
- test_overlapping_near_regions
- test_pretooluse_all_out_of_diff
- test_format_many_violations

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_integration.py

**Class:** `TestCLIIntegration` (line 10)

**Documentation:** Test the full CLI integration.

**Test Methods:** 8 total
- test_pre_hook_bare_except
- test_pre_hook_hasattr
- test_pre_hook_clean_code
- test_pre_hook_ruff_violation
- test_pre_hook_barrel_init
- test_pre_hook_invalid_json
- test_pre_hook_non_python_file
- test_post_hook_basic

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestSessionCommands` (line 240)

**Documentation:** Test session management commands.

**Test Methods:** 2 total
- test_session_list
- test_session_allow

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ast.py

**Class:** `TestBareExcept` (line 6)

**Documentation:** Test bare except detection.

**Test Methods:** 3 total
- test_detects_bare_except
- test_allows_specific_except
- test_disabled_check

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestGetAttrSetAttr` (line 54)

**Documentation:** Test hasattr/getattr/setattr detection.

**Test Methods:** 5 total
- test_detects_hasattr
- test_detects_getattr
- test_detects_setattr
- test_allows_regular_attributes
- test_allows_attribute_access

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestBarrelInit` (line 132)

**Documentation:** Test barrel __init__.py detection.

**Test Methods:** 4 total
- test_detects_star_import
- test_detects_reexport_pattern
- test_allows_minimal_init
- test_ignores_non_init_files

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestMultipleViolations` (line 189)

**Documentation:** Test detection of multiple violations.

**Test Methods:** 1 total
- test_multiple_violations

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestSyntaxErrors` (line 211)

**Documentation:** Test handling of syntax errors.

**Test Methods:** 1 total
- test_syntax_error_handling

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_python_formatter.py

**Class:** `TestPythonFormatter` (line 9)

**Documentation:** Test Python code formatting functionality.

**Test Methods:** 10 total
- test_check_available_tools
- test_format_with_ruff_success
- test_format_with_black_success
- test_no_changes_needed
- test_formatting_error
- test_fix_imports
- test_no_tools_available
- test_all_categories
- test_selective_categories
- test_file_path_passed_to_tools

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ruff.py

**Class:** `TestPythonRuffLinter` (line 9)

**Documentation:** Test Python ruff linter functionality.

**Test Methods:** 11 total
- test_check_ruff_available
- test_check_code_with_violations
- test_check_code_clean
- test_critical_only_filtering
- test_force_select_rules
- test_fixable_violations
- test_ruff_error_handling
- test_json_parse_error
- test_rule_explanations
- test_no_ruff_available
- test_file_path_passed_to_ruff

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### wt/tests/cli/test_cli_click_integration.py

**Class:** `TestNewCLIIntegration` (line 19)

**Test Methods:** 6 total
- test_default_status_command
- test_list_worktrees_command
- test_list_worktrees_with_data
- test_help_command
- test_help_flag
- test_status_command_with_pr_flag

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### wt/tests/integration/test_cli_output_format.py

**Class:** `TestCLIOutputFormat` (line 27)

**Test Methods:** 2 total
- test_status_table_rendering
- test_status_unknown_when_not_cached

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### wt/tests/integration/test_shell_integration.py

**Class:** `TestShellIntegration` (line 31)

**Test Methods:** 4 total
- test_help_command_basic
- test_shell_script_execution_basic
- test_successful_teleport_with_pwd_verification
- test_wt_main_changes_directory

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.

**Class:** `TestShellIntegrationEdgeCases` (line 152)

**Test Methods:** 1 total
- test_shell_environment_isolation

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


### wt/tests/test_data.py

**Class:** `TestData` (line 11)

**Documentation:** Centralized test data constants.

**Test Methods:** None found (may contain helper methods only)

**Recommendation:** Convert to module-level functions. Remove the class wrapper and dedent all methods.


## Summary Statistics

- **Total Test Classes Found:** 41
- **Files Affected:** 19
- **Test Methods in Useless Classes:** 130

### Distribution by Test Method Count

- Classes with 0 test methods: 10
- Classes with 1 test methods: 4
- Classes with 2 test methods: 4
- Classes with 3 test methods: 8
- Classes with 4 test methods: 5
- Classes with 5 test methods: 2
- Classes with 6 test methods: 2
- Classes with 7 test methods: 2
- Classes with 8 test methods: 1
- Classes with 9 test methods: 1
- Classes with 10 test methods: 1
- Classes with 11 test methods: 1

### Files with Most Violations

- adgn/tests/mcp/approval_policy/test_policy_resources.py: 7 violation(s)
- claude/claude_optimizer/tests/test_optimizer.py: 6 violation(s)
- llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ast.py: 5 violation(s)
- llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence.py: 3 violation(s)
- adgn/tests/agent/server/test_mcp_routing.py: 2 violation(s)
- claude/claude_optimizer/tests/test_e2e_database.py: 2 violation(s)
- llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence_edge_cases.py: 2 violation(s)
- llm/ducktape_llm_common/tests/claude_linter_v2/test_integration.py: 2 violation(s)
- wt/tests/integration/test_shell_integration.py: 2 violation(s)
- claude/claude_optimizer/tests/test_file_truncation.py: 1 violation(s)


## Conversion Guide

### Step 1: Move Class Docstring to Module Docstring
If the class has a docstring, move it to the top of the module as a module-level docstring (after imports).

### Step 2: Convert Each Test Method
For each method in the class:
1. Remove `self` from method parameters
2. Dedent the method body by one level (remove 4 spaces)
3. Keep all fixture parameters - they work the same at module level

### Step 3: Update Test Names (Optional but Recommended)
When test names become ambiguous without the class context, rename them to include context:
- Before: `class TestClient: def test_init(...)`
- After: `def test_client_init(...)`

### Step 4: Verify
Run the tests to ensure they still pass:
```bash
pytest path/to/test_file.py -v
```

## Example Conversion

### Before
```python
class TestHabitifyClient:
    """Tests for the Habitify client using async methods only."""

    async def test_get_habits(self, client, mock_async_response, patch_client_method):
        mock_resp = mock_async_response("get_habits.yaml")
        with patch_client_method("get", return_value=mock_resp) as mock_get:
            habits = await client.get_habits()
            assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
```

### After
```python
"""Tests for the Habitify client using async methods only."""

async def test_habitify_client_get_habits(client, mock_async_response, patch_client_method):
    mock_resp = mock_async_response("get_habits.yaml")
    with patch_client_method("get", return_value=mock_resp) as mock_get:
        habits = await client.get_habits()
        assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
```

## False Positives (Classes to Keep)

These patterns indicate a class **should NOT be converted**:

1. **Class-level fixtures** - Provides expensive shared setup
2. **Setup/teardown methods** - Manages state across tests
3. **Shared instance attributes** - Mutable state used by multiple tests
4. **Inheritance hierarchies** - Base test classes with behavior
5. **Class-level markers** - Only if the marker applies semantics (not just grouping)

## Next Steps

1. Review each violation file manually
2. Convert test classes to module-level functions
3. Run full test suite to verify no regressions
4. Consider adding a pre-commit hook to prevent new violations
