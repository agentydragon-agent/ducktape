"""Temporary PostgreSQL user management with RLS-scoped access.

Creates ephemeral database users for improvement agents with access restricted to
specific training examples via Row-Level Security policies.

Usage:
    async with ImprovementUserManager(admin_config, run_id, allowed_examples) as creds:
        # Agent has scoped database access
        engine = create_engine(creds.url())
        ...
    # User and policies automatically cleaned up on exit
"""

from __future__ import annotations

import logging
from typing import ClassVar
from uuid import UUID

from sqlalchemy import text

from adgn.props.db.config import DbConnectionConfig
from adgn.props.db.temp_user_manager import TempUserManager, quote_ident
from adgn.props.ids import SnapshotSlug

logger = logging.getLogger(__name__)


class ImprovementUserManager(TempUserManager):
    """Temporary PostgreSQL user with RLS-scoped access to specific training examples.

    The created user can only read rows from specific training examples. This provides
    isolation for improvement agents analyzing subsets of the training data.

    Custom RLS policies are created per-user to filter tables by (snapshot_slug, scope_hash).
    """

    # Tables with policies (single source of truth for create/drop symmetry)
    # Policy creation/deletion both derive from this list
    POLICY_TABLES: ClassVar[list[str]] = [
        "snapshots",
        "true_positives",
        "false_positives",
        "examples",
        "critic_runs",
        "grader_runs",
        "events",
    ]

    def __init__(
        self,
        admin_config: DbConnectionConfig,
        run_id: UUID,
        allowed_examples: list[tuple[SnapshotSlug, str]],  # [(snapshot_slug, scope_hash), ...]
    ):
        """Initialize improvement user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Unique identifier for this improvement run
            allowed_examples: List of (snapshot_slug, scope_hash) tuples agent can access
                            (scope_hash is always non-null, even for whole-snapshot examples)

        Raises:
            ValueError: If allowed_examples is empty
        """
        if not allowed_examples:
            raise ValueError("allowed_examples must not be empty")

        super().__init__(admin_config)
        self.run_id = run_id
        self.allowed_examples = allowed_examples

    def generate_username(self) -> str:
        """Generate username with run ID prefix."""
        return f"improve_agent_{str(self.run_id)[:8]}"

    async def grant_permissions(self, username: str) -> None:
        """Grant read-only access and create custom RLS policies.

        Grants:
        - Schema usage
        - SELECT on all tables (RLS policies filter rows)

        Then creates custom RLS policies for each table based on allowed_examples.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)

            # Grant schema access
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_username}"))

            # Grant SELECT on all tables (agent is read-only)
            # RLS policies will further restrict which rows are visible
            await conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {quoted_username}"))

        logger.debug(f"Granted base permissions to {username}")

        # Create custom RLS policies
        await self._create_policies(username)

    async def revoke_permissions(self, username: str) -> None:
        """Drop custom RLS policies before revoking grants."""
        # Drop custom policies first
        await self._drop_policies(username)

        # Then revoke grants
        await super().revoke_permissions(username)

    async def _create_policies(self, username: str) -> None:
        """Create RLS policies to scope access to specific training examples.

        Policies filter tables by (snapshot_slug, scope_hash) pairs. Different tables
        need different policy patterns based on their schema:

        - snapshots/true_positives/false_positives: Filter by snapshot_slug IN (...)
        - critic_runs: Filter by (snapshot_slug, scope_hash) IN VALUES (...)
        - grader_runs: Filter by critic_run_id IN (SELECT id FROM critic_runs WHERE ...)
        - events: Filter via FK to critic_runs (transcript_id)
        """
        # Extract unique snapshot slugs for snapshot-only tables
        snapshot_slugs = sorted({slug for slug, _ in self.allowed_examples})
        snapshot_slug_list = ", ".join(f"'{slug}'" for slug in snapshot_slugs)

        # Build VALUES clause for (snapshot_slug, scope_hash) pairs
        values_clause = ", ".join(f"('{slug}', '{hash_}')" for slug, hash_ in self.allowed_examples)

        # Policy definitions (table_name → USING clause)
        # Keys must match POLICY_TABLES
        policies = {
            # Snapshot-level tables (no scope_hash)
            "snapshots": f"(slug IN ({snapshot_slug_list}))",
            "true_positives": f"(snapshot_slug IN ({snapshot_slug_list}))",
            "false_positives": f"(snapshot_slug IN ({snapshot_slug_list}))",
            # Example-level tables with (snapshot_slug, scope_hash)
            "examples": f"((snapshot_slug, scope_hash) IN (VALUES {values_clause}))",
            "critic_runs": f"((snapshot_slug, scope_hash) IN (VALUES {values_clause}))",
            # Grader runs: filter by critic_run_id being in allowed critic_runs
            "grader_runs": f"""(critic_run_id IN (
                SELECT id FROM critic_runs
                WHERE (snapshot_slug, scope_hash) IN (VALUES {values_clause})
            ))""",
            # Events: FK to critic_runs via transcript_id
            "events": f"""(transcript_id IN (
                SELECT transcript_id FROM critic_runs
                WHERE (snapshot_slug, scope_hash) IN (VALUES {values_clause})
            ))""",
        }

        # Verify policies dict matches POLICY_TABLES
        missing = set(self.POLICY_TABLES) - set(policies.keys())
        if missing:
            raise RuntimeError(f"Policy definitions missing for tables: {missing}")

        assert self.admin_engine is not None, "admin_engine not initialized"
        created_count = 0
        async with self.admin_engine.begin() as conn:
            for table_name in self.POLICY_TABLES:
                using_clause = policies[table_name]
                policy_name = f"{username}_{table_name}"

                # Check if policy already exists
                result = await conn.execute(
                    text(
                        "SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = :table AND policyname = :policy"
                    ),
                    {"table": table_name, "policy": policy_name},
                )
                exists = result.scalar() is not None

                if exists:
                    logger.debug(f"Policy {policy_name} already exists on {table_name}, skipping")
                    continue

                # Create policy
                policy_sql = (
                    f"CREATE POLICY {policy_name} ON {table_name} FOR SELECT TO {username} USING {using_clause}"
                )
                await conn.execute(text(policy_sql))
                created_count += 1
                logger.debug(f"Created policy: {policy_name} on {table_name}")

        logger.info(f"Created {created_count} RLS policies for {username}")

    async def _drop_policies(self, username: str) -> None:
        """Drop RLS policies for this user.

        Drops policies for all tables in POLICY_TABLES (symmetric with _create_policies).
        Uses DROP POLICY IF EXISTS for idempotency.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            for table_name in self.POLICY_TABLES:
                policy_name = f"{username}_{table_name}"
                await conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))

        logger.debug(f"Dropped policies for {username} from {len(self.POLICY_TABLES)} tables")
