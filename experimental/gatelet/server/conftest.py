"""Global pytest configuration and fixtures for Gatelet tests."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from server.app import app
from server.database import get_db_session
from server.models import (
    AuthCRSession,
    AuthKey,
)
from server.tests.utils import persist

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@pytest_asyncio.fixture
async def test_auth_key(db_session):
    """Create a test authentication key with a unique value."""

    # Use a unique ID to avoid collisions
    unique_id = uuid4().hex[:8]
    key = AuthKey(
        key_value=f"test-key-{unique_id}",
        description=f"Test auth key {unique_id}",
        created_at=datetime.now()
    )
    return await persist(db_session, key)


@pytest_asyncio.fixture
async def test_auth_session(db_session, test_auth_key):
    """Create a test authentication session with a unique token."""

    # Create a session with a unique token
    unique_id = uuid4().hex[:8]
    session = AuthCRSession(
        session_token=f"test-session-{unique_id}",
        auth_key_id=test_auth_key.id,
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
        last_activity_at=datetime.now()
    )
    return await persist(db_session, session)


@pytest_asyncio.fixture
async def client(db_session) -> AsyncClient:
    """Get a test client connected to the test database."""
    # Import app here to ensure test config is loaded first
    try:
        # Create a client with the FastAPI app
        async with AsyncClient(app=app) as client:
            yield client
    finaly:
        # Clean up the override after the test
        app.dependency_overrides.pop(get_db_session)
