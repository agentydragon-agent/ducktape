"""Test utilities for Gatelet tests."""

from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def persist(db_session: AsyncSession, obj: T) -> T:
    """Persist a model instance and refresh it."""
    db_session.add(obj)
    await db_session.commit()
    await db_session.refresh(obj)
    return obj

