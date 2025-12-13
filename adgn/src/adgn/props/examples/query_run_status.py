"""Example: Query critic and grader run status to check for max_turns_exceeded.

This script demonstrates how to check which runs succeeded vs exceeded turn limits,
helping identify prompts that cause the agent to get stuck.
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GraderRun
from sqlalchemy import func


def main():
    """Query run status statistics."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    with get_session() as session:
        # Count critic runs by status
        print("Critic Run Status:")
        critic_status_query = (
            session.query(CriticRun.output["tag"].astext.label("status"), func.count(CriticRun.id).label("count"))
            .filter(CriticRun.output.isnot(None))
            .group_by(CriticRun.output["tag"].astext)
        )

        for status, count in critic_status_query.all():
            print(f"  {status}: {count}")

        # Count grader runs by status
        print("\nGrader Run Status:")
        grader_status_query = (
            session.query(GraderRun.output["tag"].astext.label("status"), func.count(GraderRun.id).label("count"))
            .filter(GraderRun.output.isnot(None))
            .group_by(GraderRun.output["tag"].astext)
        )

        for status, count in grader_status_query.all():
            print(f"  {status}: {count}")

        # Show prompts with highest max_turns_exceeded rate
        print("\nPrompts with most max_turns_exceeded (top 5):")
        max_turns_query = (
            session.query(
                CriticRun.prompt_sha256,
                func.count().filter(CriticRun.output["tag"].astext == "max_turns_exceeded").label("max_turns_count"),
                func.count().label("total_runs"),
            )
            .filter(CriticRun.output.isnot(None))
            .group_by(CriticRun.prompt_sha256)
            .order_by(func.count().filter(CriticRun.output["tag"].astext == "max_turns_exceeded").desc())
            .limit(5)
        )

        for prompt_sha, max_turns, total in max_turns_query.all():
            rate = (max_turns / total * 100) if total > 0 else 0
            print(f"  {prompt_sha[:8]}: {max_turns}/{total} ({rate:.1f}%)")


if __name__ == "__main__":
    main()
