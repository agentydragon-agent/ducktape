"""Example: Query critic and grader run status to check for max_turns_exceeded.

This script demonstrates how to check which runs succeeded vs exceeded turn limits,
helping identify prompts that cause the agent to get stuck.
"""

from typing import Any

from rich.console import Console
from sqlalchemy import func

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus, GraderRun, GraderRunStatus
from adgn.props.display import short_sha
from adgn.props.display import ColumnDef, build_table_from_schema


def main():
    """Query run status statistics."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()
    console = Console()

    with get_session() as session:
        # Count critic runs by status
        console.print("\n[bold]Critic Run Status:[/bold]")
        critic_status_query = (
            session.query(CriticRun.status.label("status"), func.count(CriticRun.id).label("count"))
            .group_by(CriticRun.status)
        )
        critic_results = critic_status_query.all()

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Status", lambda r: r.status, width=30),
            ColumnDef("Count", lambda r: r.count, str, justify="right"),
        ]
        console.print(build_table_from_schema(critic_results, columns))

        # Count grader runs by status
        console.print("\n[bold]Grader Run Status:[/bold]")
        grader_status_query = (
            session.query(GraderRun.status.label("status"), func.count(GraderRun.id).label("count"))
            .group_by(GraderRun.status)
        )
        grader_results = grader_status_query.all()

        console.print(build_table_from_schema(grader_results, columns))

        # Show prompts with highest max_turns_exceeded rate
        console.print("\n[bold]Prompts with most max_turns_exceeded (top 5):[/bold]")
        max_turns_query = (
            session.query(
                CriticRun.prompt_sha256,
                func.count().filter(CriticRun.status == CriticRunStatus.MAX_TURNS_EXCEEDED).label("max_turns_count"),
                func.count().label("total_runs"),
            )
            .group_by(CriticRun.prompt_sha256)
            .order_by(func.count().filter(CriticRun.status == CriticRunStatus.MAX_TURNS_EXCEEDED).desc())
            .limit(5)
        )
        prompt_results = max_turns_query.all()

        prompt_columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Prompt", lambda r: r.prompt_sha256, short_sha, width=8),
            ColumnDef("Max Turns", lambda r: r.max_turns_count, str, justify="right"),
            ColumnDef("Total", lambda r: r.total_runs, str, justify="right"),
            ColumnDef(
                "Rate",
                lambda r: (r.max_turns_count / r.total_runs * 100) if r.total_runs > 0 else 0,
                lambda v: f"{v:.1f}%",
                justify="right",
            ),
        ]
        console.print(build_table_from_schema(prompt_results, prompt_columns))


if __name__ == "__main__":
    main()
