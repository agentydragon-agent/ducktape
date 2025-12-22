"""SQLAlchemy query builders for agent-accessible database queries.

Each function returns a SQLAlchemy Select object that can be:
- Executed directly in tests: session.execute(query).fetchall()
- Compiled to SQL string for j2 templates: compile_to_sql(query)

This provides a single source of truth for query structure, eliminating duplication
between test execution and template injection.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, bindparam, cast, func, literal, select, text, type_coerce, union_all
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from adgn.props.agent_types import AgentType
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun, Event, FalsePositive, OccurrenceCredit, RunCost, Snapshot, TruePositive
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split


class SplitPerformanceStats(BaseModel):
    """Performance statistics for a prompt on a single split."""

    mean_recall: float
    lcb: float | None  # Lower confidence bound (NULL if n < 2)
    success_count: int
    total_count: int
    zero_count: int  # Number of examples with 0.0 recall
    stuck_count: int  # Total runs that exceeded max_turns
    context_count: int  # Total runs that exceeded context_length


class DefinitionPerformanceRow(BaseModel):
    """Performance statistics for a single agent definition across splits."""

    agent_definition_id: str
    created_at: datetime
    # Map from (split, scope_kind) to statistics
    # Keys: (Split.VALID, 'entire_snapshot'), (Split.VALID, 'specific_files'), etc.
    stats: dict[tuple[Split, str], SplitPerformanceStats]


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
        SQL string with placeholders like :agent_run_id, :snapshot_slug

    Example:
        >>> q = select(Event).where(Event.agent_run_id == bindparam('agent_run_id'))
        >>> compile_to_sql_with_placeholders(q)
        'SELECT ... WHERE agent_run_id = :agent_run_id'
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
    return select(Snapshot.slug, Snapshot.split).where(Snapshot.split == Split.TRAIN).order_by(Snapshot.slug)


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
        .join(TruePositive.snapshot_obj)
        .where(Snapshot.split == Split.TRAIN)
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
        .join(FalsePositive.snapshot_obj)
        .where(Snapshot.split == Split.TRAIN)
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
# Critic run queries
# ============================================================================


# TODO: Consider removing - no usages found (only parameterized version compiled)
def critic_runs_for_snapshot(snapshot_slug: SnapshotSlug, limit: int = 5) -> Select:
    """Get recent critic agent runs for a specific snapshot.

    Uses AgentRun with JSONB filtering on type_config->>'agent_type' = 'critic'
    and type_config->>'snapshot_slug' = snapshot_slug.

    Args:
        snapshot_slug: Snapshot to query
        limit: Maximum number of results (default 5)

    Returns:
        Query selecting agent run details for critic runs
    """
    return (
        select(
            AgentRun.agent_run_id,
            AgentRun.status,
            AgentRun.created_at,
            AgentRun.model,
            AgentRun.type_config["scope_hash"].astext.label("scope_hash"),
        )
        .where(
            AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
            AgentRun.type_config["snapshot_slug"].astext == snapshot_slug,  # type: ignore[arg-type]
        )
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )


# ============================================================================
# Event trajectory queries (require agent_run_id parameter)
# ============================================================================


# TODO: Consider removing - no usages found (only parameterized version compiled)
def tools_used_by_agent_run(agent_run_id: UUID) -> Select:
    """Count tool usage by name for a given agent run.

    Args:
        agent_run_id: Agent run UUID to query

    Returns:
        Query selecting (tool_name, count) ordered by count descending
    """
    return (
        select(Event.payload["name"].astext.label("tool_name"), func.count().label("count"))
        .where(Event.agent_run_id == agent_run_id, Event.event_type == "tool_call")
        .group_by(Event.payload["name"].astext)
        .order_by(func.count().desc())
    )


# TODO: Consider removing - no usages found (only parameterized version compiled)
def tool_sequence_by_agent_run(agent_run_id: UUID) -> Select:
    """Get tool call sequence for an agent run.

    Args:
        agent_run_id: Agent run UUID to query

    Returns:
        Query selecting (sequence_num, timestamp, tool_name) ordered by sequence
    """
    return (
        select(Event.sequence_num, Event.timestamp, Event.payload["name"].astext.label("tool_name"))
        .where(Event.agent_run_id == agent_run_id, Event.event_type == "tool_call")
        .order_by(Event.sequence_num)
    )


# TODO: Consider removing - no usages found (only parameterized version compiled)
def failed_tools_by_agent_run(agent_run_id: UUID) -> Select:
    """Get failed tool calls for an agent run.

    Args:
        agent_run_id: Agent run UUID to query

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
            (e1.c.agent_run_id == e2.c.agent_run_id)
            & (e1.c.payload["call_id"].astext == e2.c.payload["call_id"].astext),
        )
        .where(
            e1.c.agent_run_id == agent_run_id,
            e1.c.event_type == "tool_call",
            e2.c.event_type == "function_call_output",
            cast(e2.c.payload["result"]["isError"].astext, postgresql.BOOLEAN),
        )
    )


