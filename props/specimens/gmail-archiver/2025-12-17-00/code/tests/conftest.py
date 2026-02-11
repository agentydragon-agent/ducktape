"""Shared test fixtures."""

from gmail_archiver.models import GmailMessage
import pytest


@pytest.fixture
def make_email():
    def _make_email(
        *,
        id: str = "test-msg-id",
        thread_id: str | None = None,
        sender: str = "test@example.com",
        recipient: str | None = None,
        subject: str = "Test Subject",
        date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
        internal_date: int = 1704110400000,  # 2024-01-01 12:00:00 UTC
        body: str = "",
        snippet: str | None = None,
        label_ids: list[str] | None = None,
    ) -> GmailMessage:
        return GmailMessage(
            id=id,
            thread_id=thread_id,
            sender=sender,
            recipient=recipient,
            subject=subject,
            date=date,
            internal_date=internal_date,
            body=body,
            snippet=snippet,
            label_ids=label_ids or [],
        )

    return _make_email
