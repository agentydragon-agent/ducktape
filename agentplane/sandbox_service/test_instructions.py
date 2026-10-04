"""Operational prompt construction without the integration app or its database."""

import pytest
import pytest_bazel

from agentplane.sandbox_service.instructions import (
    combine_instructions,
    render_agent_instructions_template,
    resolved_agent_instructions,
)


def test_explicitly_rendered_agent_instructions_include_deployment_service_urls() -> None:
    instructions = render_agent_instructions_template(
        egress_api_url="http://egress.test.invalid", actions_service_url="http://actions.test.invalid:8080"
    )

    assert "http://egress.test.invalid/v1/rules" in instructions
    assert "http://egress.test.invalid/openapi.json" in instructions
    assert "http://actions.test.invalid:8080/openapi.json" in instructions
    assert "### Waiting efficiently for Actions" not in instructions


@pytest.mark.parametrize("custom", [False, True])
def test_notification_workflow_and_examples_augment_configured_prompt(custom: bool) -> None:
    configured = (
        "Custom deployment instructions"
        if custom
        else render_agent_instructions_template(
            egress_api_url="http://egress.test.invalid", actions_service_url="http://actions.test.invalid:8080"
        )
    )
    instructions = resolved_agent_instructions(
        configured, notifications_service_url="http://notifications.test.invalid:8080"
    )

    assert instructions.count("### Waiting efficiently for Actions") == 1
    assert instructions.index("Choose how to wait:") < instructions.index("### Subscribe")
    assert "You may subscribe immediately; you do not need to time out first." in instructions
    assert "end your turn rather than occupying it with" in instructions
    assert "http://notifications.test.invalid:8080/v1/subscriptions" in instructions
    assert "http://notifications.test.invalid:8080/v1/inboxes/INBOX_ID/acknowledgement" in instructions
    assert '"idempotency_key": "follow-REAL_REQUEST_ID"' in instructions
    assert '"client_key"' not in instructions
    assert '"source": {"provider": "actions", "request_id": "REAL_REQUEST_ID", "after_sequence": 0}' in instructions
    assert "event.request_id and event.sequence" in instructions
    assert '"through_cursor": LAST_HANDLED_CURSOR' in instructions
    assert "Reads and runner delivery receipts never acknowledge." in instructions
    assert "unsubscribing is not withdrawal." in instructions
    assert "No notification-triggered harness/sandbox startup or wake-up is available." in instructions
    assert "configured local timezone (from the `TZ` environment variable)" in instructions
    assert instructions.startswith(configured)
    if not custom:
        assert "http://actions.test.invalid:8080/openapi.json" in instructions


def test_agent_instructions_must_be_configured() -> None:
    with pytest.raises(ValueError, match="must be configured"):
        resolved_agent_instructions("")


def test_task_instructions_augment_platform_guidance() -> None:
    assert combine_instructions("  Platform  ", "  Task  ") == "Platform\n\nTask"
    assert combine_instructions("", "Task") == "Task"
    assert combine_instructions("Platform", "") == "Platform"


if __name__ == "__main__":
    pytest_bazel.main()
