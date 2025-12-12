"""Example: Query top-performing prompts on validation split.

This script demonstrates how to query the database to find which prompts
achieved the highest mean recall on validation examples.
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import Prompt
from sqlalchemy import text


def main():
    """Query and display top-performing prompts on validation split."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    # Query the database
    with get_session() as session:
        # Get top-performing prompts on validation split with mean recall
        # Query the valid_metrics view (already filters to valid split and has provenance)
        query = text("""
            SELECT
                critic_prompt_sha256,
                AVG(recall) as mean_recall,
                COUNT(*) as eval_count
            FROM valid_metrics
            GROUP BY critic_prompt_sha256
            ORDER BY AVG(recall) DESC
            LIMIT 10
        """)

        top_prompts = session.execute(query).fetchall()

        print("Top 10 prompts on validation:")
        for sha, recall, count in top_prompts:
            # Get prompt text preview
            prompt = session.query(Prompt).filter_by(prompt_sha256=sha).first()
            preview = prompt.prompt_text[:100].replace("\n", " ") if prompt else "(not found)"
            plural = "evals" if count != 1 else "eval"
            print(f"  {sha[:8]}: {recall:.3f} ({count} {plural}) - {preview}...")


if __name__ == "__main__":
    main()
