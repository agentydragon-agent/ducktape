"""Authentication dependencies for FastAPI routes."""

from typing import Annotated, Optional

from fastapi import Depends, Request

from .handlers import AuthContext, key_path_auth, session_auth


class AuthDependency:
    """Dependency provider for authentication context."""
    
    def __init__(self, initial_context: Optional[AuthContext] = None):
        """Initialize with optional context."""
        self.context: Optional[AuthContext] = initial_context
    
    def set_context(self, context: AuthContext) -> None:
        """Set the auth context."""
        self.context = context
    
    async def __call__(self, request: Request) -> AuthContext:
        """Provide the auth context when used as a dependency."""
        if self.context is None:
            raise RuntimeError("Auth context not initialized")
        return self.context


# Singleton instance of the auth dependency
auth_dependency = AuthDependency()

# Type for using auth in routes
Auth = Annotated[AuthContext, Depends(auth_dependency)]


async def get_key_path_auth_with_context(
    key: str,
    request: Request,
):
    """Get key path auth context and save it in the dependency provider."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from ..database import get_db_session

    db_session = get_db_session()
    async with db_session as session:
        auth_context = await key_path_auth(key, session)
        auth_dependency.context = auth_context
        return auth_context


async def get_session_auth_with_context(
    session_token: str,
    request: Request,
):
    """Get session auth context and save it in the dependency provider."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from ..database import get_db_session
    
    db_session = get_db_session()
    async with db_session as session:
        auth_context = await session_auth(session_token, session)
        auth_dependency.context = auth_context
        return auth_context