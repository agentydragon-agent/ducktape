"""Configured-index maintenance and reader integration tests."""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path
from uuid import UUID

import pygit2
import pytest
import pytest_bazel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from haku.console.chat_models import ItemStatus, ItemType, RuntimeKind, SessionStatus
from haku.console.config import ChatRecallIndexDefinition, GitRecallIndexDefinition, RecallIndexSettings
from haku.console.database_schema import Conversation, ConversationItem, Operator, Session
from haku.console.mcp_config import ConsoleConfigFile
from haku.console.operator_identity import OperatorStatus
from haku.console.recall_index_reader import PostgresIndexSearcher
from haku.console.recall_index_sync import RecallIndexMaintenance, advisory_lock_for
from haku.console.tools.recall_index import ChatIndexStatus, ChatSource, GitIndexStatus
from haku.recall_index.fake_embedder import ExplodingEmbedder, FakeEmbedder
from haku.recall_index.schema import ContentEmbedding

_AUTHOR = pygit2.Signature("Test", "test@example.com")
_NOW = datetime.datetime(2026, 8, 15, tzinfo=datetime.UTC)
_CHAT = ChatRecallIndexDefinition(index_id="console-chat")
_MANUAL_AUTHORITY_CONFIG = {
    "auto_approval_policies": [{"id": "manual", "type": "never"}],
    "access_profiles": [{"id": "manual", "auto_approval_policy": "manual"}],
    "default_access_profile_id": "manual",
}


def test_recall_index_settings_contains_the_shared_chunk_budget() -> None:
    config = RecallIndexSettings(chunk_budget={"target_bytes": 400, "max_bytes": 800, "overlap_codepoints": 48})
    assert config.chunk_budget.overlap_codepoints == 48


def test_deploy_config_declares_each_index_explicitly() -> None:
    config = ConsoleConfigFile.model_validate(
        {
            **_MANUAL_AUTHORITY_CONFIG,
            "recall_indexes": [
                {
                    "index_id": "haku-state",
                    "index_type": "git",
                    "repo_url": "https://forge.example/haku-state.git",
                    "username_env_var": "HAKU_STATE_GIT_USERNAME",
                    "password_env_var": "HAKU_STATE_GIT_PASSWORD",
                },
                {"index_id": "haku-conversations", "index_type": "chat"},
                {
                    "index_id": "ducktape-public",
                    "index_type": "git",
                    "repo_url": "https://github.com/agentydragon/ducktape.git",
                    "branch": "devel",
                    "mirror_path": "/tmp/haku-recall-index/ducktape.git",
                },
            ],
        }
    )
    assert [(index.index_id, index.index_type) for index in config.recall_indexes] == [
        ("haku-state", "git"),
        ("haku-conversations", "chat"),
        ("ducktape-public", "git"),
    ]
    ducktape = config.recall_indexes[2]
    assert isinstance(ducktape, GitRecallIndexDefinition)
    assert (ducktape.branch, ducktape.username_env_var, ducktape.password_env_var) == ("devel", None, None)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def haku_state(tmp_path: Path) -> GitRecallIndexDefinition:
    """A configured Git index backed by a bare repository with one main-branch commit."""
    origin = pygit2.init_repository(str(tmp_path / "origin.git"), bare=True, initial_head="main")
    index = pygit2.Index()
    blob = origin.create_blob(b"user: the egress fence keys on haku-sandbox\n")
    index.add(pygit2.IndexEntry("notes/alpha.md", blob, pygit2.enums.FileMode.BLOB))
    origin.create_commit("refs/heads/main", _AUTHOR, _AUTHOR, "seed", index.write_tree(origin), [])
    return GitRecallIndexDefinition(
        index_id="haku-state", repo_url=str(tmp_path / "origin.git"), mirror_path=tmp_path / "mirror.git"
    )


@pytest.fixture
async def operator_id(migrated_sessions: async_sessionmaker[AsyncSession]) -> UUID:
    operator_id = uuid.uuid4()
    async with migrated_sessions.begin() as session:
        session.add(Operator(operator_id=operator_id, status=OperatorStatus.ACTIVE, created_at=_NOW, updated_at=_NOW))
    return operator_id


