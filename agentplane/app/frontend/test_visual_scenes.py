"""Agentplane render-only checkpoints; interactions live in the feature tests."""

import pytest
import pytest_bazel

from agentplane.app.frontend.visual_pages import capture_scene, open_scene
from util.testing.visual_capture import VisualHarness

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    "scene",
    [
        "session_recovery_messages",
        "session_recovery_messages_phone",
        "session_recovery_tools",
        "session_recovery_quiet",
        "session_error",
        "session_error_phone",
        "session_interleaved",
        "session_lifecycle_group",
        "session_thread_setup",
        "threads",
        "threads_phone",
        "threads_failed_turn",
        "threads_provisioning",
        "threads_updates_disconnected",
        "threads_watch_stale",
        "sandboxes",
        "sandboxes_phone",
        "sandboxes_stale",
        "actions_attention_composer_desktop",
        "actions_attention_composer_phone",
        "actions",
        "actions_phone",
        "actions_history_groups_unavailable",
        "actions_hidden_codepoints",
        "consent",
        "consent_phone",
        "sandbox",
        "sandbox_phone",
        "sandbox_status",
        "sandbox_status_phone",
        "sandbox_status_grant_error",
        "sandbox_policy",
        "sandbox_policy_phone",
        "session",
        "session_deleted_sandbox",
        "session_deleted_sandbox_phone",
        "session_suspended_sandbox",
        "session_suspended_sandbox_phone",
        "session_inventory_stale",
        "session_inventory_stale_phone",
        "session_inventory_dropped",
        "session_inventory_dropped_phone",
        "session_phone",
        "session_unnamed",
        "session_unnamed_phone",
        "session_markdown_code_fence",
        "session_standalone_reasoning",
        "session_standalone_reasoning_preview",
        "session_unfinished_reasoning",
        "session_unfinished_reasoning_phone",
        "session_reasoning_code_fence",
        "session_reasoning_code_fence_phone",
        "session_states",
        "session_streaming_interleaved",
        "session_resume",
        "session_pending",
        "session_pending_phone",
        "session_pending_failed",
        "session_pending_controls",
        "session_command_outcomes_phone",
        "session_catching_up",
        "session_sync_unavailable",
        "session_sync_reconnecting",
        "session_sync_reconnecting_phone",
        "session_states_phone",
    ],
)
async def test_scene(visual: VisualHarness, scene: str) -> None:
    async with open_scene(visual, scene) as view:
        await capture_scene(view, scene)


if __name__ == "__main__":
    pytest_bazel.main()
