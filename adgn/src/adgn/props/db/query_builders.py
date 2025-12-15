"""SQLAlchemy query builders for agent-accessible database queries.

Each function returns a SQLAlchemy Select object that can be:
- Executed directly in tests: session.execute(query).fetchall()
- Compiled to SQL string for j2 templates: compile_to_sql(query)

This provides a single source of truth for query structure, eliminating duplication
between test execution and template injection.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, bindparam, cast, func, literal, select, text, type_coerce, union_all
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from adgn.props.db.models import (
    CriticRun,
    Critique,
    Event,
    Example,
    FalsePositive,
    GraderRun,
    OccurrenceCredit,
    PromptOptimizationRun,
    RunCost,
    Snapshot,
    TruePositive,
)
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split


def _exclude_jsonb_null(column):
    """Helper to exclude JSON null values from JSONB columns.

    PydanticColumn stores Python None as JSON null ('null'::jsonb), not SQL NULL.
    SQLAlchemy's .isnot(None) only excludes SQL NULL, so JSON null rows pass through
    and crash when deserialized to Python None.

    Usage:
        .where(GraderRun.output.isnot(None))  # Excludes SQL NULL
        .where(_exclude_jsonb_null(GraderRun.output))  # Excludes JSON null

    Args:
        column: SQLAlchemy column expression (e.g., GraderRun.output)

    Returns:
        SQLAlchemy binary expression: column != cast('null', JSONB)
    """
    # Cast 'null' string to JSONB type and compare
    return column != cast(literal("null"), postgresql.JSONB)


class SplitPerformanceStats(BaseModel):
    """Performance statistics for a prompt on a single split."""

    mean_recall: float
    lcb: float | None  # Lower confidence bound (NULL if n < 2)
    success_count: int
    total_count: int
    zero_count: int  # Number of examples with 0.0 recall
    stuck_count: int  # Total runs that exceeded max_turns
    context_count: int  # Total runs that exceeded context_length


class PromptPerformanceRow(BaseModel):
    """Performance statistics for a single prompt across splits."""

    prompt_sha256: str
    created_at: datetime
    prompt_length: int
    valid: SplitPerformanceStats | None
    train_whole: SplitPerformanceStats | None
    train_partial: SplitPerformanceStats | None


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


# TODO: Consider removing - compiled but never rendered in template, agents can query directly
def list_train_snapshots() -> Select:
    """List all train split snapshots.

    Returns:
        Query selecting (slug, split) from train snapshots, ordered by slug
    """
    return select(Snapshot.slug, Snapshot.split).where(Snapshot.split == "train").order_by(Snapshot.slug)


# TODO: Consider removing - no usages found anywhere
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


# TODO: Consider removing - no usages found anywhere
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


# TODO: Consider removing - no usages found anywhere
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


# TODO: Consider removing - compiled but never rendered in template, agents can query directly
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


# TODO: Consider removing - compiled but never rendered in template, agents can query directly
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
    which may be filtered by temporary agent users (e.g., TRAIN-only for prompt optimizer).
    We also join with snapshots to ensure snapshot_slug is valid.

    Returns:
        Query selecting snapshot_slug and files_with_issues (text array) for each snapshot
    """
    # Extract all file paths (dict keys) from TP occurrences
    # true_positives.occurrences is JSONB array of {files: {...}, ...}
    # RLS on true_positives applies task-specific filtering for temporary agent users
    tp_files = select(
        TruePositive.snapshot_slug,
        func.jsonb_object_keys(func.jsonb_array_elements(TruePositive.occurrences).op("->")(literal("files"))).label(
            "file_path"
        ),
    ).select_from(TruePositive)

    # Extract all file paths from FP occurrences
    # RLS on false_positives applies task-specific filtering for temporary agent users
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


# ============================================================================
# Critique queries
# ============================================================================


# TODO: Consider removing - no usages found (only parameterized version compiled)
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


# ============================================================================
# Event trajectory queries (require transcript_id parameter)
# ============================================================================


