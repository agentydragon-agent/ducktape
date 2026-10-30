"""System scenarios sharing one pod k3s stack."""

import pytest_bazel

from agentplane.system_tests.executor_environment import pod_executor as executor_environment
from agentplane.system_tests.scenarios.agent_messaging import (
    test_an_agent_messages_another_which_reads_and_acknowledges_it,
)
from agentplane.system_tests.scenarios.egress import (
    test_a_bound_sandbox_reaches_what_its_policy_names_and_nothing_else,
    test_a_policy_granted_after_the_sandbox_is_running_takes_effect,
    test_the_model_call_itself_goes_through_the_proxy,
)
from agentplane.system_tests.scenarios.launch_presets import test_a_preset_launches_an_initialized_editable_codex_thread
from agentplane.system_tests.scenarios.runner_credentials import (
    test_cert_manager_reissues_a_deleted_tls_secret,
    test_pod_mtls_session_survives_replacement_and_keeps_history,
)
from agentplane.system_tests.scenarios.session_instructions import (
    test_the_model_obeys_the_standing_instruction_its_session_was_opened_with,
    test_the_standing_instruction_reaches_the_model_and_only_in_its_own_session,
)
from agentplane.system_tests.scenarios.storage import test_fresh_workspace_storage_survives_replacement
from agentplane.system_tests.scenarios.suspend_resume import (
    test_codex_standing_instructions_after_suspend_and_compact,
    test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume,
)
from agentplane.system_tests.scenarios.thread_stream import (
    http,
    test_an_unknown_thread_is_not_found,
    test_every_tab_follows_one_log_and_a_reconnect_resumes_after_its_last_event,
    test_turns_nobody_watches_are_archived_and_a_failed_one_leaves_the_next_input_its_own_turn,
)

__all__ = [
    "executor_environment",
    "http",
    "test_a_bound_sandbox_reaches_what_its_policy_names_and_nothing_else",
    "test_a_policy_granted_after_the_sandbox_is_running_takes_effect",
    "test_a_preset_launches_an_initialized_editable_codex_thread",
    "test_an_agent_messages_another_which_reads_and_acknowledges_it",
    "test_an_unknown_thread_is_not_found",
    "test_cert_manager_reissues_a_deleted_tls_secret",
    "test_codex_standing_instructions_after_suspend_and_compact",
    "test_every_tab_follows_one_log_and_a_reconnect_resumes_after_its_last_event",
    "test_fresh_workspace_storage_survives_replacement",
    "test_pod_mtls_session_survives_replacement_and_keeps_history",
    "test_the_model_call_itself_goes_through_the_proxy",
    "test_the_model_obeys_the_standing_instruction_its_session_was_opened_with",
    "test_the_standing_instruction_reaches_the_model_and_only_in_its_own_session",
    "test_turns_nobody_watches_are_archived_and_a_failed_one_leaves_the_next_input_its_own_turn",
    "test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume",
]

if __name__ == "__main__":
    pytest_bazel.main()
