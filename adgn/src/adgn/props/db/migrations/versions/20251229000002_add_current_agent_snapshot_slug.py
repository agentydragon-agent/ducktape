"""Add SECURITY DEFINER helper functions for RLS policies.

The RLS policies on snapshots and examples need to access agent type_config data.
Subqueries in policies are subject to RLS on agent_runs, causing recursive RLS checks.

Fix: Create SECURITY DEFINER functions that bypass RLS:
- current_agent_snapshot_slug() - for critics/clustering/graders
- current_agent_scope_hash() - for critics
- current_grader_snapshot_slug() - for graders (derives from graded critic)

Revision ID: 20251229000002
Revises: 20251229000001
Create Date: 2025-12-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251229000002"
down_revision: str | Sequence[str] | None = "20251229000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extract_run_id_sql() -> str:
    """Return SQL block to extract run_id from session_user into variable 'run_id'.

    Uses session_user (not current_user) to work correctly inside SECURITY DEFINER.
    Username pattern: agent_{uuid}
    """
    return """
            -- Extract run_id directly from session_user (not current_user)
            -- session_user is the original user that started the session,
            -- while current_user changes to the function owner in SECURITY DEFINER
            -- Username pattern: agent_{uuid}
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;
    """


def upgrade() -> None:
    """Create SECURITY DEFINER helper functions and update RLS policies."""
    # Create SECURITY DEFINER function to get snapshot_slug from type_config
    op.execute(f"""
        CREATE OR REPLACE FUNCTION current_agent_snapshot_slug() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            snapshot_slug TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            {_extract_run_id_sql()}

            SELECT type_config->>'snapshot_slug' INTO snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN snapshot_slug;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_snapshot_slug() IS
            'Returns the snapshot_slug from the current agent''s type_config. Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Create SECURITY DEFINER function to get scope_hash from type_config (for critics)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION current_agent_scope_hash() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            scope_hash TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            {_extract_run_id_sql()}

            SELECT type_config->>'scope_hash' INTO scope_hash
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN scope_hash;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_scope_hash() IS
            'Returns the scope_hash from the current agent''s type_config (for critics). Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Create SECURITY DEFINER function to get snapshot_slug for graders (from graded agent)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION current_grader_snapshot_slug() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            snapshot_slug TEXT;
            run_id UUID;
            run_id_text TEXT;
            graded_run_id UUID;
        BEGIN
            {_extract_run_id_sql()}

            -- Get the graded agent run ID from current agent's type_config
            SELECT (type_config->>'graded_agent_run_id')::UUID INTO graded_run_id
            FROM agent_runs
            WHERE agent_run_id = run_id;

            IF graded_run_id IS NULL THEN
                RETURN NULL;
            END IF;

            -- Get the snapshot_slug from the graded agent's type_config
            SELECT type_config->>'snapshot_slug' INTO snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = graded_run_id;

            RETURN snapshot_slug;
        END;
        $$;

        COMMENT ON FUNCTION current_grader_snapshot_slug() IS
            'Returns the snapshot_slug from the graded agent''s type_config (for graders). Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Update snapshots policy to use the new functions
    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- For critics and clustering: snapshot_slug is directly in type_config
                (
                    current_agent_type() IN ('critic', 'clustering')
                    AND slug = current_agent_snapshot_slug()
                )
                OR
                -- For graders: snapshot_slug is derived from the graded critic's type_config
                (
                    current_agent_type() = 'grader'
                    AND slug = current_grader_snapshot_slug()
                )
            );
    """)

    # Update examples policy to use the new functions
    op.execute("""
        DROP POLICY IF EXISTS examples_agent_select ON examples;

        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                -- Critics can only see their specific example
                current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_snapshot_slug()
                AND scope_hash = current_agent_scope_hash()
            );
    """)


def downgrade() -> None:
    """Restore original policies and drop the helper functions."""
    # Restore original snapshots policy (with inline subqueries)
    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- For critics (and clustering): snapshot_slug is directly in type_config
                (
                    current_agent_type() IN ('critic', 'clustering')
                    AND slug = (
                        SELECT type_config->>'snapshot_slug'
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
                OR
                -- For graders: snapshot_slug is derived from the graded critic's type_config
                (
                    current_agent_type() = 'grader'
                    AND slug = (
                        SELECT graded.type_config->>'snapshot_slug'
                        FROM agent_runs grader
                        INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                        WHERE grader.agent_run_id = current_agent_run_id()
                    )
                )
            );
    """)

    # Restore original examples policy (with inline subqueries)
    op.execute("""
        DROP POLICY IF EXISTS examples_agent_select ON examples;

        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                snapshot_slug = (
                    SELECT type_config->>'snapshot_slug'
                    FROM agent_runs
                    WHERE agent_run_id = current_agent_run_id()
                )
                AND scope_hash = (
                    SELECT type_config->>'scope_hash'
                    FROM agent_runs
                    WHERE agent_run_id = current_agent_run_id()
                )
            );
    """)

    # Drop the helper functions
    op.execute("DROP FUNCTION IF EXISTS current_agent_snapshot_slug() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_agent_scope_hash() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_grader_snapshot_slug() CASCADE")