async def say(sessions: async_sessionmaker[AsyncSession], operator_id: UUID, content: str) -> UUID:
    """One chat session holding one prompt, as the console would have written it."""
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    async with sessions.begin() as session:
        session.add(
            Conversation(
                conversation_id=conversation_id,
                operator_id=operator_id,
                runtime_kind=RuntimeKind.CLAUDE_CODE,
                created_at=_NOW,
            )
        )
        await session.flush()
        session.add(
            Session(
                session_id=session_id,
                operator_id=operator_id,
                conversation_id=conversation_id,
                status=SessionStatus.CLOSED,
                bridge_token_fingerprint=b"fingerprint",
                lease_expires_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        # Before the item, which points at it: one unit of work orders inserts by mapper, not by
        # the order they were added.
        await session.flush()
        session.add(
            ConversationItem(
                item_id=uuid.uuid4(),
                conversation_id=conversation_id,
                session_id=session_id,
                item_type=ItemType.PROMPT,
                status=ItemStatus.COMPLETE,
                opened_seq=1,
                closed_seq=3,
                item_text=content,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return session_id


def maintenance(
    engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    embedder: FakeEmbedder,
    *indexes: GitRecallIndexDefinition | ChatRecallIndexDefinition,
) -> RecallIndexMaintenance:
    return RecallIndexMaintenance(engine, sessions, embedder=embedder, indexes=indexes)


async def test_every_configured_index_is_synchronized_and_searchable(
    migrated_engine: AsyncEngine,
    migrated_sessions: async_sessionmaker[AsyncSession],
    haku_state: GitRecallIndexDefinition,
    operator_id: UUID,
    embedder: FakeEmbedder,
) -> None:
    session_id = await say(migrated_sessions, operator_id, "we decided to keep the egress fence")
    indexes = (haku_state, _CHAT)
    await maintenance(migrated_engine, migrated_sessions, embedder, *indexes).sync_all_once()

    results = await PostgresIndexSearcher(migrated_sessions, embedder, indexes=indexes).search(
        "egress", index_ids=None, limit=5, path_prefix=None, session_id=None
    )
    assert {hit.source.kind for hit in results.hits} == {"git", "chat"}
    assert {hit.source.index_id for hit in results.hits} == {"haku-state", "console-chat"}
    assert any(isinstance(hit.source, ChatSource) and hit.source.session_id == session_id for hit in results.hits)


async def test_identical_content_across_configured_indexes_shares_one_embedding(
    migrated_engine: AsyncEngine,
    migrated_sessions: async_sessionmaker[AsyncSession],
    haku_state: GitRecallIndexDefinition,
    operator_id: UUID,
    embedder: FakeEmbedder,
) -> None:
    await say(migrated_sessions, operator_id, "the egress fence keys on haku-sandbox")
    await maintenance(migrated_engine, migrated_sessions, embedder, haku_state, _CHAT).sync_all_once()
    async with migrated_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ContentEmbedding)) == 1


async def test_status_reads_all_configured_indexes_not_fixed_names(
    migrated_engine: AsyncEngine,
    migrated_sessions: async_sessionmaker[AsyncSession],
    haku_state: GitRecallIndexDefinition,
    operator_id: UUID,
    embedder: FakeEmbedder,
) -> None:
    await say(migrated_sessions, operator_id, "status source")
    indexes = (haku_state, _CHAT)
    await maintenance(migrated_engine, migrated_sessions, embedder, *indexes).sync_all_once()
    status = await PostgresIndexSearcher(migrated_sessions, embedder, indexes=indexes).status()
    assert [(entry.index_id, entry.index_type) for entry in status.indexes] == [
        ("haku-state", "git"),
        ("console-chat", "chat"),
    ]


async def test_failed_configured_git_index_reports_the_remote_tip(
    migrated_engine: AsyncEngine,
    migrated_sessions: async_sessionmaker[AsyncSession],
    haku_state: GitRecallIndexDefinition,
    embedder: FakeEmbedder,
) -> None:
    indexes = (haku_state,)
    with pytest.raises(RuntimeError):
        await maintenance(migrated_engine, migrated_sessions, ExplodingEmbedder(), *indexes).sync_index_once(haku_state)
    status = await PostgresIndexSearcher(migrated_sessions, embedder, indexes=indexes).status()
    (git,) = status.indexes
    assert isinstance(git, GitIndexStatus)
    assert git.indexed_commit is None
    assert git.remote_commit is not None
    assert git.branch == "main"


async def test_a_replica_that_loses_one_index_lock_leaves_that_index_alone(
    migrated_engine: AsyncEngine,
    migrated_sessions: async_sessionmaker[AsyncSession],
    operator_id: UUID,
    embedder: FakeEmbedder,
) -> None:
    await say(migrated_sessions, operator_id, "the leader indexes this one")
    async with migrated_engine.connect() as leader:
        lock = advisory_lock_for(_CHAT.index_id)
        assert await leader.scalar(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": lock})
        assert await maintenance(migrated_engine, migrated_sessions, embedder, _CHAT).sync_index_once(_CHAT) is None

    status = await PostgresIndexSearcher(migrated_sessions, embedder, indexes=(_CHAT,)).status()
    (chat,) = status.indexes
    assert isinstance(chat, ChatIndexStatus)
    assert chat.sessions == 0


def test_git_index_credential_references_are_explicit_and_paired() -> None:
    with pytest.raises(ValueError, match="credentials"):
        GitRecallIndexDefinition(
            index_id="private-notes",
            repo_url="https://example.invalid/private-notes.git",
            username_env_var="PRIVATE_NOTES_USERNAME",
        )


if __name__ == "__main__":
    pytest_bazel.main()
