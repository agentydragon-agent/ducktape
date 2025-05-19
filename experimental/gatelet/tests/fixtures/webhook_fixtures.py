"""Webhook fixtures for Gatelet tests."""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import WebhookIntegration, WebhookPayload
from tests.utils import persist


@pytest_asyncio.fixture
async def test_integration(db_session: AsyncSession) -> WebhookIntegration:
    """Create a test webhook integration."""
    integration = WebhookIntegration(
        name=f"test-integration-{uuid.uuid4().hex[:8]}",
        description="Test integration",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    return await persist(db_session, integration)


@pytest_asyncio.fixture
async def test_integration_bearer(db_session: AsyncSession) -> WebhookIntegration:
    """Create a test webhook integration with bearer auth."""
    integration = WebhookIntegration(
        name=f"test-bearer-{uuid.uuid4().hex[:8]}",
        description="Test integration with bearer auth",
        auth_type="bearer",
        auth_config={"type": "bearer", "token": "test-token"},
        is_enabled=True
    )
    return await persist(db_session, integration)


@pytest_asyncio.fixture
async def test_webhook_payload(
    db_session: AsyncSession, test_integration: WebhookIntegration
) -> WebhookPayload:
    """Create a test webhook payload."""
    payload = WebhookPayload(
        integration_name=test_integration.name,
        integration_id=test_integration.id,
        received_at=datetime.now(),
        payload={"test": "data", "value": 123}
    )
    return await persist(db_session, payload)


@pytest_asyncio.fixture
async def multiple_webhook_payloads(
    db_session: AsyncSession, test_integration: WebhookIntegration
) -> list[WebhookPayload]:
    """Create multiple test webhook payloads."""
    payloads = []
    for i in range(15):
        payload = WebhookPayload(
            integration_name=test_integration.name,
            integration_id=test_integration.id,
            received_at=datetime.now(),
            payload={"test": "data", "index": i, "value": i * 10}
        )
        payloads.append(await persist(db_session, payload))
    
    return payloads