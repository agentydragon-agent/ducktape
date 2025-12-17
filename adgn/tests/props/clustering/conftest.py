"""Fixtures for clustering tests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from adgn.props.clustering.user_manager import ClusteringUserManager
from adgn.props.db.config import DatabaseConfig


@pytest.fixture
def clustering_user_engine_factory(test_db: DatabaseConfig) -> Callable[[int], AbstractAsyncContextManager[Engine]]:
    """Factory for creating clustering user engines.

    Returns:
        Factory function that takes a run_id and returns an async context manager yielding Engine
    """

    @asynccontextmanager
    async def _create_engine(run_id: int):
        """Create temp user engine for a clustering run."""
        async with ClusteringUserManager(test_db.admin, run_id) as creds:
            user_config = test_db.admin.with_user(creds)
            engine = create_engine(user_config.url())
            try:
                yield engine
            finally:
                engine.dispose()

    return _create_engine
