"""Global pytest configuration and fixtures for Gatelet tests."""

import os
from importlib import reload
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import server.config
from server.database import get_db_session
from server.models import Base


@pytest.fixture(scope="session", autouse=True)
def setup_test_config():
    """Setup test configuration."""
    os.environ["GATELET_CONFIG"] = str(Path(__file__).parent.parent.parent / "tests" / "gatelet_test.toml")
    
    # Re-import config to ensure we're using the test config
    reload(server.config)
    
    # Return the reloaded settings
    return server.config.settings


@pytest_asyncio.fixture(scope="session")
async def db_engine(setup_test_config) -> AsyncEngine:
    """Create database engine for tests."""
    engine = create_async_engine(
        str(setup_test_config.database.dsn),
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Clean up - drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    # Close engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Create database session for test."""
    async_session_maker = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(setup_test_config, db_engine) -> AsyncClient:
    """Get test client with app using test database."""
    # Import app after config is set to test config
    from server.app import app
    
    # Override the dependency to use the test database session
    async def override_get_db_session():
        """Get a test database session."""
        async with db_engine.begin() as conn:
            async_session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield async_session
                await async_session.commit()
            except Exception:
                await async_session.rollback()
                raise
    
    # Override the get_db_session dependency
    app.dependency_overrides[get_db_session] = override_get_db_session
    
    # Start the test client
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client