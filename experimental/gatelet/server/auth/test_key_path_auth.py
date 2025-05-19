"""Test for key_path_auth that doesn't depend on complex fixtures."""

import asyncio
import logging
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from server.auth.handlers import key_path_auth, AuthHandlerError
from server.auth.key_auth import KeyAuthError
from server.models import Base, AuthKey

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest.fixture(scope="module")
async def engine():
    """Create database engine."""
    eng = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@db/gatelet_test",
        echo=False
    )
    yield eng
    await eng.dispose()

@pytest.fixture
async def session(engine):
    """Create database session."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session

@pytest.mark.asyncio
async def test_key_path_auth_success(session):
    """Test key_path_auth with valid key."""
    # Create a test key
    unique_id = uuid.uuid4().hex[:8]
    key_value = f"test-key-{unique_id}"
    
    key = AuthKey(
        key_value=key_value,
        description=f"Test key {unique_id}",
        created_at=datetime.now()
    )
    
    # Add and commit
    session.add(key)
    await session.commit()
    
    # Test auth
    auth_context = await key_path_auth(key_value, session)
    assert auth_context.key_value == key_value

@pytest.mark.asyncio
async def test_key_path_auth_invalid(session):
    """Test key_path_auth with invalid key."""
    # Use a key that doesn't exist
    with pytest.raises(AuthHandlerError):
        await key_path_auth("nonexistent-key", session)