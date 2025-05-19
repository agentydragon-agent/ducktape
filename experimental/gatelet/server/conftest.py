"""Global pytest configuration and fixtures for Gatelet tests."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from importlib import reload
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import server.config
from server.database import get_db_session
from server.models import Base, WebhookIntegration, WebhookPayload, AuthKey, AuthCRSession, AuthNonce

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_config():
    """Setup test configuration."""
    # Set the environment variable to point to the test config
    test_config_path = str(Path(__file__).parent / "tests" / "gatelet_test.toml")
    os.environ["GATELET_CONFIG"] = test_config_path
    
    # Re-import config to ensure we're using the test config
    reload(server.config)
    
    # Return the reloaded settings
    return server.config.settings


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for all tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.mark.timeout(30)  # Allow up to 30 seconds for the database engine setup
@pytest_asyncio.fixture(scope="session")
async def db_engine(setup_test_config) -> AsyncEngine:
    """Create database engine for tests."""
    # Create a simpler engine configuration that we know works
    logging.info("Creating database engine for tests")
    engine = create_async_engine(
        str(setup_test_config.database.dsn),
        echo=True,  # Enable SQL echo for debugging
        future=True,
        poolclass=NullPool,  # Don't pool connections for tests
    )
    
    try:
        # Test the connection first
        logging.info("Testing database connection")
        async with engine.connect() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            value = result.scalar_one()
            logging.info(f"Connection test result: {value}")
        
        # Drop all tables first to ensure clean state
        logging.info("Dropping all tables")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        # Create all tables
        logging.info("Creating all tables")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logging.info("Database setup complete")
        yield engine
    except Exception as e:
        logging.error(f"Database connection error: {e}")
        raise
    finally:
        # Clean up - drop all tables after all tests complete
        try:
            logging.info("Cleaning up database")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            
            # Dispose engine
            await engine.dispose()
            logging.info("Database cleanup complete")
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
            # Don't re-raise here to prevent obscuring original errors


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Create an isolated database session for each test."""
    # Create session
    session = AsyncSession(
        bind=db_engine,
        expire_on_commit=False,
        autoflush=False
    )
    
    # Start a transaction
    async with session.begin():
        # All operations within this block will be rolled back
        # when the test is done, providing isolation between tests
        yield session
    
    # Session is closed automatically when the context manager exits
    # All changes are rolled back


@pytest_asyncio.fixture
async def test_auth_key(db_session):
    """Create a test authentication key with a unique value."""
    from datetime import datetime
    from uuid import uuid4
    from server.tests.utils import persist
    
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
    from datetime import datetime, timedelta
    from uuid import uuid4
    from server.tests.utils import persist
    
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
    from server.app import app
    
    # Define the dependency override
    @asynccontextmanager
    async def override_get_db_session():
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise
    
    # Override the dependency
    app.dependency_overrides[get_db_session] = override_get_db_session
    
    try:
        # Create a client with the FastAPI app
        # IMPORTANT: Use "http://test" as base_url - this works correctly with FastAPI ASGI
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client
    finally:
        # Clean up the override after the test
        app.dependency_overrides.pop(get_db_session)