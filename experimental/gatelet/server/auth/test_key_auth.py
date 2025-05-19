"""Tests for key-in-path authentication."""

import pytest
from datetime import datetime, timedelta
from hamcrest import assert_that, is_

from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.key_auth import validate_key, KeyAuthError
from server.config import settings
from server.models import AuthKey
from server.tests.utils import persist


@pytest.mark.asyncio
async def test_validate_valid_key(db_session: AsyncSession):
    """Test validating a valid key."""
    # Create a valid key
    key = AuthKey(
        key_value="valid-test-key",
        description="Valid test key",
        created_at=datetime.now()
    )
    key = await persist(db_session, key)
    
    # Validate key
    validated_key = await validate_key(key.key_value, db_session)
    assert validated_key.id == key.id
    assert validated_key.key_value == key.key_value


@pytest.mark.asyncio
async def test_validate_nonexistent_key(db_session: AsyncSession):
    """Test validating a non-existent key."""
    with pytest.raises(KeyAuthError):
        await validate_key("nonexistent-key", db_session)


@pytest.mark.asyncio
async def test_validate_revoked_key(db_session: AsyncSession):
    """Test validating a revoked key."""
    # Create a revoked key
    key = AuthKey(
        key_value="revoked-test-key",
        description="Revoked test key",
        created_at=datetime.now(),
        revoked_at=datetime.now()
    )
    key = await persist(db_session, key)
    
    # Validate key
    with pytest.raises(KeyAuthError):
        await validate_key(key.key_value, db_session)


@pytest.mark.asyncio
async def test_validate_expired_key(db_session: AsyncSession):
    """Test validating an expired key."""
    # Create a key that was created beyond the validity period
    expiry_period = settings.auth.key_in_url.key_validity
    created_at = datetime.now() - expiry_period - timedelta(days=1)
    
    key = AuthKey(
        key_value="expired-test-key",
        description="Expired test key",
        created_at=created_at
    )
    key = await persist(db_session, key)
    
    # Validate key
    with pytest.raises(KeyAuthError):
        await validate_key(key.key_value, db_session)