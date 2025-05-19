"""Auth fixtures for Gatelet tests."""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.handlers import KeyPathAuthContext, SessionAuthContext
from server.models import AuthCRSession, AuthKey
from tests.utils import persist


@pytest_asyncio.fixture
async def test_auth_key(db_session: AsyncSession) -> AuthKey:
    """Create a test auth key."""
    key = AuthKey(
        key_value=f"test-key-{uuid.uuid4()}",
        description="Test key",
        created_at=datetime.now()
    )
    return await persist(db_session, key)


@pytest_asyncio.fixture
async def test_auth_session(db_session: AsyncSession, test_auth_key: AuthKey) -> AuthCRSession:
    """Create a test auth session."""
    expires_at = datetime.now() + timedelta(hours=1)
    session = AuthCRSession(
        session_token=f"test-session-{uuid.uuid4()}",
        auth_key_id=test_auth_key.id,
        created_at=datetime.now(),
        expires_at=expires_at,
        last_activity_at=datetime.now()
    )
    return await persist(db_session, session)


@pytest_asyncio.fixture
async def key_path_auth_context(test_auth_key: AuthKey) -> KeyPathAuthContext:
    """Create a KeyPathAuthContext for testing."""
    return KeyPathAuthContext(test_auth_key)


@pytest_asyncio.fixture
async def session_auth_context(test_auth_session: AuthCRSession) -> SessionAuthContext:
    """Create a SessionAuthContext for testing."""
    return SessionAuthContext(test_auth_session)