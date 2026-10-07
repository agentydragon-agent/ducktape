"""Agentplane fixture loading and capture metadata shared by its visual tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from playwright.async_api import expect

from util.testing.viewports import DESKTOP, MOBILE, MOBILE_TOUCH, SMALL_MOBILE
from util.testing.visual_capture import VisualHarness, VisualPage


@asynccontextmanager
async def open_scene(visual: VisualHarness, name: str) -> AsyncIterator[VisualPage]:
    match name:
        case (
            "session_recovery_messages"
            | "session_recovery_tools"
            | "session_recovery_quiet"
            | "session_error"
            | "session_interleaved"
            | "session_lifecycle_group"
            | "session_thread_setup"
            | "threads"
            | "threads_failed_turn"
            | "threads_provisioning"
            | "threads_updates_disconnected"
            | "threads_watch_stale"
            | "sandboxes"
            | "sandboxes_stale"
            | "actions_attention_composer_desktop"
            | "actions"
            | "actions_history_groups_unavailable"
            | "actions_hidden_codepoints"
            | "consent"
            | "sandbox"
            | "sandbox_status"
            | "sandbox_status_grant_error"
            | "sandbox_policy"
            | "session"
            | "session_deleted_sandbox"
            | "session_suspended_sandbox"
            | "session_inventory_stale"
            | "session_inventory_dropped"
            | "session_unnamed"
            | "session_markdown_code_fence"
            | "session_standalone_reasoning"
            | "session_unfinished_reasoning"
            | "session_reasoning_code_fence"
            | "session_states"
            | "session_streaming_interleaved"
            | "session_resume"
            | "session_pending"
            | "session_pending_failed"
            | "session_pending_controls"
            | "session_catching_up"
            | "session_sync_unavailable"
            | "session_sync_reconnecting"
            | "new_sandbox"
            | "new_sandbox_policies"
            | "new_sandbox_grants"
            | "sandbox_egress"
            | "actions_history"
            | "actions_history_more"
            | "actions_history_raw"
            | "mcp_servers"
            | "session_recovery_tools_open"
            | "session_tool_payloads"
            | "session_shell_calls_open"
            | "session_compact_run"
            | "session_tool_output_sticky"
            | "session_recovery_messages_open"
            | "session_recovery_quiet_open"
            | "session_error_raw"
            | "session_interleaved_raw"
            | "session_thread_setup_open"
            | "session_interleaved_disclosures"
            | "threads_archived"
            | "threads_disconnected"
            | "sandboxes_claude_paused"
            | "actions_attention_composer_long_desktop"
            | "actions_attention_composer_open_desktop"
            | "actions_raw"
            | "connections"
            | "consent_reconnect"
            | "sandbox_claude_paused"
            | "sandbox_status_raw"
            | "session_more_menu"
            | "session_reasoning"
            | "session_reasoning_sticky"
            | "session_standalone_reasoning_open"
            | "session_reasoning_code_fence_open"
            | "session_shell_calls"
            | "session_evidence"
            | "session_evidence_hover_bubble"
            | "session_evidence_hover_reply"
            | "session_raw"
            | "session_pending_raw"
            | "realistic_rollout_desktop"
            | "reported_rollout_desktop"
            | "realistic_rollout_desktop_dark"
        ):
            viewport = DESKTOP
        case (
            "session_recovery_messages_phone"
            | "session_error_phone"
            | "threads_phone"
            | "sandboxes_phone"
            | "actions_attention_composer_phone"
            | "actions_phone"
            | "consent_phone"
            | "sandbox_phone"
            | "sandbox_status_phone"
            | "sandbox_policy_phone"
            | "session_deleted_sandbox_phone"
            | "session_suspended_sandbox_phone"
            | "session_inventory_stale_phone"
            | "session_inventory_dropped_phone"
            | "session_phone"
            | "session_unnamed_phone"
            | "session_standalone_reasoning_preview"
            | "session_unfinished_reasoning_phone"
            | "session_reasoning_code_fence_phone"
            | "session_pending_phone"
            | "session_command_outcomes_phone"
            | "session_sync_reconnecting_phone"
            | "session_states_phone"
            | "new_sandbox_phone"
            | "new_sandbox_policies_phone"
            | "new_sandbox_grants_phone"
            | "sandbox_egress_phone"
            | "actions_history_phone"
            | "mcp_servers_phone"
            | "consent_reconnect_phone"
            | "session_recovery_tools_open_phone"
            | "session_tool_payloads_phone"
            | "session_shell_calls_open_phone"
            | "session_compact_run_phone"
            | "session_tool_output_sticky_phone"
            | "disclosure_component_phone_collapsed"
            | "disclosure_component_phone_short_expanded"
            | "disclosure_component_phone_long_top"
            | "disclosure_component_phone_long_scrolled"
            | "disclosure_component_phone_after_disclosure"
            | "disclosure_component_phone_nested_child_scrolled"
            | "disclosure_component_phone_nested_after_child"
            | "disclosure_component_phone_nested_parent_only"
            | "disclosure_component_phone_nested_after_outer"
            | "disclosure_component_phone_nested_wrapped_headings"
            | "disclosure_component_phone_nested_expanded_output"
            | "disclosure_component_phone_nested_before_output"
            | "disclosure_component_phone_nested_after_output"
            | "disclosure_component_phone_nested_output_collapsed"
            | "session_recovery_messages_open_phone"
            | "session_error_raw_phone"
            | "session_interleaved_raw_phone"
            | "session_phone_drawer_over_active_thread"
            | "threads_phone_drawer"
            | "threads_failed_turn_phone_drawer"
            | "threads_provisioning_phone"
            | "threads_disconnected_phone"
            | "actions_attention_composer_long_phone"
            | "actions_attention_composer_open_phone"
            | "connections_phone"
            | "sandbox_status_raw_phone"
            | "session_more_menu_phone"
            | "session_reasoning_phone"
            | "session_reasoning_sticky_phone"
            | "session_reasoning_code_fence_open_phone"
            | "session_shell_calls_phone"
            | "session_evidence_phone"
            | "session_raw_phone"
            | "realistic_rollout_mobile"
        ):
            viewport = MOBILE
        case "session_phone_controls":
            viewport = SMALL_MOBILE
        case "session_evidence_tap_phone":
            viewport = MOBILE_TOUCH
        case _:
            raise ValueError(f"unknown Agentplane visual fixture: {name}")
    color_scheme: Literal["light", "dark"] = "dark" if name == "realistic_rollout_desktop_dark" else "light"
    async with visual.open(name, viewport=viewport, color_scheme=color_scheme) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        match name:
            case "session_recovery_messages" | "session_recovery_messages_phone" | "session_recovery_tools":
                await view.page.wait_for_selector('[aria-label="Retention unknown"]', state="attached")
            case "session_recovery_quiet" | "session_lifecycle_group":
                await view.page.wait_for_selector('[data-thread-anchor="50"]', state="attached")
            case "session_error":
                await view.page.wait_for_selector('[data-thread-anchor="6"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-thread-status-indicator[data-status="turn_error"]', state="attached"
                )
            case "session_error_phone":
                await view.page.wait_for_selector('[data-thread-anchor="8"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-thread-status-indicator[data-status="turn_error"]', state="attached"
                )
            case "session_interleaved":
                await view.page.wait_for_selector('[data-thread-anchor="18"]', state="attached")
            case "session_thread_setup":
                await view.page.wait_for_selector(':text("Thread setup complete")', state="attached")
            case "threads":
                await view.page.wait_for_selector("a.agentplane-sidebar-group-name", state="attached")
            case "threads_failed_turn":
                await view.page.wait_for_selector(
                    ".agentplane-thread-status-indicator[data-status='turn_error']", state="attached"
                )
            case "threads_provisioning":
                await view.page.wait_for_selector('a[href="#/sandboxes/test-provisioning"]', state="attached")
            case "threads_updates_disconnected" | "threads_watch_stale" | "session_sync_unavailable":
                await view.page.wait_for_selector('[role="alert"]', state="attached")
            case "actions_attention_composer_desktop" | "actions_attention_composer_phone":
                await view.page.wait_for_selector('button[aria-label="Actions, 2 pending"]', state="attached")
                await view.page.wait_for_selector(".action-affordance-notice", state="attached")
            case (
                "actions"
                | "actions_phone"
                | "session_tool_payloads"
                | "session_tool_payloads_phone"
                | "session_shell_calls_open"
                | "session_shell_calls_open_phone"
                | "session_compact_run"
                | "session_compact_run_phone"
                | "session_tool_output_sticky"
                | "session_tool_output_sticky_phone"
            ):
                await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
            case "actions_history_groups_unavailable":
                await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
                await view.page.wait_for_selector('[role="alert"]', state="attached")
            case "actions_hidden_codepoints":
                await view.page.wait_for_selector(".cm-agentplane-special-char-bidi", state="attached")
                await view.page.wait_for_selector(".cm-agentplane-special-char-ignorable", state="attached")
                await view.page.wait_for_selector(".cm-agentplane-special-char-control", state="attached")
            case "session" | "session_phone" | "session_unnamed" | "session_unnamed_phone":
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_deleted_sandbox" | "session_deleted_sandbox_phone":
                await view.page.wait_for_selector('[role="status"]', state="attached")
            case "session_suspended_sandbox" | "session_suspended_sandbox_phone":
                await view.page.wait_for_selector(':text("Last observed Sandbox and Pod")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_inventory_stale":
                await view.page.wait_for_selector(':text("so this page is not being updated")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_inventory_stale_phone":
                await view.page.wait_for_selector(':text("Current availability unknown")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_inventory_dropped":
                await view.page.wait_for_selector('[data-connection="stale"]', state="attached")
                await view.page.wait_for_selector(':text("may be out of date")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_inventory_dropped_phone":
                await view.page.wait_for_selector(':text("may be out of date")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_markdown_code_fence":
                await view.page.wait_for_selector(".agentplane-code-block", state="attached")
            case "session_standalone_reasoning":
                await view.page.wait_for_selector(
                    '[data-thread-anchor="20"] .agentplane-step-preview .agentplane-markdown--single-line',
                    state="attached",
                )
            case "session_standalone_reasoning_preview":
                await view.page.wait_for_selector(
                    '[data-thread-anchor="20"] .agentplane-step-details .agentplane-disclosure-summary:not(:has(a))',
                    state="attached",
                )
            case "session_unfinished_reasoning" | "session_unfinished_reasoning_phone":
                await view.page.wait_for_selector(".agentplane-step-title--streaming", state="attached")
            case "session_reasoning_code_fence" | "session_reasoning_code_fence_phone":
                await view.page.wait_for_selector(
                    '[data-thread-anchor="20"] .agentplane-step-preview .agentplane-code-inline', state="attached"
                )
            case "session_states":
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="failed"]', state="attached"
                )
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="noop"]', state="attached"
                )
                await view.page.wait_for_selector(
                    '.agentplane-thread-status-indicator[data-status="running"]', state="attached"
                )
            case "session_streaming_interleaved":
                await view.page.wait_for_selector(
                    '.agentplane-streaming-cursor[aria-label="Streaming"]', state="attached"
                )
                await view.page.wait_for_selector(
                    '[aria-label="Thread history"][data-layout-settled="true"]', state="attached"
                )
            case "session_resume":
                await view.page.wait_for_selector('[aria-label="Harness not running"]', state="attached")
                await view.page.wait_for_selector('[aria-label="Resume harness"]', state="attached")
            case "session_pending" | "session_pending_phone":
                await view.page.wait_for_selector('[aria-label="Pending commands"]', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="local"]', state="attached"
                )
            case "session_pending_failed":
                await view.page.wait_for_selector(
                    ':text("Admission unconfirmed · checking Thread history")', state="attached"
                )
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="local"]', state="attached"
                )
            case "session_pending_controls":
                await view.page.wait_for_selector('[data-command-id="queued-interrupt"]', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
            case "session_command_outcomes_phone":
                await view.page.wait_for_selector('[aria-label="Pending commands"]', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="failed"]', state="attached"
                )
                await view.page.wait_for_selector(
                    '.agentplane-user-bubble[data-message-phase="noop"]', state="attached"
                )
            case "session_catching_up":
                await view.page.wait_for_selector('[data-thread-catchup="true"]', state="attached")
            case "session_sync_reconnecting":
                await view.page.wait_for_selector(
                    '[aria-label="Runner feed active · harness running"]', state="attached"
                )
                await view.page.wait_for_selector('[data-connection="degraded"]', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_sync_reconnecting_phone":
                await view.page.wait_for_selector(
                    '[aria-label="Runner feed active · harness running"]', state="attached"
                )
                await view.page.wait_for_selector(':text("may be out of date")', state="attached")
                await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
            case "session_states_phone":
                await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
            case "new_sandbox" | "new_sandbox_phone" | "new_sandbox_grants" | "new_sandbox_grants_phone":
                await view.page.wait_for_selector(".mantine-Pill-root", state="attached")
            case "new_sandbox_policies" | "new_sandbox_policies_phone":
                await view.page.wait_for_selector('.mantine-Pill-root:has-text("github-public")', state="attached")
            case "actions_history" | "actions_history_phone":
                await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
                await view.page.wait_for_selector('img[src^="data:image/"]', state="attached")
            case "actions_history_more":
                await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
                await view.page.wait_for_selector('[data-testid="action-history-load-more"]', state="attached")
            case "mcp_servers" | "mcp_servers_phone":
                await view.page.wait_for_selector("[data-mcp-server]", state="attached")
            case "disclosure_component_phone_collapsed":
                await view.page.wait_for_selector(
                    ".demo-main .agentplane-disclosure-summary[aria-expanded='false']", state="attached"
                )
            case "disclosure_component_phone_short_expanded" | "disclosure_component_phone_long_top":
                await view.page.wait_for_selector(
                    ".demo-main .agentplane-disclosure-summary[aria-expanded='true']", state="attached"
                )
            case "disclosure_component_phone_long_scrolled":
                await view.page.wait_for_selector(
                    ".demo-main .agentplane-disclosure-heading[data-expanded='true']", state="attached"
                )
            case "disclosure_component_phone_after_disclosure":
                await view.page.wait_for_selector("[data-disclosure-visual-stage='after-disclosure']", state="attached")
            case "disclosure_component_phone_nested_child_scrolled":
                await view.page.wait_for_selector(
                    ".demo-inner .agentplane-disclosure-heading[data-expanded='true']", state="attached"
                )
            case "disclosure_component_phone_nested_after_child":
                await view.page.wait_for_selector(
                    ".demo-outer .agentplane-disclosure-heading[data-expanded='true']", state="attached"
                )
            case (
                "disclosure_component_phone_nested_parent_only"
                | "disclosure_component_phone_nested_after_outer"
                | "disclosure_component_phone_nested_wrapped_headings"
            ):
                await view.page.wait_for_selector(".demo-outer .agentplane-disclosure-heading", state="attached")
                await view.page.wait_for_selector(".demo-inner .agentplane-disclosure-heading", state="attached")
            case (
                "disclosure_component_phone_nested_expanded_output"
                | "disclosure_component_phone_nested_before_output"
                | "disclosure_component_phone_nested_after_output"
                | "disclosure_component_phone_nested_output_collapsed"
            ):
                await view.page.wait_for_selector(".demo-outer .agentplane-disclosure-heading", state="attached")
                await view.page.wait_for_selector(".demo-inner .agentplane-disclosure-heading", state="attached")
                await view.page.wait_for_selector(".demo-output .agentplane-disclosure-heading", state="attached")
            case (
                "session_phone_drawer_over_active_thread"
                | "realistic_rollout_desktop"
                | "realistic_rollout_mobile"
                | "reported_rollout_desktop"
                | "realistic_rollout_desktop_dark"
            ):
                await view.page.wait_for_selector(
                    "[aria-label='Thread history'][data-layout-settled='true']", state="attached"
                )
            case "sandboxes_claude_paused" | "sandbox_claude_paused":
                await view.page.wait_for_selector('[role="option"][data-combobox-disabled]', state="attached")
        await view.check(context=name)
        yield view


async def capture_scene(view: VisualPage, name: str, *, output_name: str | None = None) -> None:
    output_names = {
        "threads_phone": "threads-phone",
        "sandboxes_phone": "sandboxes-phone",
        "sandbox_phone": "sandbox-phone",
        "sandbox_status": "sandbox-status",
        "sandbox_status_phone": "sandbox-status-phone",
        "sandbox_status_grant_error": "sandbox-status-grant-error",
        "sandbox_policy": "sandbox-policy",
        "sandbox_policy_phone": "sandbox-policy-phone",
        "session_phone": "session-phone",
        "session_markdown_code_fence": "session-markdown-code-fence",
        "session_standalone_reasoning": "session-standalone-reasoning",
        "session_standalone_reasoning_preview": "session-standalone-reasoning-preview",
        "session_unfinished_reasoning": "session-unfinished-reasoning",
        "session_unfinished_reasoning_phone": "session-unfinished-reasoning-phone",
        "session_reasoning_code_fence": "session-reasoning-code-fence",
        "session_reasoning_code_fence_phone": "session-reasoning-code-fence-phone",
        "session_states": "session-states",
        "session_streaming_interleaved": "session-streaming-interleaved",
        "session_states_phone": "session-states-phone",
        "new_sandbox": "new-sandbox",
        "new_sandbox_phone": "new-sandbox-phone",
        "new_sandbox_policies": "new-sandbox-policies",
        "new_sandbox_policies_phone": "new-sandbox-policies-phone",
        "new_sandbox_grants": "new-sandbox-grants",
        "new_sandbox_grants_phone": "new-sandbox-grants-phone",
        "sandbox_egress": "sandbox-egress",
        "sandbox_egress_phone": "sandbox-egress-phone",
        "session_tool_payloads": "session-tool-payloads",
        "session_tool_payloads_phone": "session-tool-payloads-phone",
        "session_shell_calls_open": "session-shell-calls-open",
        "session_shell_calls_open_phone": "session-shell-calls-open-phone",
        "session_tool_output_sticky": "session-tool-output-sticky",
        "session_tool_output_sticky_phone": "session-tool-output-sticky-phone",
        "disclosure_component_phone_collapsed": "disclosure-component-phone-collapsed",
        "disclosure_component_phone_short_expanded": "disclosure-component-phone-short-expanded",
        "disclosure_component_phone_long_top": "disclosure-component-phone-long-top",
        "disclosure_component_phone_long_scrolled": "disclosure-component-phone-long-scrolled",
        "disclosure_component_phone_after_disclosure": "disclosure-component-phone-after-disclosure",
        "disclosure_component_phone_nested_child_scrolled": "disclosure-component-phone-nested-child-scrolled",
        "disclosure_component_phone_nested_after_child": "disclosure-component-phone-nested-after-child",
        "disclosure_component_phone_nested_parent_only": "disclosure-component-phone-nested-parent-only",
        "disclosure_component_phone_nested_after_outer": "disclosure-component-phone-nested-after-outer",
        "disclosure_component_phone_nested_wrapped_headings": "disclosure-component-phone-nested-wrapped-headings",
        "disclosure_component_phone_nested_expanded_output": "disclosure-component-phone-nested-expanded-output",
        "disclosure_component_phone_nested_before_output": "disclosure-component-phone-nested-before-output",
        "disclosure_component_phone_nested_after_output": "disclosure-component-phone-nested-after-output",
        "disclosure_component_phone_nested_output_collapsed": "disclosure-component-phone-nested-output-collapsed",
        "threads_phone_drawer": "threads-phone-drawer",
        "threads_failed_turn_phone_drawer": "threads-failed-turn-phone-drawer",
        "sandbox_status_raw": "sandbox-status-raw",
        "sandbox_status_raw_phone": "sandbox-status-raw-phone",
        "session_reasoning": "session-reasoning",
        "session_reasoning_phone": "session-reasoning-phone",
        "session_reasoning_sticky": "session-reasoning-sticky",
        "session_reasoning_sticky_phone": "session-reasoning-sticky-phone",
        "session_standalone_reasoning_open": "session-standalone-reasoning-open",
        "session_reasoning_code_fence_open": "session-reasoning-code-fence-open",
        "session_reasoning_code_fence_open_phone": "session-reasoning-code-fence-open-phone",
        "session_shell_calls": "session-shell-calls",
        "session_shell_calls_phone": "session-shell-calls-phone",
        "session_raw_phone": "session-raw-phone",
    }
    match name:
        case (
            "session_recovery_messages"
            | "session_recovery_messages_phone"
            | "session_recovery_tools"
            | "session_recovery_quiet"
            | "session_error"
            | "session_error_phone"
            | "session_interleaved"
            | "session_lifecycle_group"
            | "session_thread_setup"
            | "actions_attention_composer_desktop"
            | "actions_attention_composer_phone"
            | "session"
            | "session_deleted_sandbox"
            | "session_deleted_sandbox_phone"
            | "session_suspended_sandbox"
            | "session_suspended_sandbox_phone"
            | "session_inventory_stale"
            | "session_inventory_stale_phone"
            | "session_inventory_dropped"
            | "session_inventory_dropped_phone"
            | "session_phone"
            | "session_unnamed"
            | "session_unnamed_phone"
            | "session_unfinished_reasoning"
            | "session_unfinished_reasoning_phone"
            | "session_states"
            | "session_resume"
            | "session_pending"
            | "session_pending_phone"
            | "session_pending_failed"
            | "session_pending_controls"
            | "session_command_outcomes_phone"
            | "session_sync_reconnecting"
            | "session_sync_reconnecting_phone"
            | "session_states_phone"
            | "session_recovery_tools_open"
            | "session_recovery_tools_open_phone"
            | "session_compact_run"
            | "session_compact_run_phone"
            | "session_tool_output_sticky"
            | "session_tool_output_sticky_phone"
            | "disclosure_component_phone_collapsed"
            | "disclosure_component_phone_short_expanded"
            | "disclosure_component_phone_long_top"
            | "disclosure_component_phone_long_scrolled"
            | "disclosure_component_phone_after_disclosure"
            | "disclosure_component_phone_nested_child_scrolled"
            | "disclosure_component_phone_nested_after_child"
            | "disclosure_component_phone_nested_parent_only"
            | "disclosure_component_phone_nested_after_outer"
            | "disclosure_component_phone_nested_wrapped_headings"
            | "disclosure_component_phone_nested_expanded_output"
            | "disclosure_component_phone_nested_before_output"
            | "disclosure_component_phone_nested_after_output"
            | "disclosure_component_phone_nested_output_collapsed"
            | "session_recovery_messages_open"
            | "session_recovery_messages_open_phone"
            | "session_recovery_quiet_open"
            | "session_error_raw"
            | "session_error_raw_phone"
            | "session_interleaved_raw"
            | "session_interleaved_raw_phone"
            | "session_thread_setup_open"
            | "session_interleaved_disclosures"
            | "session_phone_drawer_over_active_thread"
            | "threads_disconnected"
            | "actions_attention_composer_long_phone"
            | "actions_attention_composer_long_desktop"
            | "actions_attention_composer_open_desktop"
            | "actions_attention_composer_open_phone"
            | "session_phone_controls"
            | "session_more_menu"
            | "session_more_menu_phone"
            | "session_shell_calls"
            | "session_shell_calls_phone"
            | "session_evidence"
            | "session_evidence_phone"
            | "session_evidence_hover_bubble"
            | "session_evidence_hover_reply"
            | "session_evidence_tap_phone"
            | "session_pending_raw"
            | "realistic_rollout_desktop"
            | "realistic_rollout_mobile"
            | "reported_rollout_desktop"
            | "realistic_rollout_desktop_dark"
        ):
            target = None
        case (
            "threads"
            | "threads_phone"
            | "threads_failed_turn"
            | "threads_provisioning"
            | "threads_updates_disconnected"
            | "threads_watch_stale"
            | "sandboxes"
            | "sandboxes_phone"
            | "sandboxes_stale"
            | "actions"
            | "actions_phone"
            | "actions_history_groups_unavailable"
            | "actions_hidden_codepoints"
            | "consent"
            | "consent_phone"
            | "sandbox"
            | "sandbox_phone"
            | "sandbox_status"
            | "sandbox_status_phone"
            | "sandbox_status_grant_error"
            | "sandbox_policy"
            | "sandbox_policy_phone"
            | "session_markdown_code_fence"
            | "session_standalone_reasoning"
            | "session_standalone_reasoning_preview"
            | "session_reasoning_code_fence"
            | "session_reasoning_code_fence_phone"
            | "session_catching_up"
            | "session_sync_unavailable"
            | "new_sandbox"
            | "new_sandbox_phone"
            | "new_sandbox_policies"
            | "new_sandbox_policies_phone"
            | "new_sandbox_grants"
            | "new_sandbox_grants_phone"
            | "sandbox_egress"
            | "sandbox_egress_phone"
            | "actions_history"
            | "actions_history_more"
            | "actions_history_phone"
            | "actions_history_raw"
            | "mcp_servers"
            | "mcp_servers_phone"
            | "consent_reconnect_phone"
            | "session_tool_payloads"
            | "session_tool_payloads_phone"
            | "session_shell_calls_open"
            | "session_shell_calls_open_phone"
            | "threads_archived"
            | "threads_phone_drawer"
            | "threads_failed_turn_phone_drawer"
            | "threads_provisioning_phone"
            | "threads_disconnected_phone"
            | "sandboxes_claude_paused"
            | "actions_raw"
            | "connections"
            | "connections_phone"
            | "consent_reconnect"
            | "sandbox_claude_paused"
            | "sandbox_status_raw"
            | "sandbox_status_raw_phone"
            | "session_reasoning"
            | "session_reasoning_phone"
            | "session_reasoning_sticky"
            | "session_reasoning_sticky_phone"
            | "session_standalone_reasoning_open"
            | "session_reasoning_code_fence_open"
            | "session_reasoning_code_fence_open_phone"
            | "session_raw"
            | "session_raw_phone"
        ):
            target = view.page.locator("#app")
        case "session_streaming_interleaved":
            target = view.page.locator(".agentplane-shell-main-content")
        case _:
            raise ValueError(f"unknown Agentplane visual capture: {name}")
    await view.capture(output_name or output_names.get(name, name), target=target)