# TODO: Consider removing - no usages found (only parameterized version compiled)
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


# TODO: Consider removing - no usages found (only parameterized version compiled)
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


# TODO: Consider removing - no usages found (only parameterized version compiled)
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


# TODO: Consider removing - compiled but never rendered in template
def critiques_for_snapshot_parameterized() -> Select:
    """Get critiques for a snapshot (parameterized with :snapshot_slug placeholder).

    Agents fill in :snapshot_slug at runtime.
    """
    return critiques_for_snapshot(bindparam("snapshot_slug"), limit=5)  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
def tools_used_by_transcript_parameterized() -> Select:
    """Tool usage by transcript (parameterized with :transcript_id placeholder).

    Agents fill in :transcript_id at runtime.
    """
    return tools_used_by_transcript(bindparam("transcript_id"))  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
def tool_sequence_by_transcript_parameterized() -> Select:
    """Tool sequence by transcript (parameterized with :transcript_id placeholder).

    Agents fill in :transcript_id at runtime.
    """
    return tool_sequence_by_transcript(bindparam("transcript_id"))  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
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
    # CTE for PO transcripts (critic runs, grader runs, and PO agent's own transcript)
    critic_transcripts = select(
        CriticRun.transcript_id, CriticRun.snapshot_slug, literal("critic").label("run_type"), CriticRun.created_at
    ).where(CriticRun.prompt_optimization_run_id == po_run_id)

    grader_transcripts = select(
        GraderRun.transcript_id, GraderRun.snapshot_slug, literal("grader").label("run_type"), GraderRun.created_at
    ).where(GraderRun.prompt_optimization_run_id == po_run_id)

    po_agent_transcript = select(
        PromptOptimizationRun.transcript_id,
        literal(None).label("snapshot_slug"),  # PO agent doesn't target a specific snapshot
        literal("prompt_optimizer").label("run_type"),
        PromptOptimizationRun.created_at,
    ).where(PromptOptimizationRun.id == po_run_id)

    po_transcripts = union_all(critic_transcripts, grader_transcripts, po_agent_transcript).cte("po_transcripts")

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


# TODO: Consider removing - no usages found (only non-param version used)
def po_run_costs_parameterized() -> Select:
    """PO run costs (parameterized with :po_run_id placeholder).

    Agents fill in :po_run_id at runtime.
    """
    return po_run_costs(bindparam("po_run_id"))  # type: ignore[arg-type]


# ============================================================================
# RLS blocked queries (examples showing what's blocked by RLS)
# ============================================================================


# TODO: Consider removing - compiled but never rendered in template
def blocked_valid_critiques() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Returns:
        Query attempting to select critiques for valid split snapshots
    """
    return select(Critique.id, Critique.payload).where(
        Critique.snapshot_slug.in_(select(Snapshot.slug).where(Snapshot.split == "valid"))
    )


# TODO: Consider removing - compiled but never rendered in template
def blocked_valid_grader_runs() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Returns:
        Query attempting to select grader runs for valid split snapshots
    """
    return select(GraderRun.id, GraderRun.output).where(
        GraderRun.snapshot_slug.in_(select(Snapshot.slug).where(Snapshot.split == "valid"))
    )


# TODO: Consider removing - compiled but never rendered in template
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
# Scope queries
# ============================================================================


# TODO: Consider removing - compiled but never rendered in template
def list_train_scopes() -> Select:
    """List all examples for train split snapshots.

    Returns:
        Query selecting (snapshot_slug, files_hash, files) for train snapshots
    """
    return (
        select(Example.snapshot_slug, Example.files_hash, Example.files)
        .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == "train")
        .order_by(Example.snapshot_slug, Example.files_hash)
    )


# ============================================================================
# Prompt performance queries
# ============================================================================


