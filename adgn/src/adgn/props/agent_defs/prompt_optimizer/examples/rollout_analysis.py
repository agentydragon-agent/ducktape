"""Rollout analysis: query builders and display functions for execution traces.

Query agent run status, inspect execution traces (tool calls, outputs), and analyze failures.

Query Builders (return SQLAlchemy Select objects):
- tools_used_by_agent_run(): Count tool usage by name for a given agent run
- tool_sequence_by_agent_run(): Get tool call sequence in chronological order
- failed_tools_by_agent_run(): Get tool calls that returned errors

Display Functions (use rich console):
- show_run_status(): Count runs by status
- show_execution_traces(): Show tool calls for recent runs
- analyze_critic_failure(): Deep-dive analysis of a specific critic run
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rich.console import Console
from sqlalchemy import Select, cast, func, select, type_coerce
from sqlalchemy.dialects import postgresql

from adgn.agent.events import ApiRequest, AssistantText, ReasoningItem, Response, ToolCall, ToolCallOutput, UserText
from adgn.props.agent_types import AgentType, CriticTypeConfig
from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, Event, GradingDecision
from adgn.props.display import ColumnDef, build_table_from_schema, ellipticize, print_table_with_footer, short_sha

# ============================================================================
# Query Builders (return SQLAlchemy Select objects)
# ============================================================================


def tools_used_by_agent_run(agent_run_id: UUID) -> Select:
    """Count tool usage by name for a given agent run.

    Args:
        agent_run_id: Agent run UUID to query

    Returns:
        Query selecting (tool_name, count) ordered by count descending

    Example:
        with get_session() as session:
            result = session.execute(tools_used_by_agent_run(run_id)).fetchall()
            for row in result:
                print(f"{row.tool_name}: {row.count} calls")
    """
    return (
        select(Event.payload["name"].astext.label("tool_name"), func.count().label("count"))
        .where(Event.agent_run_id == agent_run_id, Event.event_type == "tool_call")
        .group_by(Event.payload["name"].astext)
        .order_by(func.count().desc())
    )


def tool_sequence_by_agent_run(agent_run_id: UUID) -> Select:
    """Get tool call sequence for an agent run.

    Args:
        agent_run_id: Agent run UUID to query

    Returns:
        Query selecting (sequence_num, timestamp, tool_name) ordered by sequence

    Example:
        with get_session() as session:
            result = session.execute(tool_sequence_by_agent_run(run_id)).fetchall()
            for row in result:
                print(f"{row.sequence_num}: {row.tool_name}")
    """
    return (
        select(Event.sequence_num, Event.timestamp, Event.payload["name"].astext.label("tool_name"))
        .where(Event.agent_run_id == agent_run_id, Event.event_type == "tool_call")
        .order_by(Event.sequence_num)
    )


def failed_tools_by_agent_run(agent_run_id: UUID) -> Select:
    """Get failed tool calls for an agent run.

    Args:
        agent_run_id: Agent run UUID to query

    Returns:
        Query selecting (tool_name, is_error, result) for failed tools

    Example:
        with get_session() as session:
            result = session.execute(failed_tools_by_agent_run(run_id)).fetchall()
            for row in result:
                print(f"FAILED: {row.tool_name}")
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
# Display helpers
# ============================================================================


@dataclass
class CriticRunSummary:
    """Summary data for a critic run."""

    run_id: UUID
    snapshot_slug: str
    definition_id: str
    status: str
    tool_count: int


def _fmt_event(event: Event) -> tuple[str, str] | None:
    """Format event payload for display. Returns (type, content) or None to skip."""
    p = event.payload
    if isinstance(p, (ApiRequest, Response)):
        return None
    if isinstance(p, ToolCall):
        return (event.event_type, f"{p.name} | {ellipticize(p.args_json or '{}', 100)}")
    if isinstance(p, ToolCallOutput):
        c = str(p.result.structuredContent or p.result.content or "").replace("\n", " ")
        return (f"{event.event_type} ({'ERROR' if p.result.isError else 'OK'})", ellipticize(c, 50))
    if isinstance(p, ReasoningItem):
        return (event.event_type, ellipticize(" | ".join(i.text for i in p.summary), 100))
    if isinstance(p, (AssistantText, UserText)):
        return (event.event_type, ellipticize(p.text, 100))
    return (event.event_type, ellipticize(str(p), 100))


# ============================================================================
# Display Functions (use rich console)
# ============================================================================


def _get_descendant_run_ids(session, root_agent_run_id: UUID) -> list[UUID]:
    """Get all descendant agent run IDs (children, grandchildren, etc.) of a root agent.

    Uses a recursive CTE to traverse the parent_agent_run_id hierarchy.
    """
    from sqlalchemy import text

    # Recursive CTE to find all descendants
    cte_sql = text("""
        WITH RECURSIVE descendants AS (
            -- Base case: direct children
            SELECT agent_run_id FROM agent_runs WHERE parent_agent_run_id = :root_id
            UNION ALL
            -- Recursive case: children of children
            SELECT ar.agent_run_id
            FROM agent_runs ar
            JOIN descendants d ON ar.parent_agent_run_id = d.agent_run_id
        )
        SELECT agent_run_id FROM descendants
    """)
    result = session.execute(cte_sql, {"root_id": root_agent_run_id})
    return [row[0] for row in result]


