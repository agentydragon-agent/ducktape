"""SQLAlchemy query builders for agent-accessible database queries.

Each function returns a SQLAlchemy Select object that can be:
- Executed directly in tests: session.execute(query).fetchall()
- Compiled to SQL string for j2 templates: compile_to_sql(query)

This provides a single source of truth for query structure, eliminating duplication
between test execution and template injection.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, bindparam, cast, column, func, literal, select, table, text, type_coerce, union_all
from sqlalchemy.dialects import postgresql

from adgn.props.db.models import (
    CriticRun,
    Critique,
    Event,
    FalsePositive,
    GraderRun,
    Prompt,
    RunCost,
    Snapshot,
    TruePositive,
)
from adgn.props.ids import SnapshotSlug


def compile_to_sql(query: Select, *, literal_binds: bool = True) -> str:
    """Compile a SQLAlchemy Select to SQL string for template injection.

    Args:
        query: SQLAlchemy Select object
        literal_binds: If True, inline bound parameters as literals (for static SQL)
                      If False, use named placeholders like :param_name

    Returns:
        SQL string suitable for embedding in Jinja2 templates
    """
    compiled = query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": literal_binds} if literal_binds else {}
    )
    return str(compiled)


def compile_to_sql_with_placeholders(query: Select) -> str:
    """Compile query to SQL with named parameter placeholders.

    Args:
        query: SQLAlchemy Select object with bound parameters

    Returns:
        SQL string with placeholders like :transcript_id, :snapshot_slug

    Example:
        >>> q = select(Event).where(Event.transcript_id == bindparam('transcript_id'))
        >>> compile_to_sql_with_placeholders(q)
        'SELECT ... WHERE transcript_id = :transcript_id'
    """
    return compile_to_sql(query, literal_binds=False)


# ============================================================================
# Snapshot queries
# ============================================================================


def list_train_snapshots() -> Select:
    """List all train split snapshots.

    Returns:
        Query selecting (slug, split) from train snapshots, ordered by slug
    """
    return select(Snapshot.slug, Snapshot.split).where(Snapshot.split == "train").order_by(Snapshot.slug)


def list_snapshots_by_split(split: str) -> Select:
    """List all snapshots for a given split.

    Args:
        split: One of 'train', 'valid', 'test'

    Returns:
        Query selecting (slug, split) from snapshots with given split, ordered by slug
    """
    return select(Snapshot.slug, Snapshot.split).where(Snapshot.split == split).order_by(Snapshot.slug)


# ============================================================================
# True positive / false positive queries
# ============================================================================


def list_true_positives_for_snapshot(snapshot_slug: SnapshotSlug) -> Select:
    """Get all true positives for a snapshot.

    Args:
        snapshot_slug: Snapshot slug to query

    Returns:
        Query selecting (tp_id, rationale, occurrences) for given snapshot
    """
    return (
        select(TruePositive.tp_id, TruePositive.rationale, TruePositive.occurrences)
        .where(TruePositive.snapshot_slug == snapshot_slug)  # type: ignore[arg-type]
        .order_by(TruePositive.tp_id)
    )


def list_false_positives_for_snapshot(snapshot_slug: SnapshotSlug) -> Select:
    """Get all false positives for a snapshot.

    Args:
        snapshot_slug: Snapshot slug to query

    Returns:
        Query selecting (fp_id, rationale, occurrences) for given snapshot
    """
    return (
        select(FalsePositive.fp_id, FalsePositive.rationale, FalsePositive.occurrences)
        .where(FalsePositive.snapshot_slug == snapshot_slug)  # type: ignore[arg-type]
        .order_by(FalsePositive.fp_id)
    )


def list_train_true_positives() -> Select:
    """List all true positives for train split snapshots.

    Returns:
        Query selecting (snapshot_slug, tp_id, rationale) for train snapshots
    """
    return (
        select(TruePositive.snapshot_slug, TruePositive.tp_id, TruePositive.rationale)
        .join(Snapshot, TruePositive.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == "train")
        .order_by(TruePositive.snapshot_slug, TruePositive.tp_id)
    )


def list_train_false_positives() -> Select:
    """List all false positives for train split snapshots.

    Returns:
        Query selecting (snapshot_slug, fp_id, rationale) for train snapshots
    """
    return (
        select(FalsePositive.snapshot_slug, FalsePositive.fp_id, FalsePositive.rationale)
        .join(Snapshot, FalsePositive.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == "train")
        .order_by(FalsePositive.snapshot_slug, FalsePositive.fp_id)
    )


def count_issues_by_snapshot(split: str | None = None) -> Select:
    """Count true positives and false positives per snapshot.

    Args:
        split: Optional split filter ('train', 'valid', 'test')

    Returns:
        Query selecting (snapshot_slug, tp_count, fp_count)
    """
    # Subquery for TP counts
    tp_counts = (
        select(TruePositive.snapshot_slug, func.count().label("tp_count"))
        .group_by(TruePositive.snapshot_slug)
        .subquery()
    )

    # Subquery for FP counts
    fp_counts = (
        select(FalsePositive.snapshot_slug, func.count().label("fp_count"))
        .group_by(FalsePositive.snapshot_slug)
        .subquery()
    )

    # Main query joining snapshots with counts
    query = (
        select(
            Snapshot.slug.label("snapshot_slug"),
            func.coalesce(tp_counts.c.tp_count, 0).label("tp_count"),
            func.coalesce(fp_counts.c.fp_count, 0).label("fp_count"),
        )
        .outerjoin(tp_counts, Snapshot.slug == tp_counts.c.snapshot_slug)
        .outerjoin(fp_counts, Snapshot.slug == fp_counts.c.snapshot_slug)
        .order_by(Snapshot.slug)
    )

    if split is not None:
        query = query.where(Snapshot.split == split)

    return query


# ============================================================================
# Grader result queries
# ============================================================================


def recent_grader_results(limit: int = 10) -> Select:
    """Get recent grader runs with metrics for train split.

    Args:
        limit: Maximum number of results (default 10)

    Returns:
        Query selecting grader run details with recall/precision/metrics
    """
    return (
        select(
            GraderRun.snapshot_slug,
            GraderRun.transcript_id,
            GraderRun.output["grade"]["recall"].astext.label("recall"),
            GraderRun.output["grade"]["precision"].astext.label("precision"),
            GraderRun.output["grade"]["metrics"]["true_positives"].astext.label("tp"),
            GraderRun.output["grade"]["metrics"]["false_positives"].astext.label("fp"),
            GraderRun.output["grade"]["metrics"]["false_negatives"].astext.label("fn"),
            GraderRun.model,
            GraderRun.created_at,
        )
        .join(Snapshot, GraderRun.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == "train")
        .where(GraderRun.output.isnot(None))
        .order_by(GraderRun.created_at.desc())
        .limit(limit)
    )


def snapshot_files_with_issues_select() -> Select:
    """Define the SELECT query for the snapshot_files_with_issues view.

    Computes the set of files with issues for each snapshot by extracting all file paths
    (dict keys) from true_positives and false_positives occurrences.

    Replicates the logic of Snapshot.files_with_issues() method (models.py:196-204):
        tp_files = {file_path for tp in self.true_positives
                    for occurrence in tp.occurrences
                    for file_path in occurrence.files}
        fp_files = {file_path for fp in self.false_positives
                    for occurrence in fp.occurrences
                    for file_path in occurrence.files}
        return tp_files | fp_files

    RLS Note: This view inherits RLS from true_positives and false_positives tables,
    which filter to split='train' for agent_user. For completeness, we also join
    with snapshots to ensure snapshot_slug is valid.

    Returns:
        Query selecting snapshot_slug and files_with_issues (text array) for each snapshot
    """
    # Extract all file paths (dict keys) from TP occurrences
    # true_positives.occurrences is JSONB array of {files: {...}, ...}
    # RLS on true_positives ensures only train split is visible to agent_user
    tp_files = select(
        TruePositive.snapshot_slug,
        func.jsonb_object_keys(func.jsonb_array_elements(TruePositive.occurrences).op("->")(literal("files"))).label(
            "file_path"
        ),
    ).select_from(TruePositive)

    # Extract all file paths from FP occurrences
    # RLS on false_positives ensures only train split is visible to agent_user
    fp_files = select(
        FalsePositive.snapshot_slug,
        func.jsonb_object_keys(func.jsonb_array_elements(FalsePositive.occurrences).op("->")(literal("files"))).label(
            "file_path"
        ),
    ).select_from(FalsePositive)

    # Union and aggregate per snapshot
    all_files_union = union_all(tp_files, fp_files).subquery()

    # Join with snapshots to ensure snapshot_slug is valid and inherits snapshots RLS (no-op for train filter)
    return (
        select(
            all_files_union.c.snapshot_slug,
            func.array_agg(func.distinct(all_files_union.c.file_path)).label("files_with_issues"),
        )
        .select_from(all_files_union)
        .join(Snapshot, all_files_union.c.snapshot_slug == Snapshot.slug)
        .group_by(all_files_union.c.snapshot_slug)
    )


def valid_full_snapshot_grader_metrics_select() -> Select:
    """Define the SELECT query for the valid_full_snapshot_grader_metrics view.

    Shows grader runs for valid split with full provenance:
    - Which critique was graded
    - How it was produced (critic prompt, model)
    - How it was graded (grader run ID, model)
    - What score it got (recall)

    Filters to full-snapshot critiques only (where critic reviewed ALL files with issues).

    A full-snapshot run is defined as: CriticRun.files (JSONB array) contains exactly
    the same files as computed by the snapshot_files_with_issues view (which replicates
    Snapshot.files_with_issues() method).

    Returns:
        Query defining the view's row structure (not aggregated)
    """
    # Reference the snapshot_files_with_issues view
    # This view computes files_with_issues for each snapshot (same logic as Snapshot.files_with_issues())

    # Create a table reference for the snapshot_files_with_issues view
    snapshot_files_view = table("snapshot_files_with_issues", column("snapshot_slug"), column("files_with_issues"))

    # Main query: join to snapshot_files_with_issues view and filter for full-snapshot runs
    # Use bidirectional array containment (@> and <@) to check set equality
    return (
        select(
            GraderRun.snapshot_slug,
            GraderRun.critique_id.label("critique_id"),
            CriticRun.prompt_sha256.label("critic_prompt_sha256"),
            CriticRun.model.label("critic_model"),
            GraderRun.id.label("grader_run_id"),
            GraderRun.model.label("grader_model"),
            (GraderRun.output["grade"]["recall"].astext.cast(postgresql.DOUBLE_PRECISION)).label("recall"),
            GraderRun.created_at,
        )
        .select_from(GraderRun)
        .join(Snapshot, GraderRun.snapshot_slug == Snapshot.slug)
        .join(Critique, GraderRun.critique_id == Critique.id)
        .join(CriticRun, Critique.id == CriticRun.critique_id)
        .join(
            snapshot_files_view,
            text(
                "grader_runs.snapshot_slug::text = snapshot_files_with_issues.snapshot_slug::text AND "
                "ARRAY(SELECT jsonb_array_elements_text(critic_runs.files)) @> snapshot_files_with_issues.files_with_issues AND "
                "ARRAY(SELECT jsonb_array_elements_text(critic_runs.files)) <@ snapshot_files_with_issues.files_with_issues"
            ),
        )
        .where(Snapshot.split == "valid")
        .where(GraderRun.output.isnot(None))
    )


def valid_aggregates_view() -> Select:
    """Get aggregate grader metrics for valid split (from view).

    Returns:
        Query selecting avg_recall, snapshot_count, run_count, grader_model
    """
    # This queries the materialized view valid_full_snapshot_grader_metrics
    # We use text() to reference the view since it's not mapped as an ORM model
    return (
        select(
            text("AVG(recall) as avg_recall"),
            text("COUNT(DISTINCT snapshot_slug) as snapshot_count"),
            text("COUNT(*) as run_count"),
            text("grader_model"),
        )
        .select_from(text("valid_full_snapshot_grader_metrics"))
        .group_by(text("grader_model"))
        .order_by(text("avg_recall DESC"))
    )


# ============================================================================
# Critique queries
# ============================================================================


def critiques_for_snapshot(snapshot_slug: SnapshotSlug, limit: int = 5) -> Select:
    """Get recent critiques for a specific snapshot.

    Args:
        snapshot_slug: Snapshot to query
        limit: Maximum number of results (default 5)

    Returns:
        Query selecting critique details with related run info
    """
    return (
        select(
            Critique.id,
            Critique.payload,
            Critique.created_at,
            CriticRun.prompt_sha256,
            CriticRun.model,
            CriticRun.files,
        )
        .outerjoin(CriticRun, Critique.id == CriticRun.critique_id)
        .where(Critique.snapshot_slug == snapshot_slug)  # type: ignore[arg-type]
        .order_by(Critique.created_at.desc())
        .limit(limit)
    )


def link_grader_to_prompt(snapshot_slug: SnapshotSlug, limit: int = 1) -> Select:
    """Link grader run to its prompt text via critique and critic run.

    Args:
        snapshot_slug: Snapshot to query
        limit: Maximum number of results (default 1)

    Returns:
        Query selecting grader_run_id, snapshot_slug, recall, critique_id,
        critic_run_id, prompt_sha256, prompt_text
    """
    return (
        select(
            GraderRun.id.label("grader_run_id"),
            GraderRun.snapshot_slug,
            GraderRun.output["grade"]["recall"].astext.label("recall"),
            Critique.id.label("critique_id"),
            CriticRun.id.label("critic_run_id"),
            CriticRun.prompt_sha256,
            Prompt.prompt_text,
        )
        .join(Critique, GraderRun.critique_id == Critique.id)
        .join(CriticRun, Critique.id == CriticRun.critique_id)
        .join(Prompt, CriticRun.prompt_sha256 == Prompt.prompt_sha256)
        .where(GraderRun.snapshot_slug == snapshot_slug)  # type: ignore[arg-type]
        .where(GraderRun.output.isnot(None))
        .limit(limit)
    )


# ============================================================================
# Event trajectory queries (require transcript_id parameter)
# ============================================================================


def tools_used_by_transcript(transcript_id: UUID) -> Select:
    """Count tool usage by name for a given transcript.

    Args:
        transcript_id: Transcript UUID to query

    Returns:
        Query selecting (tool_name, count) ordered by count descending
    """
    return (
        select(Event.payload["name"].astext.label("tool_name"), func.count().label("count"))
        .where(Event.transcript_id == transcript_id, Event.event_type == "tool_call")
        .group_by(Event.payload["name"].astext)
        .order_by(func.count().desc())
    )


def tool_sequence_by_transcript(transcript_id: UUID) -> Select:
    """Get tool call sequence for a transcript.

    Args:
        transcript_id: Transcript UUID to query

    Returns:
        Query selecting (sequence_num, timestamp, tool_name) ordered by sequence
    """
    return (
        select(Event.sequence_num, Event.timestamp, Event.payload["name"].astext.label("tool_name"))
        .where(Event.transcript_id == transcript_id, Event.event_type == "tool_call")
        .order_by(Event.sequence_num)
    )


def failed_tools_by_transcript(transcript_id: UUID) -> Select:
    """Get failed tool calls for a transcript.

    Args:
        transcript_id: Transcript UUID to query

    Returns:
        Query selecting (tool_name, is_error, result) for failed tools
    """
    # Alias tables for the join
    e1 = Event.__table__.alias("e1")
    e2 = Event.__table__.alias("e2")

    return (
        select(
            e1.c.payload["name"].astext.label("tool_name"),
            e2.c.payload["result"]["isError"].astext.label("is_error"),
            # Use type_coerce to treat as plain JSONB (bypasses PydanticColumn validation)
            type_coerce(e2.c.payload["result"], postgresql.JSONB).label("result"),
        )
        .select_from(e1)
        .join(
            e2,
            (e1.c.transcript_id == e2.c.transcript_id)
            & (e1.c.payload["call_id"].astext == e2.c.payload["call_id"].astext),
        )
        .where(
            e1.c.transcript_id == transcript_id,
            e1.c.event_type == "tool_call",
            e2.c.event_type == "function_call_output",
            cast(e2.c.payload["result"]["isError"].astext, postgresql.BOOLEAN),
        )
    )


# ============================================================================
# Parameterized query builders (for agent-side parameter substitution)
# ============================================================================


def critiques_for_snapshot_parameterized() -> Select:
    """Get critiques for a snapshot (parameterized with :snapshot_slug placeholder).

    Agents fill in :snapshot_slug at runtime.
    """
    return critiques_for_snapshot(bindparam("snapshot_slug"), limit=5)  # type: ignore[arg-type]


def link_grader_to_prompt_parameterized() -> Select:
    """Link grader to prompt for a snapshot (parameterized with :snapshot_slug placeholder).

    Agents fill in :snapshot_slug at runtime.
    """
    return link_grader_to_prompt(bindparam("snapshot_slug"), limit=1)  # type: ignore[arg-type]


def tools_used_by_transcript_parameterized() -> Select:
    """Tool usage by transcript (parameterized with :transcript_id placeholder).

    Agents fill in :transcript_id at runtime.
    """
    return tools_used_by_transcript(bindparam("transcript_id"))  # type: ignore[arg-type]


def tool_sequence_by_transcript_parameterized() -> Select:
    """Tool sequence by transcript (parameterized with :transcript_id placeholder).

    Agents fill in :transcript_id at runtime.
    """
    return tool_sequence_by_transcript(bindparam("transcript_id"))  # type: ignore[arg-type]


def failed_tools_by_transcript_parameterized() -> Select:
    """Failed tools by transcript (parameterized with :transcript_id placeholder).

    Agents fill in :transcript_id at runtime.
    """
    return failed_tools_by_transcript(bindparam("transcript_id"))  # type: ignore[arg-type]


def po_run_costs(po_run_id: UUID) -> Select:
    """Get per-run costs and totals for a prompt optimization run.

    Args:
        po_run_id: Prompt optimization run UUID

    Returns:
        Query selecting transcript details with cost/token metrics from run_costs view
    """
    # CTE for PO transcripts
    po_transcripts = (
        select(
            CriticRun.transcript_id, CriticRun.snapshot_slug, literal("critic").label("run_type"), CriticRun.created_at
        )
        .where(CriticRun.prompt_optimization_run_id == po_run_id)
        .union_all(
            select(
                GraderRun.transcript_id,
                GraderRun.snapshot_slug,
                literal("grader").label("run_type"),
                GraderRun.created_at,
            ).where(GraderRun.prompt_optimization_run_id == po_run_id)
        )
        .cte("po_transcripts")
    )

    # Main query joining with run_costs view (mapped as RunCost ORM model)
    return (
        select(
            po_transcripts.c.transcript_id,
            po_transcripts.c.snapshot_slug,
            po_transcripts.c.run_type,
            RunCost.model,
            func.sum(RunCost.cost_usd).label("cost_usd"),
            func.sum(RunCost.input_tokens).label("input_tokens"),
            func.sum(RunCost.cached_tokens).label("cached_tokens"),
            func.sum(RunCost.output_tokens).label("output_tokens"),
            po_transcripts.c.created_at,
        )
        .select_from(po_transcripts)
        .join(RunCost, po_transcripts.c.transcript_id == RunCost.transcript_id)
        .group_by(
            po_transcripts.c.transcript_id,
            po_transcripts.c.snapshot_slug,
            po_transcripts.c.run_type,
            RunCost.model,
            po_transcripts.c.created_at,
        )
        .order_by(po_transcripts.c.created_at.desc())
    )


def po_run_costs_parameterized() -> Select:
    """PO run costs (parameterized with :po_run_id placeholder).

    Agents fill in :po_run_id at runtime.
    """
    return po_run_costs(bindparam("po_run_id"))  # type: ignore[arg-type]


# ============================================================================
# RLS blocked queries (examples showing what's blocked by RLS)
# ============================================================================


def blocked_valid_critiques() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Returns:
        Query attempting to select critiques for valid split snapshots
    """
    return select(Critique.id, Critique.payload).where(
        Critique.snapshot_slug.in_(select(Snapshot.slug).where(Snapshot.split == "valid"))
    )


def blocked_valid_grader_runs() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Returns:
        Query attempting to select grader runs for valid split snapshots
    """
    return select(GraderRun.id, GraderRun.output).where(
        GraderRun.snapshot_slug.in_(select(Snapshot.slug).where(Snapshot.split == "valid"))
    )


def blocked_valid_events() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Returns:
        Query attempting to count events for valid split critic runs
    """
    valid_transcripts = (
        select(CriticRun.transcript_id)
        .where(CriticRun.snapshot_slug.in_(select(Snapshot.slug).where(Snapshot.split == "valid")))
        .scalar_subquery()
    )

    return select(func.count()).select_from(Event).where(Event.transcript_id.in_(valid_transcripts))


# ============================================================================
# Cost tracking queries (require po_run_id parameter)
# ============================================================================


# po_run_costs query removed - see comment above