# ============================================================================
# Parameterized query builders (for agent-side parameter substitution)
# ============================================================================


# TODO: Consider removing - compiled but never rendered in template
def critic_runs_for_snapshot_parameterized() -> Select:
    """Get critic runs for a snapshot (parameterized with :snapshot_slug placeholder).

    Agents fill in :snapshot_slug at runtime.
    """
    return critic_runs_for_snapshot(bindparam("snapshot_slug"), limit=5)  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
def tools_used_by_agent_run_parameterized() -> Select:
    """Tool usage by agent run (parameterized with :agent_run_id placeholder).

    Agents fill in :agent_run_id at runtime.
    """
    return tools_used_by_agent_run(bindparam("agent_run_id"))  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
def tool_sequence_by_agent_run_parameterized() -> Select:
    """Tool sequence by agent run (parameterized with :agent_run_id placeholder).

    Agents fill in :agent_run_id at runtime.
    """
    return tool_sequence_by_agent_run(bindparam("agent_run_id"))  # type: ignore[arg-type]


# TODO: Consider removing - compiled but never rendered in template
def failed_tools_by_agent_run_parameterized() -> Select:
    """Failed tools by agent run (parameterized with :agent_run_id placeholder).

    Agents fill in :agent_run_id at runtime.
    """
    return failed_tools_by_agent_run(bindparam("agent_run_id"))  # type: ignore[arg-type]