def show_run_status(parent_agent_run_id: UUID | None = None) -> None:
    """Query run status statistics.

    Args:
        parent_agent_run_id: If provided, only show runs that are descendants
            of this agent run (i.e., runs spawned by this optimizer/improver).
            If None, shows all runs globally.
    """
    console = Console()
    with get_session() as session:
        # Build filter for descendant runs if parent specified
        descendant_ids: list[UUID] | None = None
        if parent_agent_run_id is not None:
            descendant_ids = _get_descendant_run_ids(session, parent_agent_run_id)
            if not descendant_ids:
                console.print("[yellow]No child runs found for this agent.[/yellow]")
                return
            console.print(f"[dim]Showing runs spawned by this agent ({len(descendant_ids)} total)[/dim]\n")

        cols: list[ColumnDef[Any, Any]] = [
            ColumnDef("Status", lambda r: r.status, width=30),
            ColumnDef("Count", lambda r: r.count, str, justify="right"),
        ]

        console.print("\n[bold]Critic Run Status:[/bold]")
        critic_q = session.query(
            AgentRun.status.label("status"), func.count(AgentRun.agent_run_id).label("count")
        ).filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
        if descendant_ids is not None:
            critic_q = critic_q.filter(AgentRun.agent_run_id.in_(descendant_ids))
        critic_q = critic_q.group_by(AgentRun.status)
        console.print(build_table_from_schema(critic_q.all(), cols))

        console.print("\n[bold]Grader Run Status:[/bold]")
        grader_q = session.query(
            AgentRun.status.label("status"), func.count(AgentRun.agent_run_id).label("count")
        ).filter(AgentRun.type_config["agent_type"].astext == AgentType.GRADER)
        if descendant_ids is not None:
            grader_q = grader_q.filter(AgentRun.agent_run_id.in_(descendant_ids))
        grader_q = grader_q.group_by(AgentRun.status)
        console.print(build_table_from_schema(grader_q.all(), cols))

        console.print("\n[bold]Definitions with most max_turns_exceeded (top 5):[/bold]")
        mt = func.count().filter(AgentRun.status == AgentRunStatus.MAX_TURNS_EXCEEDED)
        pq = session.query(
            AgentRun.agent_definition_id.label("definition_id"), mt.label("mt"), func.count().label("total")
        ).filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
        if descendant_ids is not None:
            pq = pq.filter(AgentRun.agent_run_id.in_(descendant_ids))
        pq = pq.group_by(AgentRun.agent_definition_id).order_by(mt.desc()).limit(5)
        pcols: list[ColumnDef[Any, Any]] = [
            ColumnDef("Definition", lambda r: r.definition_id, width=20),
            ColumnDef("MaxTurns", lambda r: r.mt, str, justify="right"),
            ColumnDef("Total", lambda r: r.total, str, justify="right"),
            ColumnDef(
                "Rate", lambda r: (r.mt / r.total * 100) if r.total > 0 else 0, lambda v: f"{v:.1f}%", justify="right"
            ),
        ]
        console.print(build_table_from_schema(pq.all(), pcols))


