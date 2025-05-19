"""Tests for authentication handlers."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.handlers import (
    AuthHandlerError,
    KeyPathAuthContext,
    SessionAuthContext,
    key_path_auth,
    session_auth
)
from server.models import AuthCRSession, AuthKey
from tests.utils import persist


@pytest.mark.asyncio
async def test_key_path_auth_context():
    """Test KeyPathAuthContext functions."""
    key = AuthKey(key_value="test-key", description="Test key")
    auth_context = KeyPathAuthContext(key)
    
    assert auth_context.auth_type == "key_path"
    assert auth_context.key_value == "test-key"
    assert auth_context.create_url("test/path") == "/k/test-key/test/path"
    assert auth_context.create_url_with_params("test/path", a=1, b="test") in [
        "/k/test-key/test/path?a=1&b=test",
        "/k/test-key/test/path?b=test&a=1"
    ]


@pytest.mark.asyncio
async def test_session_auth_context():
    """Test SessionAuthContext functions."""
    session = AuthCRSession(session_token="test-token")
    auth_context = SessionAuthContext(session)
    
    assert auth_context.auth_type == "session"
    assert auth_context.session_token == "test-token"
    assert auth_context.create_url("test/path") == "/s/test-token/test/path"
    assert auth_context.create_url_with_params("test/path", a=1, b="test") in [
        "/s/test-token/test/path?a=1&b=test",
        "/s/test-token/test/path?b=test&a=1"
    ]


@pytest.mark.asyncio
async def test_key_path_auth_valid(db_session: AsyncSession):
    """Test key_path_auth with valid key."""
    key = AuthKey(
        key_value="valid-test-key",
        description="Valid test key",
        created_at=datetime.now()
    )
    key = await persist(db_session, key)
    
    # Test with valid key
    auth_context = await key_path_auth(key.key_value, db_session)
    assert isinstance(auth_context, KeyPathAuthContext)
    assert auth_context.key_value == key.key_value


@pytest.mark.asyncio
async def test_key_path_auth_invalid(db_session: AsyncSession):
    """Test key_path_auth with invalid key."""
    # Test with invalid key
    with pytest.raises(AuthHandlerError):
        await key_path_auth("invalid-key", db_session)


@pytest.mark.asyncio
async def test_session_auth_valid(db_session: AsyncSession):
    """Test session_auth with valid session."""
    key = AuthKey(
        key_value="valid-test-key",
        description="Valid test key",
        created_at=datetime.now()
    )
    key = await persist(db_session, key)
    
    session = AuthCRSession(
        session_token="valid-test-session",
        auth_key_id=key.id,
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
        last_activity_at=datetime.now()
    )
    session = await persist(db_session, session)
    
    # Test with valid session
    auth_context = await session_auth(session.session_token, db_session)
    assert isinstance(auth_context, SessionAuthContext)
    assert auth_context.session_token == session.session_token
    
    # Verify last_activity_at was updated
    assert session.last_activity_at > session.created_at


@pytest.mark.asyncio
async def test_session_auth_invalid(db_session: AsyncSession):
    """Test session_auth with invalid session."""
    # Test with invalid session token
    with pytest.raises(AuthHandlerError):
        await session_auth("invalid-session", db_session)


@pytest.mark.asyncio
async def test_session_auth_expired(db_session: AsyncSession):
    """Test session_auth with expired session."""
    key = AuthKey(
        key_value="test-key",
        description="Test key",
        created_at=datetime.now()
    )
    key = await persist(db_session, key)
    
    # Create expired session
    session = AuthCRSession(
        session_token="expired-test-session",
        auth_key_id=key.id,
        created_at=datetime.now() - timedelta(hours=2),
        expires_at=datetime.now() - timedelta(hours=1),
        last_activity_at=datetime.now() - timedelta(hours=2)
    )
    session = await persist(db_session, session)
    
    # Test with expired session
    with pytest.raises(AuthHandlerError):
        await session_auth(session.session_token, db_session)