def po_run_costs(po_run_id: UUID) -> Select:
    """Get per-run costs and totals for a prompt optimization run.

    Uses AgentRun with JSONB filtering to find all child runs (critics, graders)
    of a prompt optimizer agent run.

    Args:
        po_run_id: Prompt optimization agent run UUID (agent_run_id)

    Returns:
        Query selecting transcript details with cost/token metrics from run_costs view
    """
    # CTE for PO transcripts (all child agent runs + the PO agent's own run)
    # Child runs have parent_agent_run_id = po_run_id
    child_runs = select(
        AgentRun.agent_run_id,
        AgentRun.type_config["snapshot_slug"].astext.label("snapshot_slug"),
        AgentRun.type_config["agent_type"].astext.label("run_type"),
        AgentRun.created_at,
    ).where(AgentRun.parent_agent_run_id == po_run_id)

    # The PO agent's own run
    po_agent_run = select(
        AgentRun.agent_run_id,
        literal(None).label("snapshot_slug"),  # PO agent doesn't target a specific snapshot
        literal("prompt_optimizer").label("run_type"),
        AgentRun.created_at,
    ).where(AgentRun.agent_run_id == po_run_id)

    po_runs = union_all(child_runs, po_agent_run).cte("po_runs")

    # Main query joining with run_costs view (mapped as RunCost ORM model)
    # Note: RunCost.agent_run_id references agent_run_id
    return (
        select(
            po_runs.c.agent_run_id,
            po_runs.c.snapshot_slug,
            po_runs.c.run_type,
            RunCost.model,
            func.sum(RunCost.cost_usd).label("cost_usd"),
            func.sum(RunCost.input_tokens).label("input_tokens"),
            func.sum(RunCost.cached_tokens).label("cached_tokens"),
            func.sum(RunCost.output_tokens).label("output_tokens"),
            po_runs.c.created_at,
        )
        .select_from(po_runs)
        .join(RunCost, po_runs.c.agent_run_id == RunCost.agent_run_id)
        .group_by(
            po_runs.c.agent_run_id, po_runs.c.snapshot_slug, po_runs.c.run_type, RunCost.model, po_runs.c.created_at
        )
        .order_by(po_runs.c.created_at.desc())
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
def blocked_valid_grader_runs() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Uses AgentRun with JSONB filtering for grader agent type.
    Note: Graders derive snapshot_slug from the graded critic's type_config.

    Returns:
        Query attempting to select grader agent runs for valid split snapshots
    """
    # Grader runs: get snapshot_slug from the graded critic via a subquery
    # graded_agent_run_id -> lookup critic's type_config->>'snapshot_slug'
    graded_critic_snapshot = (
        select(AgentRun.type_config["snapshot_slug"].astext)
        .where(AgentRun.agent_run_id == func.cast(AgentRun.type_config["graded_agent_run_id"].astext, postgresql.UUID))
        .correlate(AgentRun)
        .scalar_subquery()
    )

    return select(AgentRun.agent_run_id, AgentRun.status).where(
        AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
        graded_critic_snapshot.in_(select(Snapshot.slug).where(Snapshot.split == Split.VALID)),
    )


# TODO: Consider removing - compiled but never rendered in template
def blocked_valid_events() -> Select:
    """Example query that returns 0 rows due to RLS (valid split blocked).

    Uses AgentRun with JSONB filtering to find critic runs for valid split.

    Returns:
        Query attempting to count events for valid split critic agent runs
    """
    valid_agent_run_ids = (
        select(AgentRun.agent_run_id)
        .where(
            AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
            AgentRun.type_config["snapshot_slug"].astext.in_(
                select(Snapshot.slug).where(Snapshot.split == Split.VALID)
            ),
        )
        .scalar_subquery()
    )

    # Events reference agent_run_id
    return select(func.count()).select_from(Event).where(Event.agent_run_id.in_(valid_agent_run_ids))


# ============================================================================
# Scope queries
# ============================================================================


# TODO: Consider removing - compiled but never rendered in template
def list_train_scopes() -> Select:
    """List all examples for train split snapshots.

    Returns:
        Query selecting (snapshot_slug, scope_hash) for train snapshots
    """
    return (
        select(Example.snapshot_slug, Example.scope_hash)
        .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
        .where(Snapshot.split == Split.TRAIN)
        .order_by(Example.snapshot_slug, Example.scope_hash)
    )


# ============================================================================
# Definition performance queries
# ============================================================================


def query_definition_performance_stats(session: Session, limit: int = 50) -> list[DefinitionPerformanceRow]:
    """Query comprehensive agent definition performance statistics across train/valid splits.

    For each agent definition, computes:
    - Mean recall (over all examples, computed from occurrence credits like the view)
    - LCB (Lower Confidence Bound): mean - stddev/sqrt(n) for ranking definitions
    - Success/total counts (successful runs vs all runs including failures)
    - Zero%: percentage of examples with 0.0 recall
    - Stuck%: percentage of runs that exceeded max_turns
    - Context%: percentage of runs that exceeded context_length

    Train split is further divided into whole-snapshot and partial examples.

    Uses occurrence_credits view as data source (includes failed runs via UNION).
    Recall computation matches aggregated_recall_by_definition view exactly.

    Args:
        session: SQLAlchemy session
        limit: Maximum number of definitions to return (default 50, most recent)

    Returns:
        List of PromptPerformanceRow models with split statistics
    """
    # Use text() for the complex CTE-based query
    # Data source: occurrence_credits view (includes failures with zero credit)
    query_text = text(
        """
        WITH per_example_recall AS (
            -- Compute recall per (definition, example) - same math as aggregated_recall_by_definition view
            -- First: average credits per occurrence across runs
            -- Then: sum occurrence averages and divide by count
            SELECT
                agent_definition_id,
                split,
                scope_kind,
                snapshot_slug,
                scope_hash,
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
                    agent_definition_id,
                    split,
                    scope_kind,
                    snapshot_slug,
                    scope_hash,
                    tp_id,
                    occurrence_id,
                    critic_run_id,
                    grader_run_id,
                    grader_rationale,
                    AVG(found_credit) as avg_credit
                FROM occurrence_credits
                WHERE split = 'train' OR split = 'valid'
                GROUP BY agent_definition_id, split, scope_kind, snapshot_slug, scope_hash,
                         tp_id, occurrence_id, critic_run_id, grader_run_id, grader_rationale
            ) occurrence_avg
            GROUP BY agent_definition_id, split, scope_kind, snapshot_slug, scope_hash
        ),
        split_stats AS (
            -- Aggregate statistics per (definition, split, scope_kind)
            SELECT
                agent_definition_id,
                split,
                scope_kind,
                AVG(recall) as mean_recall,
                -- Lower confidence bound: mean - 1.0 * (stddev / sqrt(n))
                -- NULL if n < 2 (can't compute stddev with single sample)
                CASE
                    WHEN COUNT(*) >= 2 THEN
                        AVG(recall) - 1.0 * (STDDEV_SAMP(recall) / SQRT(COUNT(*)))
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
            GROUP BY agent_definition_id, split, scope_kind
        )
        SELECT
            d.id as agent_definition_id,
            d.created_at,
            s.split,
            s.scope_kind,
            s.mean_recall,
            s.recall_lcb,
            s.success_count,
            s.total_count,
            s.zero_count,
            s.stuck_count,
            s.context_count
        FROM agent_definitions d
        LEFT JOIN split_stats s ON s.agent_definition_id = d.id
        ORDER BY
            d.created_at DESC
        LIMIT :limit
    """
    )

    results = session.execute(query_text, {"limit": limit}).fetchall()

    # Group results by agent_definition_id and build stats dictionaries
    definition_data: dict[str, dict] = {}
    definition_stats: dict[str, dict[tuple[Split, str], SplitPerformanceStats]] = defaultdict(dict)

    for row in results:
        # Store definition metadata (same for all rows of same definition)
        if row.agent_definition_id not in definition_data:
            definition_data[row.agent_definition_id] = {"created_at": row.created_at}

        # Add stats for this (split, scope_kind) combination if available
        if row.split is not None and row.scope_kind is not None and row.mean_recall is not None:
            definition_stats[row.agent_definition_id][(Split(row.split), row.scope_kind)] = SplitPerformanceStats(
                mean_recall=row.mean_recall,
                lcb=row.recall_lcb,
                success_count=row.success_count,
                total_count=row.total_count,
                zero_count=row.zero_count or 0,
                stuck_count=row.stuck_count or 0,
                context_count=row.context_count or 0,
            )

    # Convert to Pydantic models
    return [
        DefinitionPerformanceRow(
            agent_definition_id=definition_id, created_at=data["created_at"], stats=definition_stats[definition_id]
        )
        for definition_id, data in definition_data.items()
    ]


# ============================================================================
# Recall by Example Queries (Occurrence-Weighted)
# ============================================================================


class RecallByExampleRow(BaseModel):
    """Single row from recall-by-example query."""

    snapshot_slug: SnapshotSlug
    scope_hash: str
    agent_definition_id: str
    recall: float


def query_recall_by_example(
    session: Session,
    split: Split | None = None,
    agent_definition_id: str | None = None,
    snapshot_slugs: list[SnapshotSlug] | None = None,
) -> list[RecallByExampleRow]:
    """Query occurrence-weighted recall grouped by (example, agent_definition).

    Computes AVG(found_credit) from occurrence_credits view, grouped by
    (snapshot_slug, scope_hash, agent_definition_id).

    This is the canonical way to compute recall for cross-run aggregation.
    Single-run recall can be computed inline from occurrence_results.

    Args:
        session: SQLAlchemy session
        split: Optional split filter (TRAIN, VALID, TEST)
        agent_definition_id: Optional definition filter (get recall for specific definition)
        snapshot_slugs: Optional list of snapshot slugs to filter

    Returns:
        List of RecallByExampleRow (snapshot, scope_hash, agent_definition_id, recall)

    Example:
        # Get recall for all train examples with a specific definition
        results = query_recall_by_example(
            session,
            split=Split.TRAIN,
            agent_definition_id="critic/v1"
        )
        for row in results:
            print(f"{row.snapshot_slug}: {row.recall * 100:.1f}%")
    """
    query = session.query(
        OccurrenceCredit.snapshot_slug,
        OccurrenceCredit.scope_hash,
        OccurrenceCredit.agent_definition_id,
        func.avg(OccurrenceCredit.found_credit).label("avg_credit_per_occurrence"),
    )

    if split is not None:
        query = query.filter(OccurrenceCredit.split == split)
    if agent_definition_id is not None:
        query = query.filter(OccurrenceCredit.agent_definition_id == agent_definition_id)
    if snapshot_slugs is not None:
        query = query.filter(OccurrenceCredit.snapshot_slug.in_(snapshot_slugs))

    query = query.group_by(
        OccurrenceCredit.snapshot_slug, OccurrenceCredit.scope_hash, OccurrenceCredit.agent_definition_id
    )

    results = query.all()
    return [
        RecallByExampleRow(
            snapshot_slug=r.snapshot_slug,
            scope_hash=r.scope_hash,
            agent_definition_id=r.agent_definition_id,
            recall=r.avg_credit_per_occurrence,
        )
        for r in results
    ]


# ============================================================================
# Cross-Run Aggregated Recall (Database Views)
# ============================================================================
#
# Use ORM models to query the database views directly:
#
# Example 1: Query aggregated_recall_by_definition view
#   from adgn.props.db.models import AggregatedRecallByDefinition
#   from adgn.props.splits import Split
#   from adgn.props.models.critic_scopes import ScopeKind
#
#   result = session.query(AggregatedRecallByDefinition).filter(
#       AggregatedRecallByDefinition.split == Split.TRAIN,
#       AggregatedRecallByDefinition.critic_model == "gpt-4o",
#       AggregatedRecallByDefinition.scope_kind == ScopeKind.SPECIFIC_FILES,
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
