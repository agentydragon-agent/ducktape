"""Restore occurrence_credits and dependent views.

Revision ID: 20251226000001
Revises: 20251226000000
Create Date: 2025-12-26

These views were dropped via CASCADE when 20251226000000 dropped the examples view,
but were not recreated. This migration restores them.
"""

from alembic import op

revision = "20251226000001"
down_revision = "20251226000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Recreate occurrence_credits view
    op.execute("""
        CREATE VIEW occurrence_credits AS
        SELECT
            -- Example identification
            (cr.type_config -> 'example' ->> 'snapshot_slug') AS snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            -- Ground truth
            gd.target_tp_id AS tp_id,
            gd.target_tp_occurrence_id AS occurrence_id,
            -- Critic-specific
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id AS critic_definition_id,
            cr.model AS critic_model,
            -- Grader-specific
            gr.agent_run_id AS grader_run_id,
            gr.agent_run_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.model AS grader_model,
            sum(gd.credit) AS found_credit,
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            max(gd.rationale) AS grader_rationale
        FROM agent_runs gr
        JOIN agent_runs cr ON cr.agent_run_id = get_graded_agent_run_id(gr.agent_run_id)
        JOIN snapshots s ON (cr.type_config -> 'example' ->> 'snapshot_slug') = s.slug
        JOIN examples ex ON (
            (cr.type_config -> 'example' ->> 'snapshot_slug') = ex.snapshot_slug
            AND (cr.type_config -> 'example' ->> 'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config -> 'example' ->> 'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        JOIN grading_decisions gd ON gr.agent_run_id = gd.agent_run_id
        WHERE (gr.type_config ->> 'agent_type') = 'grader'
          AND (cr.type_config ->> 'agent_type') = 'critic'
          AND gd.target_tp_id IS NOT NULL
        GROUP BY (cr.type_config -> 'example' ->> 'snapshot_slug'), s.split, ex.example_kind, ex.files_hash,
            gd.target_tp_id, gd.target_tp_occurrence_id, cr.agent_run_id, cr.agent_definition_id, cr.model,
            gr.agent_run_id, gr.created_at, gr.model
        UNION ALL
        SELECT
            -- Example identification
            (cr.type_config -> 'example' ->> 'snapshot_slug') AS snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            -- Ground truth
            tpo.tp_id,
            tpo.occurrence_id,
            -- Critic-specific
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id AS critic_definition_id,
            cr.model AS critic_model,
            -- Grader-specific (NULL for failed critics)
            NULL::uuid AS grader_run_id,
            NULL::uuid AS grader_transcript_id,
            cr.created_at AS graded_at,
            NULL::varchar AS grader_model,
            0.0 AS found_credit,
            NULL::jsonb AS matched_by_json,
            ('Critic failed: ' || cr.status) AS grader_rationale
        FROM agent_runs cr
        JOIN snapshots s ON (cr.type_config -> 'example' ->> 'snapshot_slug') = s.slug
        JOIN examples ex ON (
            (cr.type_config -> 'example' ->> 'snapshot_slug') = ex.snapshot_slug
            AND (cr.type_config -> 'example' ->> 'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config -> 'example' ->> 'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        CROSS JOIN true_positive_occurrences tpo
        WHERE (cr.type_config ->> 'agent_type') = 'critic'
          AND cr.status = ANY (ARRAY['max_turns_exceeded'::agent_run_status_enum, 'context_length_exceeded'::agent_run_status_enum])
          AND (cr.type_config -> 'example' ->> 'snapshot_slug') = tpo.snapshot_slug
          AND is_tp_catchable_from_scope(tpo.snapshot_slug, tpo.tp_id, ex.example_kind, ex.files_hash)
    """)

    # Recreate occurrence_run_credits view
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            -- Example identification
            snapshot_slug,
            split,
            example_kind,
            files_hash,
            -- Ground truth
            tp_id,
            occurrence_id,
            -- Critic-specific
            critic_run_id,
            critic_transcript_id,
            critic_definition_id,
            critic_model,
            -- Grader-specific
            grader_run_id,
            grader_transcript_id,
            graded_at,
            grader_model,
            sum(found_credit) AS total_credit,
            array_agg(DISTINCT matched_by_json) FILTER (WHERE matched_by_json IS NOT NULL) AS all_matched_by,
            string_agg(DISTINCT grader_rationale, ' | ') AS combined_rationale
        FROM occurrence_credits
        GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id,
            critic_run_id, critic_transcript_id, critic_definition_id, critic_model,
            grader_run_id, grader_transcript_id, graded_at, grader_model
    """)

    # Recreate occurrence_statistics view
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            -- Example identification
            snapshot_slug,
            split,
            example_kind,
            files_hash,
            -- Ground truth
            tp_id,
            occurrence_id,
            -- Critic-specific
            critic_definition_id,
            critic_model,
            -- Grader statistics
            grader_model,
            compute_stats_with_ci(array_agg(total_credit)) AS credit_stats
        FROM occurrence_run_credits
        GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id,
            critic_definition_id, critic_model, grader_model
    """)

    # Grant permissions to agent_base role
    op.execute("GRANT SELECT ON TABLE occurrence_credits TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_run_credits TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_statistics TO agent_base")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