def query_prompt_performance_stats(session: Session, limit: int = 50) -> list[PromptPerformanceRow]:
    """Query comprehensive prompt performance statistics across train/valid splits.

    For each prompt, computes:
    - Mean recall (over all examples, computed from occurrence credits like the view)
    - LCB (Lower Confidence Bound): mean - stddev/sqrt(n) for ranking prompts
    - Success/total counts (successful runs vs all runs including failures)
    - Zero%: percentage of examples with 0.0 recall
    - Stuck%: percentage of runs that exceeded max_turns
    - Context%: percentage of runs that exceeded context_length

    Train split is further divided into whole-snapshot and partial examples.

    Uses occurrence_credits view as data source (includes failed runs via UNION).
    Recall computation matches aggregated_recall_by_prompt view exactly.

    Args:
        session: SQLAlchemy session
        limit: Maximum number of prompts to return (default 50, most recent)

    Returns:
        List of PromptPerformanceRow models with split statistics
    """
    # Use text() for the complex CTE-based query
    # Data source: occurrence_credits view (includes failures with zero credit)
    query_text = text("""
        WITH per_example_recall AS (
            -- Compute recall per (prompt, example) - same math as aggregated_recall_by_prompt view
            -- First: average credits per occurrence across runs
            -- Then: sum occurrence averages and divide by count
            SELECT
                prompt_sha256,
                split,
                is_whole_snapshot,
                snapshot_slug,
                files_hash,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                COUNT(DISTINCT critic_run_id) as n_critic_runs,
                COUNT(DISTINCT CASE
                    WHEN grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%'
                    THEN critic_run_id
                END) as n_max_turns,
                COUNT(DISTINCT CASE
                    WHEN grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%'
                    THEN critic_run_id
                END) as n_context
            FROM (
                SELECT
                    prompt_sha256,
                    split,
                    is_whole_snapshot,
                    snapshot_slug,
                    files_hash,
                    tp_id,
                    occurrence_id,
                    critic_run_id,
                    grader_run_id,
                    grader_rationale,
                    AVG(found_credit) as avg_credit
                FROM occurrence_credits
                WHERE split = 'train' OR (split = 'valid' AND is_whole_snapshot = TRUE)
                GROUP BY prompt_sha256, split, is_whole_snapshot, snapshot_slug, files_hash,
                         tp_id, occurrence_id, critic_run_id, grader_run_id, grader_rationale
            ) occurrence_avg
            GROUP BY prompt_sha256, split, is_whole_snapshot, snapshot_slug, files_hash
        ),
        split_stats AS (
            -- Aggregate statistics per (prompt, split, is_whole_snapshot)
            SELECT
                prompt_sha256,
                split,
                is_whole_snapshot,
                AVG(recall) * 100 as mean_recall,
                -- Lower confidence bound: mean - 1.0 * (stddev / sqrt(n))
                -- NULL if n < 2 (can't compute stddev with single sample)
                CASE
                    WHEN COUNT(*) >= 2 THEN
                        AVG(recall) * 100 - 1.0 * (STDDEV_SAMP(recall) * 100 / SQRT(COUNT(*)))
                    ELSE NULL
                END as recall_lcb,
                COUNT(*) as total_count,
                -- Success count: examples with at least one successful run (has grader_run_id)
                COUNT(CASE WHEN n_critic_runs > n_max_turns + n_context THEN 1 END) as success_count,
                -- Zero count: number of examples with 0.0 recall
                SUM(CASE WHEN recall = 0.0 THEN 1 ELSE 0 END) as zero_count,
                -- Stuck count: total runs that exceeded max_turns
                SUM(n_max_turns) as stuck_count,
                -- Context count: total runs that exceeded context
                SUM(n_context) as context_count
            FROM per_example_recall
            GROUP BY prompt_sha256, split, is_whole_snapshot
        ),
        prompt_info AS (
            -- Get prompt metadata
            SELECT
                prompt_sha256,
                created_at,
                LENGTH(prompt_text) as prompt_length
            FROM prompts
        )
        SELECT
            p.prompt_sha256,
            p.created_at,
            p.prompt_length,
            v.mean_recall as valid_recall,
            v.recall_lcb as valid_lcb,
            v.success_count as valid_success,
            v.total_count as valid_total,
            v.zero_count as valid_zero_count,
            v.stuck_count as valid_stuck_count,
            v.context_count as valid_context_count,
            tw.mean_recall as train_whole_recall,
            tw.recall_lcb as train_whole_lcb,
            tw.success_count as train_whole_success,
            tw.total_count as train_whole_total,
            tw.zero_count as train_whole_zero_count,
            tw.stuck_count as train_whole_stuck_count,
            tw.context_count as train_whole_context_count,
            tp.mean_recall as train_partial_recall,
            tp.recall_lcb as train_partial_lcb,
            tp.success_count as train_partial_success,
            tp.total_count as train_partial_total,
            tp.zero_count as train_partial_zero_count,
            tp.stuck_count as train_partial_stuck_count,
            tp.context_count as train_partial_context_count
        FROM prompt_info p
        LEFT JOIN split_stats v ON v.prompt_sha256 = p.prompt_sha256 AND v.split = 'valid'
        LEFT JOIN split_stats tw ON tw.prompt_sha256 = p.prompt_sha256 AND tw.split = 'train' AND tw.is_whole_snapshot = TRUE
        LEFT JOIN split_stats tp ON tp.prompt_sha256 = p.prompt_sha256 AND tp.split = 'train' AND tp.is_whole_snapshot = FALSE
        ORDER BY
            v.recall_lcb DESC NULLS LAST,   -- Primary: valid LCB (descending)
            tw.recall_lcb DESC NULLS LAST,  -- Secondary: train whole LCB (descending)
            tp.recall_lcb DESC NULLS LAST,  -- Tertiary: train partial LCB (descending)
            p.created_at DESC               -- Quaternary: creation time (tiebreaker)
        LIMIT :limit
    """)

    results = session.execute(query_text, {"limit": limit}).fetchall()

    # Convert to Pydantic models
    rows = []
    for row in results:
        # Build valid stats if data exists
        valid_stats = None
        if row.valid_recall is not None:
            valid_stats = SplitPerformanceStats(
                mean_recall=row.valid_recall,
                lcb=row.valid_lcb,  # NULL if n < 2
                success_count=row.valid_success,
                total_count=row.valid_total,
                zero_count=row.valid_zero_count or 0,
                stuck_count=row.valid_stuck_count or 0,
                context_count=row.valid_context_count or 0,
            )

        # Build train whole-snapshot stats if data exists
        train_whole_stats = None
        if row.train_whole_recall is not None:
            train_whole_stats = SplitPerformanceStats(
                mean_recall=row.train_whole_recall,
                lcb=row.train_whole_lcb,  # NULL if n < 2
                success_count=row.train_whole_success,
                total_count=row.train_whole_total,
                zero_count=row.train_whole_zero_count or 0,
                stuck_count=row.train_whole_stuck_count or 0,
                context_count=row.train_whole_context_count or 0,
            )

        # Build train partial stats if data exists
        train_partial_stats = None
        if row.train_partial_recall is not None:
            train_partial_stats = SplitPerformanceStats(
                mean_recall=row.train_partial_recall,
                lcb=row.train_partial_lcb,  # NULL if n < 2
                success_count=row.train_partial_success,
                total_count=row.train_partial_total,
                zero_count=row.train_partial_zero_count or 0,
                stuck_count=row.train_partial_stuck_count or 0,
                context_count=row.train_partial_context_count or 0,
            )

        rows.append(
            PromptPerformanceRow(
                prompt_sha256=row.prompt_sha256,
                created_at=row.created_at,
                prompt_length=row.prompt_length,
                valid=valid_stats,
                train_whole=train_whole_stats,
                train_partial=train_partial_stats,
            )
        )

    return rows


