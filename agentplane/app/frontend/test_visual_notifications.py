"""Notification diagnostics seen from a Thread and the owning Sandbox."""

import pytest
import pytest_bazel
from playwright.async_api import expect

from agentplane.app.frontend.visual_app import IDLE_THREAD, AgentplaneFixture
from util.testing.visual_capture import VisualPage

pytest_plugins = ("util.testing.visual_fixtures", "agentplane.app.frontend.visual_fixtures")
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_thread_notifications(view: VisualPage, app: AgentplaneFixture) -> None:
    await app.mount_thread(IDLE_THREAD)
    page = view.page
    await page.get_by_role("button", name="Notifications").click()
    await expect(page.get_by_text("2 awaiting notice")).to_be_visible()
    await expect(page.get_by_text("runner admitted; awaiting confirmation", exact=False)).to_be_visible()
    await expect(page.get_by_text("Session s-2")).to_have_count(0)
    await view.capture()


async def test_sandbox_notifications(view: VisualPage, app: AgentplaneFixture) -> None:
    await app.mount_app("/sandboxes/ready-sandbox")
    page = view.page
    await page.get_by_role("button", name="Notifications").click()
    await expect(page.get_by_text("Session s-2")).to_be_visible()
    await expect(page.get_by_text("Session s-3")).to_be_visible()
    await expect(page.get_by_text("runner unavailable", exact=False)).to_be_visible()
    await expect(page.get_by_text("debouncing", exact=False)).to_be_visible()
    await view.capture()


async def test_empty_notifications(view: VisualPage, app: AgentplaneFixture) -> None:
    await app.mount_app("/sandboxes/suspended-sandbox")
    page = view.page
    await page.get_by_role("button", name="Notifications").click()
    await expect(page.get_by_text("No inbox for this Sandbox incarnation.")).to_be_visible()
    await view.capture()


async def test_notification_service_reconnect(view: VisualPage, app: AgentplaneFixture) -> None:
    await app.set_notification_status_unavailable(True)
    await app.mount_thread(IDLE_THREAD)
    page = view.page
    await page.get_by_role("button", name="Notifications").click()
    await expect(page.get_by_role("alert")).to_contain_text("Notification service unavailable")
    await view.capture(name="notification_status_unavailable")
    await app.set_notification_status_unavailable(False)
    await page.keyboard.press("Escape")
    await expect(page.get_by_text("Loading notification status…")).to_have_count(0)
    await page.get_by_role("button", name="Notifications").click()
    await expect(page.get_by_text("2 awaiting notice")).to_be_visible()
    await view.capture(name="notification_status_reconnected")


if __name__ == "__main__":
    pytest_bazel.main()
