"""The index's two schema definitions must not drift.

`haku/recall_index/schema.py` is what the code queries and what `store.ensure_schema` builds for
the CLI and the tests; the console's Alembic baseline is what the deployed database gets. Nothing
else compares them, and a column added to one and not the other would pass every other test in the
repo and fail in production at the first query.
"""

from __future__ import annotations

import pytest
import pytest_bazel
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import ProgrammingError

from haku.console.database_migrate import apply_migrations
from haku.recall_index.schema import SCHEMA, Base


def _only_the_index_schema(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Keep the comparison to the recall-index schema.

    `include_schemas` is what makes Alembic look outside `public` at all, and it looks at *every*
    schema — so without this the console's own tables all read as "not in this metadata" and the
    comparison is a list of everything else the database contains.
    """
    return name == SCHEMA if type_ == "schema" else True


def test_the_migration_builds_exactly_what_the_orm_declares(db_url: str) -> None:
    apply_migrations(db_url)
    # The fixture hands out an asyncpg URL for the app; comparison is synchronous.
    engine = create_engine(make_url(db_url).set(drivername="postgresql+psycopg").render_as_string(False))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "include_schemas": True, "include_name": _only_the_index_schema}
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_startup_refuses_a_database_whose_stamped_schema_drifted(db_url: str) -> None:
    """The guard that should have caught the 2026-08-15 rename, on the schema it did not cover.

    An edited revision is a no-op against a database that already recorded it, so the only thing
    standing between that and a pod serving queries for absent columns is this read.
    """
    apply_migrations(db_url)
    engine = create_engine(make_url(db_url).set(drivername="postgresql+psycopg").render_as_string(False))
    try:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {SCHEMA}.chat_chunks RENAME COLUMN window_no TO chunk_no"))

        with pytest.raises(ProgrammingError):
            apply_migrations(db_url)
    finally:
        engine.dispose()


def test_the_schema_rename_preserves_the_derived_index(db_url: str) -> None:
    """A database stamped before 0083 keeps its existing content under ``recall_index``."""
    apply_migrations(db_url, "0082")
    engine = create_engine(make_url(db_url).set(drivername="postgresql+psycopg").render_as_string(False))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO state_index.contents (content_sha, content) VALUES ('before-0083', 'preserved')")
            )

        apply_migrations(db_url)

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace('state_index')")) is None
            assert connection.scalar(text("SELECT to_regnamespace('recall_index')")) == "recall_index"
            content = connection.scalar(
                text("SELECT content FROM recall_index.contents WHERE content_sha = 'before-0083'")
            )
            assert content == "preserved"
    finally:
        engine.dispose()


def test_logical_index_migration_backfills_existing_occurrences(db_url: str) -> None:
    """0085 changes every occurrence key without re-embedding or dropping the published tip."""
    apply_migrations(db_url, "0083")
    engine = create_engine(make_url(db_url).set(drivername="postgresql+psycopg").render_as_string(False))
    session_id = "00000000-0000-0000-0000-000000000001"
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO recall_index.contents (content_sha, content) VALUES ('sha', 'preserved')")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO recall_index.git_chunks (blob_sha, chunker_key, byte_start, byte_end, content_sha)
                    VALUES ('blob', 'chunker', 0, 9, 'sha')
                    """
                )
            )
            connection.execute(text("INSERT INTO recall_index.git_tip (path, blob_sha) VALUES ('note.md', 'blob')"))
            connection.execute(text("INSERT INTO recall_index.git_sync_state (id, branch) VALUES (1, 'main')"))
            connection.execute(
                text(
                    f"""
                    INSERT INTO recall_index.chat_sessions
                        (session_id, message_count, last_message_at, chunker_key, model_key, indexed_at)
                    VALUES ('{session_id}', 1, now(), 'chunker', 'model', now())
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    INSERT INTO recall_index.chat_chunks
                        (session_id, window_no, content_sha, first_message_at, last_message_at)
                    VALUES ('{session_id}', 0, 'sha', now(), now())
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    INSERT INTO recall_index.chat_chunk_messages (session_id, window_no, ordinal, message_id)
                    VALUES ('{session_id}', 0, 0, '{session_id}')
                    """
                )
            )

        apply_migrations(db_url)

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('recall_index.index_sources')")) is None
            assert (
                connection.scalar(text("SELECT index_type FROM recall_index.indexes WHERE index_id = 'haku-state'"))
                == "git"
            )
            assert connection.scalar(text("SELECT index_id FROM recall_index.git_sync_state")) == "haku-state"
            assert connection.scalar(text("SELECT index_id FROM recall_index.git_tip")) == "haku-state"
            assert connection.scalar(text("SELECT index_id FROM recall_index.chat_sessions")) == "haku-conversations"
            assert (
                connection.scalar(text("SELECT index_id FROM recall_index.chat_chunk_messages")) == "haku-conversations"
            )
    finally:
        engine.dispose()


def test_embedding_split_preserves_source_progress_without_a_model_claim(db_url: str) -> None:
    """0087 retains materialized source state while making embedding completion global."""
    apply_migrations(db_url, "0086")
    engine = create_engine(make_url(db_url).set(drivername="postgresql+psycopg").render_as_string(False))
    session_id = "00000000-0000-0000-0000-000000000002"
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO recall_index.indexes (index_id, index_type) VALUES ('git', 'git'), ('chat', 'chat')")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO recall_index.git_sync_state
                        (index_id, branch, commit_sha, chunker_key, model_key, synced_at)
                    VALUES ('git', 'main', 'commit', 'chunker', 'old-model', now())
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    INSERT INTO recall_index.chat_sessions
                        (index_id, session_id, message_count, last_message_at, chunker_key, model_key, indexed_at)
                    VALUES ('chat', '{session_id}', 1, now(), 'chunker', 'old-model', now())
                    """
                )
            )

        apply_migrations(db_url)

        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT commit_sha FROM recall_index.git_sync_state WHERE index_id = 'git'"))
                == "commit"
            )
            assert (
                connection.scalar(text("SELECT message_count FROM recall_index.chat_sessions WHERE index_id = 'chat'"))
                == 1
            )
            for table in ("git_sync_state", "chat_sessions"):
                assert (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_schema = 'recall_index' AND table_name = :table AND column_name = 'model_key'"
                        ),
                        {"table": table},
                    )
                    == 0
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    pytest_bazel.main()
