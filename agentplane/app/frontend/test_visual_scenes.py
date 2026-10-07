"""Agentplane render-only checkpoints; interactions live in the feature tests."""

import pytest
import pytest_bazel
from playwright.async_api import expect

from agentplane.app.frontend.visual_app import (
    DELETED_SANDBOX_THREAD,
    IDLE_THREAD,
    RUNNING_THREAD,
    SUSPENDED_THREAD,
    UNNAMED_THREAD,
    AgentplaneFixture,
)
from util.testing.viewports import DESKTOP, MOBILE, Viewport
from util.testing.visual_capture import VisualHarness

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_recovery_messages"), (MOBILE, "session_recovery_messages_phone")]
)
async def test_session_recovery_messages(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("messages")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Retention unknown"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


async def test_session_recovery_tools(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("tools")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Retention unknown"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_recovery_tools")


async def test_session_recovery_quiet(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("quiet")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="50"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_recovery_quiet")


async def test_session_error(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.failed_turn(after_content=False)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="6"]', state="attached")
        await view.page.wait_for_selector(
            '.agentplane-thread-status-indicator[data-status="turn_error"]', state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture("session_error")


async def test_session_error_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.failed_turn(after_content=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="8"]', state="attached")
        await view.page.wait_for_selector(
            '.agentplane-thread-status-indicator[data-status="turn_error"]', state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture("session_error_phone")


async def test_session_interleaved(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.interleaved_events()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="18"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_interleaved")


async def test_session_lifecycle_group(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.lifecycle_group()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="50"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_lifecycle_group")


async def test_session_thread_setup(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.thread_setup()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("Thread setup complete")', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_thread_setup")


async def test_threads(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("a.agentplane-sidebar-group-name", state="attached")
        await view.check(context="fixture ready")
        await view.capture("threads", target=view.page.locator("#app"))


async def test_threads_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture("threads-phone", target=view.page.locator("#app"))


async def test_threads_failed_turn(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.failed_turn(after_content=False)
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(
            ".agentplane-thread-status-indicator[data-status='turn_error']", state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture("threads_failed_turn", target=view.page.locator("#app"))


async def test_threads_provisioning(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.add_provisioning_sandbox()
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('a[href="#/sandboxes/test-provisioning"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("threads_provisioning", target=view.page.locator("#app"))


async def test_threads_updates_disconnected(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.disconnect_thread_database()
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[role="alert"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("threads_updates_disconnected", target=view.page.locator("#app"))


async def test_threads_watch_stale(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.stale_watch()
        await app.mount_app("/")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[role="alert"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("threads_watch_stale", target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "sandboxes"), (MOBILE, "sandboxes-phone")])
async def test_sandboxes(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/sandboxes")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_sandboxes_stale(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.stale_watch()
        await app.mount_app("/sandboxes")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture("sandboxes_stale", target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "actions_attention_composer_desktop"), (MOBILE, "actions_attention_composer_phone")],
)
async def test_actions_attention_composer_desktop(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.show_pending_actions()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('button[aria-label="Actions, 2 pending"]', state="attached")
        await view.page.wait_for_selector(".action-affordance-notice", state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "actions"), (MOBILE, "actions_phone")])
async def test_actions(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.show_pending_actions()
        await app.mount_app("/actions")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_actions_history_groups_unavailable(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.fail_action_groups()
        await app.show_pending_actions()
        await app.mount_app("/actions")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.page.wait_for_selector('[role="alert"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("actions_history_groups_unavailable", target=view.page.locator("#app"))


async def test_actions_hidden_codepoints(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.hidden_codepoints()
        await app.show_pending_actions()
        await app.mount_app("/actions")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".cm-agentplane-special-char-bidi", state="attached")
        await view.page.wait_for_selector(".cm-agentplane-special-char-ignorable", state="attached")
        await view.page.wait_for_selector(".cm-agentplane-special-char-control", state="attached")
        await view.check(context="fixture ready")
        await view.capture("actions_hidden_codepoints", target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "consent"), (MOBILE, "consent_phone")])
async def test_consent(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/connection-enrollments/test-only-opaque-handle")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "sandbox"), (MOBILE, "sandbox-phone")])
async def test_sandbox(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/sandboxes/ready-sandbox")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "sandbox-status"), (MOBILE, "sandbox-status-phone")])
async def test_sandbox_status(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/sandboxes/ready-sandbox?tab=status")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_sandbox_status_grant_error(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.fail_grant_provisioning()
        await app.mount_app("/sandboxes/ready-sandbox?tab=status")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture("sandbox-status-grant-error", target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "sandbox-policy"), (MOBILE, "sandbox-policy-phone")])
async def test_sandbox_policy(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_app("/sandboxes/ready-sandbox?tab=policy")
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "session"), (MOBILE, "session-phone")])
async def test_session(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_deleted_sandbox"), (MOBILE, "session_deleted_sandbox_phone")]
)
async def test_session_deleted_sandbox(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(DELETED_SANDBOX_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[role="status"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_suspended_sandbox"), (MOBILE, "session_suspended_sandbox_phone")]
)
async def test_session_suspended_sandbox(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(SUSPENDED_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("Last observed Sandbox and Pod")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


async def test_session_inventory_stale(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.stale_watch()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("so this page is not being updated")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_inventory_stale")


async def test_session_inventory_stale_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.stale_watch()
        await app.mount_thread(DELETED_SANDBOX_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("Current availability unknown")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_inventory_stale_phone")


async def test_session_inventory_dropped(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.disconnect_inventory_stream()
        await app.age_outage(90000)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-connection="stale"]', state="attached")
        await view.page.wait_for_selector(':text("may be out of date")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_inventory_dropped")


async def test_session_inventory_dropped_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.disconnect_inventory_stream()
        await app.age_outage(90000)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("may be out of date")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_inventory_dropped_phone")


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "session_unnamed"), (MOBILE, "session_unnamed_phone")])
async def test_session_unnamed(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(UNNAMED_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


async def test_session_markdown_code_fence(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.markdown_code_fence()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-code-block", state="attached")
        await view.check(context="fixture ready")
        await view.capture("session-markdown-code-fence", target=view.page.locator("#app"))


async def test_session_standalone_reasoning(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(
            '[data-thread-anchor="20"] .agentplane-step-preview .agentplane-markdown--single-line', state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture("session-standalone-reasoning", target=view.page.locator("#app"))


async def test_session_standalone_reasoning_preview(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning(long_preview=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(
            '[data-thread-anchor="20"] .agentplane-step-details .agentplane-disclosure-summary:not(:has(a))',
            state="attached",
        )
        await view.check(context="fixture ready")
        await view.capture("session-standalone-reasoning-preview", target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "session-unfinished-reasoning"), (MOBILE, "session-unfinished-reasoning-phone")],
)
async def test_session_unfinished_reasoning(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.unfinished_reasoning()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-step-title--streaming", state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "session-reasoning-code-fence"), (MOBILE, "session-reasoning-code-fence-phone")],
)
async def test_session_reasoning_code_fence(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning(code_fence=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(
            '[data-thread-anchor="20"] .agentplane-step-preview .agentplane-code-inline', state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_session_states(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="failed"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="noop"]', state="attached")
        await view.page.wait_for_selector(
            '.agentplane-thread-status-indicator[data-status="running"]', state="attached"
        )
        await view.check(context="fixture ready")
        await view.capture("session-states")


async def test_session_streaming_interleaved(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.streaming_interleaved()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('.agentplane-streaming-cursor[aria-label="Streaming"]', state="attached")
        await view.page.wait_for_selector('[aria-label="Thread history"][data-layout-settled="true"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session-streaming-interleaved", target=view.page.locator(".agentplane-shell-main-content"))


async def test_session_resume(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.ended_attachment()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Harness not running"]', state="attached")
        await view.page.wait_for_selector('[aria-label="Resume harness"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_resume")


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "session_pending"), (MOBILE, "session_pending_phone")])
async def test_session_pending(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.pending_commands()
        await app.remember_pending_input()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Pending commands"]', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="local"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture(image_name)


async def test_session_pending_failed(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.time_out_command_admission()
        await app.pending_commands()
        await app.remember_pending_input()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(':text("Admission unconfirmed · checking Thread history")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="local"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_pending_failed")


async def test_session_pending_controls(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.pending_commands()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-command-id="queued-interrupt"]', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_pending_controls")


async def test_session_command_outcomes_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.command_outcomes()
        await app.remember_settled_commands()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Pending commands"]', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="failed"]', state="attached")
        await view.page.wait_for_selector('.agentplane-user-bubble[data-message-phase="noop"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_command_outcomes_phone")


async def test_session_catching_up(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.withhold_entity_segments()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-catchup="true"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_catching_up", target=view.page.locator("#app"))


async def test_session_sync_unavailable(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.fail_sync_scope()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[role="alert"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_sync_unavailable", target=view.page.locator("#app"))


async def test_session_sync_reconnecting(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.disconnect_entity_stream()
        await app.age_outage(10000)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Runner feed active · harness running"]', state="attached")
        await view.page.wait_for_selector('[data-connection="degraded"]', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_sync_reconnecting")


async def test_session_sync_reconnecting_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.disconnect_entity_stream()
        await app.age_outage(90000)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[aria-label="Runner feed active · harness running"]', state="attached")
        await view.page.wait_for_selector(':text("may be out of date")', state="attached")
        await view.page.wait_for_selector('[data-thread-anchor="34"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session_sync_reconnecting_phone")


async def test_session_states_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-thread-anchor="16"]', state="attached")
        await view.check(context="fixture ready")
        await view.capture("session-states-phone")


if __name__ == "__main__":
    pytest_bazel.main()
