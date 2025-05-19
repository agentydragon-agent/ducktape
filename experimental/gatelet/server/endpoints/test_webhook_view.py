"""Tests for webhook viewing endpoints."""

import pytest
from hamcrest import (
    all_of, assert_that, contains_string, equal_to, has_entries, 
    has_property, greater_than, is_not, is_
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import WebhookIntegration, WebhookPayload
from tests.utils import persist


@pytest.mark.asyncio
async def test_list_all_payloads_key_auth(
    client: AsyncClient,
    db_session: AsyncSession,
    test_auth_key
):
    """Test listing all payloads with key path authentication."""
    # Create test integration and payloads
    integration = WebhookIntegration(
        name="test-view-integration",
        description="Test integration for viewing",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Add some test payloads
    payloads = []
    for i in range(15):
        payload = WebhookPayload(
            integration_name=integration.name,
            integration_id=integration.id,
            payload={"test": "data", "index": i, "value": i * 10}
        )
        payloads.append(await persist(db_session, payload))
    
    # Use key-in-path authentication
    response = await client.get(f"/k/{test_auth_key.key_value}/webhooks/")
    
    # Verify response status code
    assert_that(response.status_code, equal_to(200))
    
    # Verify response content
    assert_that(
        response.text,
        all_of(
            contains_string(integration.name),
            contains_string("test"),
            contains_string("data"),
            contains_string("page=1"),
            contains_string("page=2")
        )
    )


@pytest.mark.asyncio
async def test_list_integration_payloads(
    client: AsyncClient,
    db_session: AsyncSession,
    test_auth_key
):
    """Test listing integration-specific payloads."""
    # Create test integration and payloads
    integration = WebhookIntegration(
        name="test-specific-integration",
        description="Test integration for specific view",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Add some test payloads
    for i in range(5):
        payload = WebhookPayload(
            integration_name=integration.name,
            integration_id=integration.id,
            payload={"test": "specific", "index": i}
        )
        await persist(db_session, payload)
    
    # Use key-in-path authentication
    response = await client.get(f"/k/{test_auth_key.key_value}/webhooks/{integration.name}")
    
    # Verify response status code
    assert_that(response.status_code, equal_to(200))
    
    # Verify response content
    assert_that(
        response.text,
        all_of(
            contains_string(integration.name),
            contains_string("test"),
            contains_string("specific")
        )
    )


@pytest.mark.asyncio
async def test_list_nonexistent_integration(
    client: AsyncClient,
    db_session: AsyncSession,
    test_auth_key
):
    """Test listing a non-existent integration."""
    # Use key-in-path authentication
    response = await client.get(f"/k/{test_auth_key.key_value}/webhooks/nonexistent")
    assert_that(response.status_code, equal_to(404))


@pytest.mark.asyncio
async def test_session_auth_webhooks(
    client: AsyncClient,
    db_session: AsyncSession,
    test_auth_session
):
    """Test listing payloads with session authentication."""
    # Create test integration and payloads
    integration = WebhookIntegration(
        name="test-session-integration",
        description="Test integration for session auth",
        auth_type="none",
        auth_config={"type": "none"},
        is_enabled=True
    )
    integration = await persist(db_session, integration)
    
    # Add a test payload
    payload = WebhookPayload(
        integration_name=integration.name,
        integration_id=integration.id,
        payload={"test": "session", "value": 42}
    )
    await persist(db_session, payload)
    
    # Use session-based authentication
    response = await client.get(f"/s/{test_auth_session.session_token}/webhooks/")
    
    # Verify response status code
    assert_that(response.status_code, equal_to(200))
    
    # Verify response content
    assert_that(
        response.text,
        all_of(
            contains_string(integration.name),
            contains_string("test"),
            contains_string("session")
        )
    )