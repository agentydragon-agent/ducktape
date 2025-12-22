"""Run status, execution traces, and failure analysis.

Query critic/grader run status, inspect execution traces, analyze failures.

Functions:
- show_run_status(): Count runs by status
- show_execution_traces(): Show tool calls for recent runs
- analyze_critic_failure(): Deep-dive analysis of a specific critic run

TODO: Move this module to agent_defs/ with appropriate symlinks for agents that need it.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rich.console import Console
from sqlalchemy import func

from adgn.agent.events import ApiRequest, AssistantText, ReasoningItem, Response, ToolCall, ToolCallOutput, UserText
from adgn.props.agent_types import AgentType, CriticTypeConfig
from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, Event, GradingDecision
from adgn.props.display import ColumnDef, build_table_from_schema, ellipticize, print_table_with_footer, short_sha


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


def show_run_status() -> None:
    """Query run status statistics."""
    console = Console()
    with get_session() as session:
        cols: list[ColumnDef[Any, Any]] = [
            ColumnDef("Status", lambda r: r.status, width=30),
            ColumnDef("Count", lambda r: r.count, str, justify="right"),
        ]

        console.print("\n[bold]Critic Run Status:[/bold]")
        critic_q = (
            session.query(AgentRun.status.label("status"), func.count(AgentRun.agent_run_id).label("count"))
            .filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
            .group_by(AgentRun.status)
        )
        console.print(build_table_from_schema(critic_q.all(), cols))

        console.print("\n[bold]Grader Run Status:[/bold]")
        grader_q = (
            session.query(AgentRun.status.label("status"), func.count(AgentRun.agent_run_id).label("count"))
            .filter(AgentRun.type_config["agent_type"].astext == AgentType.GRADER)
            .group_by(AgentRun.status)
        )
        console.print(build_table_from_schema(grader_q.all(), cols))

        console.print("\n[bold]Definitions with most max_turns_exceeded (top 5):[/bold]")
        mt = func.count().filter(AgentRun.status == AgentRunStatus.MAX_TURNS_EXCEEDED)
        pq = (
            session.query(AgentRun.agent_definition_id.label("definition_id"), mt.label("mt"), func.count().label("total"))
            .filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
            .group_by(AgentRun.agent_definition_id)
            .order_by(mt.desc())
            .limit(5)
        )
        pcols: list[ColumnDef[Any, Any]] = [
            ColumnDef("Definition", lambda r: r.definition_id, width=20),
            ColumnDef("MaxTurns", lambda r: r.mt, str, justify="right"),
            ColumnDef("Total", lambda r: r.total, str, justify="right"),
            ColumnDef("Rate", lambda r: (r.mt / r.total * 100) if r.total > 0 else 0, lambda v: f"{v:.1f}%", justify="right"),
        ]
        console.print(build_table_from_schema(pq.all(), pcols))


def show_execution_traces(limit: int = 5) -> None:
    """Show execution traces for recent critic runs."""
    console = Console()
    with get_session() as session:
        # Query recent critic runs (AgentRun with CRITIC agent_type)
        critic_runs = (
            session.query(AgentRun)
            .filter(AgentRun.type_config["agent_type"].astext == AgentType.CRITIC)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
            .all()
        )

        # Build summaries - query events per run using agent_run_id directly
        summaries = []
        for cr in critic_runs:
            if isinstance(cr.type_config, CriticTypeConfig):
                snapshot_slug = cr.type_config.snapshot_slug
            else:
                raise ValueError(f"Expected CriticTypeConfig, got {type(cr.type_config)}")
            definition_id = cr.agent_definition_id
            tool_count = session.query(Event).filter(
                Event.agent_run_id == cr.agent_run_id,
                Event.event_type == "tool_call",
            ).count()
            summaries.append(CriticRunSummary(cr.agent_run_id, snapshot_slug, definition_id, str(cr.status.value), tool_count))

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
                events = session.query(Event).filter(Event.agent_run_id == cr_detail.agent_run_id).order_by(Event.sequence_num).limit(100).all()
                console.print(f"Snapshot: {s.snapshot_slug} | Definition: {s.definition_id} | Status: {s.status} | Tools: {s.tool_count}\n")
                rows = [(i, t, c) for i, (t, c) in enumerate(filter(None, (_fmt_event(e) for e in events)), 1)]
                ecols: list[ColumnDef[Any, Any]] = [ColumnDef("#", lambda r: r[0], str, justify="right", width=3), ColumnDef("Type", lambda r: r[1], width=12), ColumnDef("Content", lambda r: r[2], width=80)]
                total_events = session.query(Event).filter(Event.agent_run_id == cr_detail.agent_run_id).count()
                print_table_with_footer(console, rows, ecols, show_header=True, total_count=total_events, item_name="events")


def analyze_critic_failure(snapshot_slug: str, scope_hash: str) -> None:
    """Analyze critic failures on a specific example."""
    console = Console()
    with get_session() as session:
        runs = (
            session.query(AgentRun)
            .filter(
                AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
                AgentRun.type_config["snapshot_slug"].astext == snapshot_slug,
                AgentRun.type_config["scope_hash"].astext == scope_hash,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(5)
            .all()
        )
        if not runs:
            print(f"No critic runs found for {snapshot_slug} / {short_sha(scope_hash)}...")
            return

        print(f"=== {len(runs)} critic runs for {snapshot_slug} / {short_sha(scope_hash)} ===\n")
        cr = runs[0]
        print(f"Run: {short_sha(str(cr.agent_run_id))} | Definition: {cr.agent_definition_id} | Model: {cr.model}\n")

        if cr.status != AgentRunStatus.COMPLETED:
            print(f"Status: {cr.status.value.upper()} (did not complete)")
            return
        print(f"Status: COMPLETED | ID: {cr.agent_run_id}\n")

        # Find grader run via JSONB graded_agent_run_id
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

        if gr.status != AgentRunStatus.COMPLETED:
            print(f"Grader status: {gr.status.value}")
            return

        # Grader results
        grader_run_id = gr.agent_run_id
        credit = session.query(func.sum(GradingDecision.credit)).filter_by(agent_run_id=grader_run_id).filter(GradingDecision.target_tp_id.isnot(None)).scalar() or 0.0
        n_occ = session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id).filter_by(agent_run_id=grader_run_id).filter(GradingDecision.target_tp_id.isnot(None)).distinct().count()
        n_tps = session.query(GradingDecision.target_tp_id).filter_by(agent_run_id=grader_run_id).filter(GradingDecision.target_tp_id.isnot(None)).distinct().count()
        n_novel = session.query(GradingDecision).filter_by(agent_run_id=grader_run_id).filter(GradingDecision.target_tp_id.is_(None)).count()
        print(f"=== Grader: {credit:.1f}/{n_occ} occ, {n_tps} TPs, {n_novel} unknown ===\n")

        # Missed
        missed = session.query(GradingDecision).filter_by(agent_run_id=grader_run_id).filter(GradingDecision.target_tp_id.isnot(None), GradingDecision.credit == 0.0).limit(3).all()
        if missed:
            print(f"Missed ({len(missed)} shown):")
            for d in missed:
                print(f"  - {d.target_tp_id} occ {d.target_tp_occurrence_id}" + (" (partial)" if d.input_issue_id else ""))

        # Trace - use agent_run_id directly
        console.print("\n[bold]=== Execution Trace ===[/bold]\n")
        events = session.query(Event).filter(Event.agent_run_id == cr.agent_run_id).order_by(Event.sequence_num).limit(100).all()
        rows = [(i, t, c) for i, (t, c) in enumerate(filter(None, (_fmt_event(e) for e in events)), 1)]
        if rows:
            ecols: list[ColumnDef[Any, Any]] = [ColumnDef("#", lambda r: r[0], str, justify="right", width=3), ColumnDef("Type", lambda r: r[1], width=12), ColumnDef("Content", lambda r: r[2], width=80)]
            total_events = session.query(Event).filter(Event.agent_run_id == cr.agent_run_id).count()
            print_table_with_footer(console, rows, ecols, show_header=True, total_count=total_events, item_name="events")


def main():
    """Run all run analysis examples."""
    show_run_status()
    print()
    show_execution_traces()


if __name__ == "__main__":
    main()
