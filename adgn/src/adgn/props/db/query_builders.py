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
from sqlalchemy import Select, bindparam, case, cast, func, literal, select, text, type_coerce, union_all
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from adgn.props.db.models import (
    CriticRun,
    Critique,
    Event,
    Example,
    FalsePositive,
    GraderRun,
    Prompt,
    PromptOptimizationRun,
    RunCost,
    Snapshot,
    TruePositive,
)
from adgn.props.ids import SnapshotSlug


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
    from sqlalchemy.dialects import postgresql

    # Cast 'null' string to JSONB type and compare
    return column != cast(literal("null"), postgresql.JSONB)


class SplitPerformanceStats(BaseModel):
    """Performance statistics for a prompt on a single split."""

    mean_recall: float
    lcb: float | None  # Lower confidence bound (NULL if n < 2)
    success_count: int
    total_count: int
    zero_pct: float
    stuck_pct: float
    context_pct: float


class PromptPerformanceRow(BaseModel):
    """Performance statistics for a single prompt across splits."""

    prompt_sha256: str
    created_at: datetime
    prompt_length: int
    valid: SplitPerformanceStats | None
    train: SplitPerformanceStats | None


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
        Query selecting grader run details with status and conditional metrics.
        - status: success or max_turns_exceeded
        - recall: NULL if max_turns_exceeded, otherwise from output
        - canonical_tp_count: NULL if max_turns_exceeded, otherwise array length
        - canonical_fp_count: NULL if max_turns_exceeded, otherwise array length
        - reported_issue_ratios: NULL if max_turns_exceeded or empty critique
    """
    return (
        select(
            GraderRun.snapshot_slug,
            GraderRun.transcript_id,
            GraderRun.output["tag"].astext.label("status"),
            # Recall is NULL if max_turns_exceeded
            case((GraderRun.output["tag"].astext == "success", GraderRun.output["recall"].astext), else_=None).label(
                "recall"
            ),
            # Count canonical TPs/FPs from array lengths (NULL if max_turns_exceeded)
            case(
                (
                    GraderRun.output["tag"].astext == "success",
                    func.jsonb_array_length(GraderRun.output["canonical_tp_coverage"]),
                ),
                else_=None,
            ).label("canonical_tp_count"),
            case(
                (
                    GraderRun.output["tag"].astext == "success",
                    func.jsonb_array_length(GraderRun.output["canonical_fp_coverage"]),
                ),
                else_=None,
            ).label("canonical_fp_count"),
            # Reported issue ratios (NULL if max_turns_exceeded or empty critique)
            case(
                (GraderRun.output["tag"].astext == "success", GraderRun.output["reported_issue_ratios"]["tp"].astext),
                else_=None,
            ).label("reported_tp_ratio"),
            case(
                (GraderRun.output["tag"].astext == "success", GraderRun.output["reported_issue_ratios"]["fp"].astext),
                else_=None,
            ).label("reported_fp_ratio"),
            GraderRun.model,
            GraderRun.created_at,
        )
        .join(Snapshot, GraderRun.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == "train")
        .where(GraderRun.output.isnot(None))
        .where(_exclude_jsonb_null(GraderRun.output))  # Exclude JSON null in addition to SQL NULL
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


def valid_metrics_select() -> Select:
    """Define the SELECT query for the valid_metrics view.

    Shows grader runs for valid split with full provenance:
    - Which critique was graded
    - How it was produced (critic prompt, model)
    - How it was graded (grader run ID, model)
    - What score it got (recall, NULL if max_turns_exceeded)
    - Status (success or max_turns_exceeded)

    Goes over all validation examples (from examples table) that have been evaluated.
    No manual file filtering - just joins with examples table to identify which
    validation examples have grader runs.

    Returns:
        Query defining the view's row structure (not aggregated)
    """
    # Join grader runs with examples table via critic_runs (snapshot_slug, files_hash)
    # Filter to validation split snapshots only
    return (
        select(
            GraderRun.snapshot_slug,
            Example.files_hash,
            GraderRun.critique_id.label("critique_id"),
            CriticRun.prompt_sha256.label("critic_prompt_sha256"),
            CriticRun.model.label("critic_model"),
            GraderRun.id.label("grader_run_id"),
            GraderRun.model.label("grader_model"),
            GraderRun.output["tag"].astext.label("status"),
            # Recall is NULL if max_turns_exceeded, otherwise extract from output
            case(
                (
                    GraderRun.output["tag"].astext == "success",
                    GraderRun.output["recall"].astext.cast(postgresql.DOUBLE_PRECISION),
                ),
                else_=None,
            ).label("recall"),
            GraderRun.created_at,
        )
        .select_from(GraderRun)
        .join(Snapshot, GraderRun.snapshot_slug == Snapshot.slug)
        .join(Critique, GraderRun.critique_id == Critique.id)
        .join(CriticRun, Critique.id == CriticRun.critique_id)
        .join(
            Example, (Example.snapshot_slug == CriticRun.snapshot_slug) & (Example.files_hash == CriticRun.files_hash)
        )
        .where(Snapshot.split == "valid")
        .where(GraderRun.output.isnot(None))
        .where(_exclude_jsonb_null(GraderRun.output))  # Exclude JSON null in addition to SQL NULL
    )


def valid_aggregates_view() -> Select:
    """Get aggregate grader metrics for valid split (from view).

    Returns:
        Query selecting avg_recall, snapshot_count, run_count, grader_model
    """
    # This queries the valid_metrics view
    # We use text() to reference the view since it's not mapped as an ORM model
    return (
        select(
            text("AVG(recall) as avg_recall"),
            text("COUNT(DISTINCT snapshot_slug) as snapshot_count"),
            text("COUNT(*) as run_count"),
            text("grader_model"),
        )
        .select_from(text("valid_metrics"))
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
        Query selecting grader_run_id, snapshot_slug, status, recall (NULL if max_turns_exceeded),
        critique_id, critic_run_id, prompt_sha256, prompt_text
    """
    return (
        select(
            GraderRun.id.label("grader_run_id"),
            GraderRun.snapshot_slug,
            GraderRun.output["tag"].astext.label("status"),
            # Recall is NULL if max_turns_exceeded
            case((GraderRun.output["tag"].astext == "success", GraderRun.output["recall"].astext), else_=None).label(
                "recall"
            ),
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
        .where(_exclude_jsonb_null(GraderRun.output))  # Exclude JSON null in addition to SQL NULL
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
# Scope queries
# ============================================================================


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


def grader_runs_by_scope_train(limit: int = 10) -> Select:
    """Count completed grader runs per example for train split.

    Returns grader runs grouped by (snapshot_slug, files_hash) to show
    how many times each example has been evaluated.

    Args:
        limit: Maximum number of results (default 10)

    Returns:
        Query selecting (snapshot_slug, files_hash, run_count, avg_recall, success_count)
        ordered by run_count descending.
        avg_recall only includes successful runs (status='success'), not max_turns_exceeded.
    """
    return (
        select(
            GraderRun.snapshot_slug,
            Example.files_hash,
            Example.files,
            func.count().label("run_count"),
            # Average recall only for successful runs (where tag='success')
            func.avg(
                case(
                    (
                        GraderRun.output["tag"].astext == "success",
                        GraderRun.output["recall"].astext.cast(postgresql.DOUBLE_PRECISION),
                    ),
                    else_=None,
                )
            ).label("avg_recall"),
            # Count successful runs (status='success')
            func.sum(case((GraderRun.output["tag"].astext == "success", 1), else_=0)).label("success_count"),
        )
        .select_from(GraderRun)
        .join(Snapshot, GraderRun.snapshot_slug == Snapshot.slug)
        .join(Critique, GraderRun.critique_id == Critique.id)
        .join(CriticRun, Critique.id == CriticRun.critique_id)
        # Join examples by matching files_hash (critic_runs.files matches example.files via hash)
        .join(
            Example, (CriticRun.snapshot_slug == Example.snapshot_slug) & (CriticRun.files_hash == Example.files_hash)
        )
        .where(Snapshot.split == "train")
        .where(GraderRun.output.isnot(None))
        .where(_exclude_jsonb_null(GraderRun.output))  # Exclude JSON null in addition to SQL NULL
        .group_by(GraderRun.snapshot_slug, Example.files_hash, Example.files)
        .order_by(func.count().desc())
        .limit(limit)
    )


# ============================================================================
# Prompt performance queries
# ============================================================================


def query_prompt_performance_stats(session: Session, limit: int = 50) -> list[PromptPerformanceRow]:
    """Query comprehensive prompt performance statistics across train/valid splits.

    For each prompt, computes:
    - Mean recall (over all runs, failures count as 0.0)
    - Success/total counts (successful runs vs all runs)
    - Zero%: percentage of successful runs with 0% recall
    - Stuck%: percentage of all runs that exceeded max_turns
    - Context%: percentage of all runs that exceeded context_length

    IMPORTANT: max_turns_exceeded/context_exceeded are taken as recall=0.0 in mean calculation.
    Example: 4 successful (25% recall each) + 1 stuck = 20% mean recall.
    See lines 803-806: CASE WHEN status='success' THEN recall ELSE 0.0 END

    Args:
        session: SQLAlchemy session
        limit: Maximum number of prompts to return (default 50, most recent)

    Returns:
        List of PromptPerformanceRow models with split statistics
    """
    # Use text() for the complex CTE-based query
    # This matches the query from query_train_vs_valid_performance.py
    query_text = text("""
        WITH latest_grader_per_example AS (
            -- Get most recent grader run per (prompt, example, split)
            SELECT DISTINCT ON (cr.prompt_sha256, cr.snapshot_slug, cr.files_hash)
                cr.prompt_sha256,
                cr.snapshot_slug,
                cr.files_hash,
                s.split,
                gr.output->>'tag' as status,
                CASE
                    WHEN gr.output->>'tag' = 'success' THEN (gr.output->'recall')::float
                    ELSE 0.0
                END as recall,
                gr.created_at
            FROM grader_runs gr
            JOIN critiques c ON gr.critique_id = c.id
            JOIN critic_runs cr ON cr.critique_id = c.id
            JOIN examples e ON e.snapshot_slug = cr.snapshot_slug AND e.files_hash = cr.files_hash
            JOIN snapshots s ON s.slug = cr.snapshot_slug
            WHERE s.split IN ('train', 'valid')
            ORDER BY cr.prompt_sha256, cr.snapshot_slug, cr.files_hash, gr.created_at DESC
        ),
        split_stats AS (
            -- Aggregate statistics per (prompt, split)
            SELECT
                prompt_sha256,
                split,
                AVG(recall) * 100 as mean_recall,
                -- Lower confidence bound: mean - 1.0 * (stddev / sqrt(n))
                -- NULL if n < 2 (can't compute stddev with single sample)
                CASE
                    WHEN COUNT(*) >= 2 THEN
                        AVG(recall) * 100 - 1.0 * (STDDEV_SAMP(recall) * 100 / SQRT(COUNT(*)))
                    ELSE NULL
                END as recall_lcb,
                COUNT(*) as total_count,
                COUNT(CASE WHEN status = 'success' THEN 1 END) as success_count,
                SUM(CASE WHEN status = 'success' AND recall = 0.0 THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(CASE WHEN status = 'success' THEN 1 END), 0) * 100 as zero_pct,
                SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::float / COUNT(*) * 100 as stuck_pct,
                SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::float / COUNT(*) * 100 as context_pct
            FROM latest_grader_per_example
            GROUP BY prompt_sha256, split
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
            v.zero_pct as valid_zero_pct,
            v.stuck_pct as valid_stuck_pct,
            v.context_pct as valid_context_pct,
            t.mean_recall as train_recall,
            t.recall_lcb as train_lcb,
            t.success_count as train_success,
            t.total_count as train_total,
            t.zero_pct as train_zero_pct,
            t.stuck_pct as train_stuck_pct,
            t.context_pct as train_context_pct
        FROM prompt_info p
        LEFT JOIN split_stats v ON v.prompt_sha256 = p.prompt_sha256 AND v.split = 'valid'
        LEFT JOIN split_stats t ON t.prompt_sha256 = p.prompt_sha256 AND t.split = 'train'
        ORDER BY
            v.recall_lcb DESC NULLS LAST,  -- Primary: valid LCB (descending)
            t.recall_lcb DESC NULLS LAST,  -- Secondary: train LCB (descending)
            p.created_at DESC              -- Tertiary: creation time (tiebreaker)
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
                zero_pct=row.valid_zero_pct or 0.0,
                stuck_pct=row.valid_stuck_pct or 0.0,
                context_pct=row.valid_context_pct or 0.0,
            )

        # Build train stats if data exists
        train_stats = None
        if row.train_recall is not None:
            train_stats = SplitPerformanceStats(
                mean_recall=row.train_recall,
                lcb=row.train_lcb,  # NULL if n < 2
                success_count=row.train_success,
                total_count=row.train_total,
                zero_pct=row.train_zero_pct or 0.0,
                stuck_pct=row.train_stuck_pct or 0.0,
                context_pct=row.train_context_pct or 0.0,
            )

        rows.append(
            PromptPerformanceRow(
                prompt_sha256=row.prompt_sha256,
                created_at=row.created_at,
                prompt_length=row.prompt_length,
                valid=valid_stats,
                train=train_stats,
            )
        )

    return rows
