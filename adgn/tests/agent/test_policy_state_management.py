"""Tests for policy state management (persistence, validation, reload)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adgn.agent.persist.sqlite import SQLitePersistence


@pytest.fixture
async def persistence(tmp_path: Path):
    """Create a temporary SQLite persistence instance."""
    db_path = tmp_path / "test.db"
    p = SQLitePersistence(db_path)
    await p.ensure_schema()
    return p


@pytest.mark.asyncio
async def test_create_policy(persistence: SQLitePersistence):
    """Test creating a new policy."""
    policy = await persistence.create_policy(
        policy_id="test-policy",
        text="print('hello')",
        description="Test policy",
        enabled=True,
    )

    assert policy.id == "test-policy"
    assert policy.text == "print('hello')"
    assert policy.description == "Test policy"
    assert policy.enabled is True
    assert isinstance(policy.created_at, datetime)
    assert isinstance(policy.updated_at, datetime)


@pytest.mark.asyncio
async def test_get_policy(persistence: SQLitePersistence):
    """Test retrieving a policy by ID."""
    # Create a policy
    await persistence.create_policy(
        policy_id="test-policy",
        text="print('hello')",
        description="Test policy",
    )

    # Retrieve it
    policy = await persistence.get_policy("test-policy")
    assert policy is not None
    assert policy.id == "test-policy"
    assert policy.text == "print('hello')"
    assert policy.description == "Test policy"

    # Non-existent policy
    missing = await persistence.get_policy("nonexistent")
    assert missing is None


@pytest.mark.asyncio
async def test_update_policy(persistence: SQLitePersistence):
    """Test updating a policy (with history tracking)."""
    # Create initial policy
    policy = await persistence.create_policy(
        policy_id="test-policy",
        text="version 1",
        description="Initial version",
    )

    # Update it
    await asyncio.sleep(0.01)  # Ensure timestamp difference
    updated = await persistence.update_policy(
        "test-policy",
        text="version 2",
        description="Updated version",
    )

    assert updated.id == "test-policy"
    assert updated.text == "version 2"
    assert updated.description == "Updated version"
    assert updated.updated_at > policy.updated_at


@pytest.mark.asyncio
async def test_update_nonexistent_policy_raises(persistence: SQLitePersistence):
    """Test that updating a non-existent policy raises KeyError."""
    with pytest.raises(KeyError, match="Policy not found"):
        await persistence.update_policy("nonexistent", text="new text")


@pytest.mark.asyncio
async def test_list_policies(persistence: SQLitePersistence):
    """Test listing policies with pagination."""
    # Create multiple policies
    for i in range(5):
        await persistence.create_policy(
            policy_id=f"policy-{i}",
            text=f"print({i})",
            description=f"Policy {i}",
        )
        await asyncio.sleep(0.01)  # Ensure ordering

    # List all
    all_policies = await persistence.list_policies()
    assert len(all_policies) == 5

    # List with pagination
    page1 = await persistence.list_policies(offset=0, limit=2)
    assert len(page1) == 2

    page2 = await persistence.list_policies(offset=2, limit=2)
    assert len(page2) == 2

    # Policies should be ordered by updated_at DESC (newest first)
    assert page1[0].id == "policy-4"
    assert page1[1].id == "policy-3"


@pytest.mark.asyncio
async def test_delete_policy(persistence: SQLitePersistence):
    """Test deleting a policy."""
    # Create policy
    await persistence.create_policy(
        policy_id="test-policy",
        text="print('hello')",
    )

    # Verify it exists
    policy = await persistence.get_policy("test-policy")
    assert policy is not None

    # Delete it
    await persistence.delete_policy("test-policy")

    # Verify it's gone
    deleted = await persistence.get_policy("test-policy")
    assert deleted is None


@pytest.mark.asyncio
async def test_policy_history_tracking(persistence: SQLitePersistence):
    """Test that policy history is tracked on updates."""
    # Create policy
    await persistence.create_policy(
        policy_id="test-policy",
        text="version 1",
    )

    # Update it multiple times
    await persistence.update_policy("test-policy", text="version 2")
    await asyncio.sleep(0.01)
    await persistence.update_policy("test-policy", text="version 3")

    # Check that we have history entries (implementation detail: query DB directly)
    # The history table should contain entries for the old versions
    async with persistence._db_connection() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM policy_history WHERE policy_id = ?",
            ("test-policy",),
        ) as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0

    # Should have 3 entries: initial version + 2 updates
    assert count == 3


@pytest.mark.asyncio
async def test_policy_enabled_flag(persistence: SQLitePersistence):
    """Test that enabled flag works correctly."""
    # Create enabled policy
    enabled = await persistence.create_policy(
        policy_id="enabled-policy",
        text="print('enabled')",
        enabled=True,
    )
    assert enabled.enabled is True

    # Create disabled policy
    disabled = await persistence.create_policy(
        policy_id="disabled-policy",
        text="print('disabled')",
        enabled=False,
    )
    assert disabled.enabled is False

    # Verify retrieval preserves enabled state
    retrieved_enabled = await persistence.get_policy("enabled-policy")
    assert retrieved_enabled is not None
    assert retrieved_enabled.enabled is True

    retrieved_disabled = await persistence.get_policy("disabled-policy")
    assert retrieved_disabled is not None
    assert retrieved_disabled.enabled is False


@pytest.mark.asyncio
async def test_policy_description_optional(persistence: SQLitePersistence):
    """Test that description is optional."""
    # Create without description
    policy = await persistence.create_policy(
        policy_id="no-desc",
        text="print('hello')",
    )
    assert policy.description is None

    # Retrieve and verify
    retrieved = await persistence.get_policy("no-desc")
    assert retrieved is not None
    assert retrieved.description is None


@pytest.mark.asyncio
async def test_concurrent_policy_updates(persistence: SQLitePersistence):
    """Test that concurrent updates are handled correctly."""
    # Create policy
    await persistence.create_policy(
        policy_id="concurrent-test",
        text="initial",
    )

    # Perform concurrent updates
    async def update_policy(i: int):
        await persistence.update_policy("concurrent-test", text=f"version {i}")

    await asyncio.gather(*[update_policy(i) for i in range(10)])

    # Final policy should have one of the versions
    final = await persistence.get_policy("concurrent-test")
    assert final is not None
    assert final.text.startswith("version ")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
