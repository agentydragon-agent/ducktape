"""Authentication handlers for Gatelet endpoints."""

from datetime import datetime
from typing import Callable, Protocol
from urllib.parse import urlencode

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..models import AuthCRSession, AuthKey
from .key_auth import KeyAuthError, validate_key


class AuthHandlerError(Exception):
    """Common exception for all authentication errors."""

    pass


class AuthContext(Protocol):
    """Authentication context with information for navigation."""

    @property
    def auth_type(self) -> str:
        """Authentication method type."""
        ...

    def create_url(self, path: str) -> str:
        """Create authenticated URL for a given path.

        Args:
            path: Path to authenticate (should not start with /)

        Returns:
            URL with authentication component
        """
        ...

    def create_url_with_params(self, path: str, **query_params) -> str:
        """Create authenticated URL with query parameters.

        Args:
            path: Path to authenticate (should not start with /)
            **query_params: Query parameters as keyword arguments

        Returns:
            URL with authentication component and query parameters
        """
        base_url = self.create_url(path)
        if not query_params:
            return base_url

        return f"{base_url}?{urlencode(query_params)}"


class KeyPathAuthContext:
    """Authentication context for key-in-path."""

    def __init__(self, auth_key: AuthKey):
        self.key = auth_key

    @property
    def auth_type(self) -> str:
        return "key_path"

    @property
    def key_value(self) -> str:
        """Get the authentication key value."""
        return self.key.key_value

    def create_url(self, path: str) -> str:
        return f"/k/{self.key_value}/{path}"
        
    def create_url_with_params(self, path: str, **query_params) -> str:
        """Create authenticated URL with query parameters."""
        base_url = self.create_url(path)
        if not query_params:
            return base_url

        return f"{base_url}?{urlencode(query_params)}"


class SessionAuthContext:
    """Authentication context for session-based auth."""

    def __init__(self, session: AuthCRSession):
        self.session = session

    @property
    def auth_type(self) -> str:
        return "session"

    @property
    def session_token(self) -> str:
        """Get the session token."""
        return self.session.session_token

    def create_url(self, path: str) -> str:
        return f"/s/{self.session_token}/{path}"
        
    def create_url_with_params(self, path: str, **query_params) -> str:
        """Create authenticated URL with query parameters."""
        base_url = self.create_url(path)
        if not query_params:
            return base_url

        return f"{base_url}?{urlencode(query_params)}"


async def key_path_auth(
    key: str, db_session: AsyncSession = Depends(get_db_session)
) -> KeyPathAuthContext:
    """Authenticate using key in path."""
    try:
        return KeyPathAuthContext(await validate_key(key, db_session))
    except KeyAuthError:
        raise AuthHandlerError()


async def session_auth(
    session_token: str, db_session: AsyncSession = Depends(get_db_session)
) -> SessionAuthContext:
    """Authenticate using challenge-response session token."""
    # Find session
    query = select(AuthCRSession).where(AuthCRSession.session_token == session_token)
    session = (await db_session.execute(query)).scalar_one_or_none()

    if not session or not session.is_valid:
        raise AuthHandlerError()

    # Extend session if needed
    session.last_activity_at = datetime.now()
    
    # Only commit if session is managed - prevents errors in tests
    if db_session.in_transaction():
        await db_session.commit()
    # Create SessionAuthContext with the updated session
    return SessionAuthContext(session)


def create_auth_dependency(auth_type: str) -> Callable:
    """Create an authentication dependency based on auth type."""
    if auth_type == "key_path":
        return key_path_auth
    elif auth_type == "session":
        return session_auth
    else:
        raise ValueError(f"Unsupported {auth_type = }")
