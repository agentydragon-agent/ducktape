"""Drop clustering tables and related objects.

Removes the clustering feature entirely:
- unknown_assignments table
- unknown_clusters table
- check_unknown_mapping_exists function and trigger
- Related RLS policies and grants
- Updates policies that referenced 'clustering' agent type

Revision ID: 20251227000003
Revises: 20251227000002
Create Date: 2025-12-27
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251227000003"
down_revision = "20251227000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop RLS policies for clustering tables first
    op.execute("DROP POLICY IF EXISTS unknown_clusters_agent_select ON unknown_clusters")
    op.execute("DROP POLICY IF EXISTS unknown_clusters_agent_insert ON unknown_clusters")
    op.execute("DROP POLICY IF EXISTS unknown_clusters_agent_update ON unknown_clusters")
    op.execute("DROP POLICY IF EXISTS unknown_assignments_agent_select ON unknown_assignments")
    op.execute("DROP POLICY IF EXISTS unknown_assignments_agent_insert ON unknown_assignments")
    op.execute("DROP POLICY IF EXISTS unknown_assignments_agent_update ON unknown_assignments")

    # Drop trigger before function
    op.execute("DROP TRIGGER IF EXISTS check_unknown_mapping_exists_trigger ON unknown_assignments")

    # Drop tables (unknown_assignments first due to FK to unknown_clusters)
    op.execute("DROP TABLE IF EXISTS unknown_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS unknown_clusters CASCADE")

    # Drop the validation function
    op.execute("DROP FUNCTION IF EXISTS check_unknown_mapping_exists()")

    # Note: PostgreSQL doesn't support removing enum values directly.
    # The 'clustering' value in agent_type_enum is now orphaned but harmless.
    op.execute("""
        COMMENT ON TYPE agent_type_enum IS
        'Agent types. Note: clustering value is deprecated and unused.'
    """)

    # Update can_access_snapshot to remove clustering branch
    op.execute("DROP FUNCTION IF EXISTS can_access_snapshot(text) CASCADE")
    op.execute("""
        CREATE FUNCTION can_access_snapshot(p_slug text) RETURNS boolean
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        BEGIN
            RETURN (
                (current_agent_type() = 'prompt_optimizer' AND is_train_snapshot(p_slug))
                OR (current_agent_type() = 'grader' AND p_slug = get_graded_snapshot_slug(current_agent_run_id()))
                OR (current_agent_type() = 'improvement' AND is_improvement_snapshot_allowed(p_slug))
            );
        END;
        $$
    """)
    op.execute("""
        COMMENT ON FUNCTION can_access_snapshot(text) IS
        'Unified snapshot access check for RLS policies. Returns TRUE if current agent can access the given snapshot.
Used by true_positives, false_positives, and their occurrence tables.'
    """)

    # Recreate policies that depend on can_access_snapshot (they were dropped by CASCADE)
    op.execute(
        "CREATE POLICY true_positives_agent_select ON true_positives FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )
    op.execute(
        "CREATE POLICY false_positives_agent_select ON false_positives FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )
    op.execute(
        "CREATE POLICY tp_occurrences_agent_select ON true_positive_occurrences FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )
    op.execute(
        "CREATE POLICY fp_occurrences_agent_select ON false_positive_occurrences FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )
    op.execute(
        "CREATE POLICY occ_triggers_agent_select ON occurrence_triggers FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # Update agent_runs RLS policy to remove clustering branch
    op.execute("DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs")
    op.execute("""
        CREATE POLICY agent_runs_agent_select ON agent_runs FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer'
             AND (((type_config->>'agent_type') = 'critic' AND is_train_snapshot(type_config->'example'->>'snapshot_slug'))
                  OR ((type_config->>'agent_type') = 'grader' AND is_train_snapshot(get_graded_snapshot_slug(agent_run_id)))))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'grader' AND agent_run_id = current_graded_agent_run_id())
            OR (current_agent_type() = 'improvement'
                AND (type_config->>'agent_type') IN ('critic', 'grader')
                AND is_improvement_example_allowed(type_config->'example'->>'snapshot_slug', (type_config->'example'->>'kind')::example_kind_enum, (type_config->'example'->>'files_hash')))
        )
    """)

    # Update file_sets RLS policy to remove clustering branch
    op.execute("DROP POLICY IF EXISTS file_sets_agent_select ON file_sets")
    op.execute("""
        CREATE POLICY file_sets_agent_select ON file_sets FOR SELECT USING (
            -- Prompt optimizer in whole-repo mode: only TRAIN file_sets
            (current_agent_type() = 'prompt_optimizer'
             AND current_agent_type_config()->>'target_metric' = 'whole_repo'
             AND is_train_snapshot(snapshot_slug))
            -- Prompt optimizer in targeted mode: TRAIN + VALID file_sets
            OR (current_agent_type() = 'prompt_optimizer'
                AND (current_agent_type_config()->>'target_metric' IS NULL
                     OR current_agent_type_config()->>'target_metric' != 'whole_repo')
                AND is_train_or_valid_snapshot(snapshot_slug))
            -- Critic: only their example's file_set
            OR (current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_type_config()->'example'->>'snapshot_slug'
                AND files_hash = current_agent_type_config()->'example'->>'files_hash')
            -- Grader: graded example's file_set
            OR (current_agent_type() = 'grader'
                AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id()))
            -- Improvement: allowed snapshots only
            OR (current_agent_type() = 'improvement'
                AND is_improvement_snapshot_allowed(snapshot_slug))
        )
    """)

    # Update file_set_members RLS policy to remove clustering branch
    op.execute("DROP POLICY IF EXISTS file_set_members_agent_select ON file_set_members")
    op.execute("""
        CREATE POLICY file_set_members_agent_select ON file_set_members FOR SELECT USING (
            -- Prompt optimizer in whole-repo mode: only TRAIN file_set_members
            (current_agent_type() = 'prompt_optimizer'
             AND current_agent_type_config()->>'target_metric' = 'whole_repo'
             AND is_train_snapshot(snapshot_slug))
            -- Prompt optimizer in targeted mode: TRAIN + VALID file_set_members
            OR (current_agent_type() = 'prompt_optimizer'
                AND (current_agent_type_config()->>'target_metric' IS NULL
                     OR current_agent_type_config()->>'target_metric' != 'whole_repo')
                AND is_train_or_valid_snapshot(snapshot_slug))
            -- Critic: own example's file_set_members
            OR (current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_type_config()->'example'->>'snapshot_slug')
            -- Grader: graded snapshot's file_set_members
            OR (current_agent_type() = 'grader'
                AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id()))
            -- Improvement: allowed snapshots' file_set_members
            OR (current_agent_type() = 'improvement'
                AND is_improvement_snapshot_allowed(snapshot_slug))
        )
    """)

    # Update events RLS policy to remove clustering branch
    op.execute("DROP POLICY IF EXISTS events_agent_select ON events")
    op.execute("""
        CREATE POLICY events_agent_select ON events FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer' AND is_train_agent_run(agent_run_id))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'improvement'
                AND agent_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
        )
    """)


def downgrade() -> None:
    # This is a destructive migration - downgrade would need to recreate the tables
    # For simplicity, we don't support downgrade
    raise NotImplementedError("Downgrade not supported - clustering feature has been removed")