# ============================================================================
# Recall by Example Queries (Occurrence-Weighted)
# ============================================================================


class RecallByExampleRow(BaseModel):
    """Single row from recall-by-example query."""

    snapshot_slug: SnapshotSlug
    files_hash: str | None
    prompt_sha256: str
    recall: float


def query_recall_by_example(
    session: Session,
    split: Split | None = None,
    prompt_sha256: str | None = None,
    snapshot_slugs: list[SnapshotSlug] | None = None,
) -> list[RecallByExampleRow]:
    """Query occurrence-weighted recall grouped by (example, prompt).

    Computes AVG(found_credit) from occurrence_credits view, grouped by
    (snapshot_slug, files_hash, prompt_sha256).

    This is the canonical way to compute recall for cross-run aggregation.
    Single-run recall can be computed inline from occurrence_results.

    Args:
        session: SQLAlchemy session
        split: Optional split filter (TRAIN, VALID, TEST)
        prompt_sha256: Optional prompt filter (get recall for specific prompt)
        snapshot_slugs: Optional list of snapshot slugs to filter

    Returns:
        List of RecallByExampleRow (snapshot, files_hash, prompt, recall)

    Example:
        # Get recall for all train examples with a specific prompt
        results = query_recall_by_example(
            session,
            split=Split.TRAIN,
            prompt_sha256="abc123..."
        )
        for row in results:
            print(f"{row.snapshot_slug}: {row.recall * 100:.1f}%")
    """
    query = session.query(
        OccurrenceCredit.snapshot_slug,
        OccurrenceCredit.files_hash,
        OccurrenceCredit.prompt_sha256,
        func.avg(OccurrenceCredit.found_credit).label("recall"),
    )

    if split is not None:
        query = query.filter(OccurrenceCredit.split == split)
    if prompt_sha256 is not None:
        query = query.filter(OccurrenceCredit.prompt_sha256 == prompt_sha256)
    if snapshot_slugs is not None:
        query = query.filter(OccurrenceCredit.snapshot_slug.in_(snapshot_slugs))

    query = query.group_by(OccurrenceCredit.snapshot_slug, OccurrenceCredit.files_hash, OccurrenceCredit.prompt_sha256)

    results = query.all()
    return [
        RecallByExampleRow(
            snapshot_slug=SnapshotSlug(r.snapshot_slug),
            files_hash=r.files_hash,
            prompt_sha256=r.prompt_sha256,
            recall=r.recall,
        )
        for r in results
    ]


