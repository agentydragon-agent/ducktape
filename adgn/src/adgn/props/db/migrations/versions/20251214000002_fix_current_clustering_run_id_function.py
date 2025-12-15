"""Fix current_clustering_run_id() function - remove EXCEPTION handler

Revision ID: 20251214000002
Revises: 20251214000001
Create Date: 2025-12-14 00:51:00.000000

The EXCEPTION WHEN OTHERS THEN RETURN NULL handler was silently swallowing errors
and causing the function to return NULL even when it should return a valid run_id.
Removing the handler fixes RLS filtering for clustering users.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251214000002"
down_revision = "20251214000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace current_clustering_run_id() function without EXCEPTION handler."""
    op.execute("""
        CREATE OR REPLACE FUNCTION current_clustering_run_id() RETURNS INTEGER AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Extract run_id from username pattern: clustering_run_{run_id}_agent
            run_id_text := SUBSTRING(current_user FROM 'clustering_run_([0-9]+)_agent');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::INTEGER;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """)


def downgrade() -> None:
    """Restore function with EXCEPTION handler (original broken version)."""
    op.execute("""
        CREATE OR REPLACE FUNCTION current_clustering_run_id() RETURNS INTEGER AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Extract run_id from username pattern: clustering_run_{run_id}_agent
            run_id_text := SUBSTRING(current_user FROM 'clustering_run_([0-9]+)_agent');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::INTEGER;
        EXCEPTION
            WHEN OTHERS THEN
                RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)