def show_execution_traces(limit: int = 5, parent_agent_run_id: UUID | None = None) -> None:
    """Show execution traces for recent critic runs.

    Args:
        limit: Maximum number of recent runs to show.
        parent_agent_run_id: If provided, only show runs that are descendants
            of this agent run (i.e., runs spawned by this optimizer/improver).
            If None, shows all runs globally.
    """
    console = Console()
    with get_session() as session:
        # Build filter for descendant runs if parent specified
        descendant_ids: list[UUID] | None = None
        if parent_agent_run_id is not None:
            descendant_ids = _get_descendant_run_ids(session, parent_agent_run_id)
            if not descendant_ids:
                console.print("[yellow]No child runs found for this agent.[/yellow]")
                return
            console.print(f"[dim]Showing runs spawned by this agent ({len(descendant_ids)} total)[/dim]\n")

        # Query recent critic runs (AgentRun with CRITIC agent_type)
        critic_q = session.query(AgentRun).filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
        if descendant_ids is not None:
            critic_q = critic_q.filter(AgentRun.agent_run_id.in_(descendant_ids))
        critic_runs = critic_q.order_by(AgentRun.created_at.desc()).limit(limit).all()

        # Build summaries - query events per run using agent_run_id directly
        summaries = []
        for cr in critic_runs:
            if isinstance(cr.type_config, CriticTypeConfig):
                snapshot_slug = cr.type_config.example.snapshot_slug
            else:
                raise ValueError(f"Expected CriticTypeConfig, got {type(cr.type_config)}")
            definition_id = cr.agent_definition_id
            tool_count = (
                session.query(Event)
                .filter(Event.agent_run_id == cr.agent_run_id, Event.event_type == "tool_call")
                .count()
            )
            summaries.append(
                CriticRunSummary(cr.agent_run_id, snapshot_slug, definition_id, str(cr.status.value), tool_count)
            )

        console.print(f"\n[bold]Recent critic runs (last {limit}):[/bold]")
        cols: list[ColumnDef[Any, Any]] = [
            ColumnDef("Run", lambda r: str(r.run_id), short_sha, width=8),
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=25),
            ColumnDef("Definition", lambda r: r.definition_id, width=20),
            ColumnDef("Status", lambda r: r.status, width=15),
            ColumnDef("Tools", lambda r: r.tool_count, str, justify="right", width=6),
        ]
        console.print(build_table_from_schema(summaries, cols))

        if summaries:
            s = summaries[0]
            console.print(f"\n[bold]Trace for {short_sha(str(s.run_id))}:[/bold]")
            cr_detail = session.get(AgentRun, s.run_id)
            if cr_detail:
                events = (
                    session.query(Event)
                    .filter(Event.agent_run_id == cr_detail.agent_run_id)
                    .order_by(Event.sequence_num)
                    .limit(100)
                    .all()
                )
                console.print(
                    f"Snapshot: {s.snapshot_slug} | Definition: {s.definition_id} | Status: {s.status} | Tools: {s.tool_count}\n"
                )
                rows = [(i, t, c) for i, (t, c) in enumerate(filter(None, (_fmt_event(e) for e in events)), 1)]
                ecols: list[ColumnDef[Any, Any]] = [
                    ColumnDef("#", lambda r: r[0], str, justify="right", width=3),
                    ColumnDef("Type", lambda r: r[1], width=12),
                    ColumnDef("Content", lambda r: r[2], width=80),
                ]
                total_events = session.query(Event).filter(Event.agent_run_id == cr_detail.agent_run_id).count()
                print_table_with_footer(
                    console, rows, ecols, show_header=True, total_count=total_events, item_name="events"
                )


def show_grading_summary(agent_run_id: UUID) -> None:
    """Show grading decision summary for a critic or grader run.

    Args:
        agent_run_id: UUID of a critic or grader run. If critic, finds associated grader.
    """
    with get_session() as session:
        run = session.get(AgentRun, agent_run_id)
        if not run:
            print(f"Run not found: {agent_run_id}")
            return

        agent_type = run.type_config.agent_type

        # Resolve to grader run
        if agent_type == AgentType.CRITIC:
            cr = run
            print(
                f"Critic: {short_sha(str(cr.agent_run_id))} | Definition: {cr.agent_definition_id} | Model: {cr.model}"
            )
            if cr.status != AgentRunStatus.COMPLETED:
                print(f"Status: {cr.status.value.upper()} (did not complete)")
                return

            gr = (
                session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                    AgentRun.type_config["graded_agent_run_id"].astext == str(cr.agent_run_id),
                )
                .first()
            )
            if not gr:
                print("No grader result (not graded yet)")
                return
        elif agent_type == AgentType.GRADER:
            gr = run
        else:
            print(f"Expected critic or grader run, got: {agent_type}")
            return

        if gr.status != AgentRunStatus.COMPLETED:
            print(f"Grader status: {gr.status.value}")
            return

        # Grader results
        grader_run_id = gr.agent_run_id
        print(f"Grader: {short_sha(str(grader_run_id))}\n")

        credit = (
            session.query(func.sum(GradingDecision.credit))
            .filter_by(agent_run_id=grader_run_id)
            .filter(GradingDecision.target_tp_id.isnot(None))
            .scalar()
            or 0.0
        )
        n_occ = (
            session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
            .filter_by(agent_run_id=grader_run_id)
            .filter(GradingDecision.target_tp_id.isnot(None))
            .distinct()
            .count()
        )
        n_tps = (
            session.query(GradingDecision.target_tp_id)
            .filter_by(agent_run_id=grader_run_id)
            .filter(GradingDecision.target_tp_id.isnot(None))
            .distinct()
            .count()
        )
        n_novel = (
            session.query(GradingDecision)
            .filter_by(agent_run_id=grader_run_id)
            .filter(GradingDecision.target_tp_id.is_(None))
            .count()
        )
        print(f"Credit: {credit:.1f}/{n_occ} occ | {n_tps} TPs | {n_novel} unknown\n")

        # Missed
        missed_q = (
            session.query(GradingDecision)
            .filter_by(agent_run_id=grader_run_id)
            .filter(GradingDecision.target_tp_id.isnot(None), GradingDecision.credit == 0.0)
        )
        total_missed = missed_q.count()
        missed = missed_q.limit(5).all()
        if missed:
            print(f"Missed ({len(missed)}/{total_missed}):")
            for d in missed:
                print(
                    f"  - {d.target_tp_id} occ {d.target_tp_occurrence_id}" + (" (partial)" if d.input_issue_id else "")
                )


def main():
    """Run all run analysis examples."""
    show_run_status()
    print()
    show_execution_traces()


if __name__ == "__main__":
    main()
