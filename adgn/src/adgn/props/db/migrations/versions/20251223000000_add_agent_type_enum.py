"""Add agent_type PostgreSQL enum.

Creates agent_type_enum for the unified agent system. This enum identifies
different agent types (critic, grader, prompt_optimizer, clustering, freeform)
and is used in type_config JSONB discriminated unions.

Note: This migration only creates the enum type. The agent_runs table and
related schema changes will be added in subsequent migrations.

Revision ID: 20251223000000
Revises: 20251222000003
Create Date: 2025-12-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251223000000"
down_revision: str | Sequence[str] | None = "20251222000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create agent_type_enum PostgreSQL type.

    Enum values:
    - critic: Analyzes code snapshots and reports issues
    - grader: Evaluates critic output against ground truth
    - prompt_optimizer: Optimizes prompts using training/validation splits
    - clustering: Groups unknown issues into clusters
    - freeform: Ad-hoc sub-agents created by other agents
    """
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_type_enum') THEN
                CREATE TYPE agent_type_enum AS ENUM (
                    'critic',
                    'grader',
                    'prompt_optimizer',
                    'clustering',
                    'freeform'
                );
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    """Drop agent_type_enum type.

    Note: This will fail if any tables reference the type.
    Drop dependent tables first.
    """
    op.execute("DROP TYPE IF EXISTS agent_type_enum")