# ============================================================================
# Cross-Run Aggregated Recall (Database Views)
# ============================================================================
#
# Use ORM models to query the database views directly:
#
# Example 1: Query aggregated_recall_by_prompt view
#   from adgn.props.db.models import AggregatedRecallByPrompt
#   from adgn.props.splits import Split
#
#   result = session.query(AggregatedRecallByPrompt).filter(
#       AggregatedRecallByPrompt.split == Split.TRAIN,
#       AggregatedRecallByPrompt.critic_model == "gpt-4o",
#       AggregatedRecallByPrompt.is_whole_snapshot == False,
#   ).first()
#
#   if result:
#       print(f"Recall: {result.recall}, Total credit: {result.total_credit}, Occurrences: {result.n_occurrences}")
#
# Example 2: Query aggregated_recall_by_example view
#   from adgn.props.db.models import AggregatedRecallByExample
#
#   results = session.query(AggregatedRecallByExample).filter(
#       AggregatedRecallByExample.split == Split.TRAIN,
#       AggregatedRecallByExample.critic_model == "gpt-4o",
#   ).all()
#
# Example 3: Query occurrence_statistics view
#   from adgn.props.db.models import OccurrenceStatistics
#
#   stats = session.query(OccurrenceStatistics).filter(
#       OccurrenceStatistics.split == Split.TRAIN,
#       OccurrenceStatistics.full_catch_rate > 0.8,
#   ).order_by(OccurrenceStatistics.mean_credit.desc()).all()
#
# The views handle all JSONB extraction and aggregation logic.
# No separate query builder functions are needed.
