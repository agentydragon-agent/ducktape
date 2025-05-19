"""Tests for webhook receiving endpoint."""

import json

import pytest
from hamcrest import assert_that, equal_to, has_entries, is_, not_none, none
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import WebhookIntegration, WebhookPayload
from tests.utils import persist


@pytest.mark.asyncio
async def test_receive_webhook_no_auth(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook with no authentication."""
    # Create test integration with no auth
    integration = WebhookIntegration(
        name="test-integration",
        description="Test integration",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Send webhook payload
    payload = {"test": "data", "value": 42}
    response = await client.post(f"/webhook/{integration.name}", json=payload)
    assert_that(response.status_code, equal_to(200))
    
    # Check response
    data = response.json()
    assert_that(data, has_entries({"status": "ok"}))
    assert_that(data.get("payload_id"), not_none())
    
    # Verify payload was stored in database
    query = select(WebhookPayload).where(WebhookPayload.id == data["payload_id"])
    result = await db_session.execute(query)
    webhook_payload = result.scalar_one()
    
    assert_that(webhook_payload.integration_name, equal_to(integration.name))
    assert_that(webhook_payload.payload, equal_to(payload))


@pytest.mark.asyncio
async def test_receive_webhook_bearer_auth(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook with bearer authentication."""
    # Create test integration with bearer auth
    integration = WebhookIntegration(
        name="test-bearer",
        description="Test integration with bearer auth",
        auth_type="bearer",
        auth_config={"type": "bearer", "token": "test-token"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Send webhook payload with correct token
    payload = {"test": "data", "auth": "bearer"}
    headers = {"Authorization": "Bearer test-token"}
    response = await client.post(
        f"/webhook/{integration.name}", 
        json=payload, 
        headers=headers
    )
    assert_that(response.status_code, equal_to(200))
    
    # Check response
    data = response.json()
    assert_that(data, has_entries({"status": "ok"}))
    assert_that(data.get("payload_id"), not_none())
    
    # Verify payload was stored in database
    query = select(WebhookPayload).where(WebhookPayload.id == data["payload_id"])
    result = await db_session.execute(query)
    webhook_payload = result.scalar_one()
    
    assert_that(webhook_payload.integration_name, equal_to(integration.name))
    assert_that(webhook_payload.payload, equal_to(payload))


@pytest.mark.asyncio
async def test_receive_webhook_invalid_auth(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook with invalid bearer authentication."""
    # Create test integration with bearer auth
    integration = WebhookIntegration(
        name="test-bearer-invalid",
        description="Test integration with bearer auth",
        auth_type="bearer",
        auth_config={"type": "bearer", "token": "test-token"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Send webhook payload with incorrect token
    payload = {"test": "data", "auth": "invalid"}
    headers = {"Authorization": "Bearer wrong-token"}
    response = await client.post(
        f"/webhook/{integration.name}", 
        json=payload, 
        headers=headers
    )
    assert_that(response.status_code, equal_to(401))
    
    # No payload should be stored
    query = select(WebhookPayload).where(
        WebhookPayload.integration_id == integration.id
    )
    result = await db_session.execute(query)
    assert_that(result.scalar_one_or_none(), is_(none()))


@pytest.mark.asyncio
async def test_receive_webhook_nonexistent_integration(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook for non-existent integration."""
    payload = {"test": "data"}
    response = await client.post("/webhook/nonexistent", json=payload)
    assert_that(response.status_code, equal_to(404))


@pytest.mark.asyncio
async def test_receive_webhook_disabled_integration(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook for disabled integration."""
    # Create disabled integration
    integration = WebhookIntegration(
        name="test-disabled",
        description="Disabled test integration",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=False
    )
    integration = await persist(db_session, integration)
    
    payload = {"test": "data"}
    response = await client.post(f"/webhook/{integration.name}", json=payload)
    assert_that(response.status_code, equal_to(403))


@pytest.mark.asyncio
async def test_receive_webhook_invalid_json(
    client: AsyncClient,
    db_session: AsyncSession
):
    """Test receiving webhook with invalid JSON."""
    # Create test integration
    integration = WebhookIntegration(
        name="test-invalid-json",
        description="Test integration",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Send invalid JSON payload
    response = await client.post(
        f"/webhook/{integration.name}", 
        content="not-json",
        headers={"Content-Type": "application/json"}
    )
    assert_that(response.status_code, equal_to(400))