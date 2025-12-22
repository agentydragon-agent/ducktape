"""Rename prompts.prompt_optimization_run_id to creator_agent_run_id.

Revision ID: 20251229000000
Revises: 20251228000000
Create Date: 2025-12-29

This migration:
1. Renames prompt_optimization_run_id column to creator_agent_run_id
2. Updates the FK constraint name
3. Updates the index name
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251229000000"
down_revision = "20251228000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop any FK constraint referencing prompt_optimization_run_id
    # The constraint name was auto-generated, so we need to find and drop it dynamically
    op.execute("""
        DO $$
        DECLARE
            fk_name TEXT;
        BEGIN
            -- Find the FK constraint name for prompt_optimization_run_id column
            SELECT constraint_name INTO fk_name
            FROM information_schema.constraint_column_usage
            WHERE table_name = 'prompts'
              AND column_name = 'prompt_optimization_run_id'
            LIMIT 1;

            -- Drop it if found
            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE prompts DROP CONSTRAINT %I', fk_name);
            END IF;
        END
        $$;
    """)

    # 2. Drop old index (may not exist if migration order differs)
    op.execute("DROP INDEX IF EXISTS ix_prompts_prompt_optimization_run_id")

    # 3. Rename the column
    op.alter_column("prompts", "prompt_optimization_run_id", new_column_name="creator_agent_run_id")

    # 4. Create new FK constraint pointing to agent_runs (not prompt_optimization_runs)
    op.create_foreign_key(
        "fk_prompts_creator_agent_run_id",
        "prompts",
        "agent_runs",
        ["creator_agent_run_id"],
        ["agent_run_id"],
        ondelete="CASCADE",
    )

    # 5. Create new index with updated name
    op.create_index("ix_prompts_creator_agent_run_id", "prompts", ["creator_agent_run_id"])


def downgrade() -> None:
    # 1. Drop new FK constraint and index
    op.drop_constraint("fk_prompts_creator_agent_run_id", "prompts", type_="foreignkey")
    op.drop_index("ix_prompts_creator_agent_run_id", table_name="prompts")

    # 2. Rename column back
    op.alter_column("prompts", "creator_agent_run_id", new_column_name="prompt_optimization_run_id")

    # 3. Recreate old FK constraint
    op.create_foreign_key(
        "prompts_prompt_optimization_run_id_fkey",
        "prompts",
        "prompt_optimization_runs",
        ["prompt_optimization_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 4. Recreate old index
    op.create_index("ix_prompts_prompt_optimization_run_id", "prompts", ["prompt_optimization_run_id"])
