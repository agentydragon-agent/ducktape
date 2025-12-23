"""Example: Working with Example objects (composite primary key pattern).

This script demonstrates how to work with Example objects, which have a
composite primary key instead of a single 'id' field.

Key schema details:
- Example has composite primary key: (snapshot_slug, example_kind, files_hash)
- No 'id' or 'key' attribute - use the tuple (snapshot_slug, example_kind, files_hash) as identifier
- Access via: example.snapshot_slug, example.example_kind, example.files_hash
- Query pattern: session.query(Example).filter_by(snapshot_slug=..., example_kind=..., files_hash=...)
- For whole_snapshot examples: files_hash is NULL

TODO: Move this module to agent_defs/ with appropriate symlinks for agents that need it.
"""

from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import aliased

from adgn.props.agent_types import AgentType
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun
from adgn.props.display import short_sha
from adgn.props.models.examples import ExampleKind

# Example keys to query (can be patched in tests)
# Format: (snapshot_slug, example_kind, files_hash)
# files_hash is None for whole_snapshot examples
examples: list[tuple[str, ExampleKind, str | None]] = [
    ("ducktape/2025-12-04-00", ExampleKind.WHOLE_SNAPSHOT, None),
    ("crush/2025-08-30-internal_db", ExampleKind.FILE_SET, "733628142f29d9df2a775332d677ba976ffafbd95f1ceb3908cdf94a6a6af4ca"),
]


def main():
    """Query details for specific examples."""
    with get_session() as session:

        print("Querying example details:")
        print()

        for snapshot_slug, example_kind, files_hash in examples:
            example = session.query(Example).filter_by(
                snapshot_slug=snapshot_slug, example_kind=example_kind, files_hash=files_hash
            ).first()

            if example is None:
                hash_display = short_sha(files_hash) if files_hash else "whole"
                print(f"❌ Example not found: {snapshot_slug} / {example_kind.value} / {hash_display}")
                print()
                continue

            hash_display = short_sha(example.files_hash) if example.files_hash else "whole"
            print(f"✓ {snapshot_slug} / {example_kind.value} / {hash_display}")

            # Count associated critic runs (AgentRun with CRITIC agent_type)
            # CriticTypeConfig stores example as nested object: type_config->'example'
            query = (
                session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
                    AgentRun.type_config["example"]["snapshot_slug"].astext == snapshot_slug,
                    AgentRun.type_config["example"]["kind"].astext == example_kind.value,
                )
            )
            if files_hash:
                query = query.filter(AgentRun.type_config["example"]["files_hash"].astext == files_hash)
            else:
                # For whole_snapshot, files_hash should be absent or null
                query = query.filter(AgentRun.type_config["example"]["files_hash"].astext.is_(None))

            critic_count = query.count()
            print(f"  Critic runs: {critic_count}")

            # Count associated grader runs (AgentRun with GRADER agent_type)
            # Graders don't have snapshot_slug directly - lookup via graded critic's type_config
            CriticRun = aliased(AgentRun)
            grader_count = (
                session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                    exists().where(
                        CriticRun.agent_run_id == AgentRun.type_config["graded_agent_run_id"].astext.cast(PG_UUID),
                        CriticRun.type_config["example"]["snapshot_slug"].astext == snapshot_slug,
                    ),
                )
                .count()
            )
            print(f"  Grader runs: {grader_count}")
            print()


if __name__ == "__main__":
    main()
