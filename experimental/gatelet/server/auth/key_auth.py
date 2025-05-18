"""Key-in-path authentication for Gatelet."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import AuthKey


class KeyAuthError(Exception):
    """Authentication error for key-in-path."""
    pass


async def validate_key(key: str, db_session: AsyncSession) -> AuthKey:
    """Validate a key from the URL path.
    
    Args:
        key: The key to validate
        db_session: Database session
        
    Returns:
        AuthKey if valid
        
    Raises:
        KeyAuthError: If key is invalid for any reason
    """
    query = select(AuthKey).where(AuthKey.key_value == key)
    result = await db_session.execute(query)
    auth_key = result.scalar_one_or_none()
    
    if not auth_key:
        raise KeyAuthError()
    
    if auth_key.revoked_at is not None:
        raise KeyAuthError()
        
    # Use the timedelta from config settings
    validity_period = settings.auth.key_in_url.key_validity
    
    if not auth_key.is_valid(validity_period):
        raise KeyAuthError()
    
    return auth_key