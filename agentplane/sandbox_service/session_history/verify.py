"""Read-only, bounded migration evidence. Never import Events or change runner bindings."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

import grpc
from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.message import DecodeError
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from agentplane.protocol import event_log_pb2
from agentplane.runner.client import RunnerClient

# gazelle:include_dep @pypi//asyncpg
# gazelle:include_dep @pypi//protobuf


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTPLANE_HISTORY_VERIFY_", cli_parse_args=True, cli_kebab_case=True)

    mode: Literal["archive", "runner"]
    session_id: UUID
    through: int = Field(ge=0)
    after: int = Field(default=0, ge=0)
    batch_size: int = Field(default=128, ge=1, le=128)
    max_batches: int = Field(default=100, ge=1, le=1000)
    timeout_s: float = Field(default=60, gt=0, le=300)
    database_url: str
    app_database_url: str | None = None
    runner_target: str | None = None

    @model_validator(mode="after")
    def validate_range_and_mode(self) -> Settings:
        if self.after > self.through:
            raise ValueError("after must not exceed through")
        if self.mode == "archive" and not self.app_database_url:
            raise ValueError("archive mode requires app_database_url")
        if self.mode == "runner" and (not self.runner_target or self.after == self.through):
            raise ValueError("runner mode requires a target and nonempty overlap")
        return self


class VerificationError(ValueError):
    """Missing, conflicting or insufficient evidence; never include Event payloads."""


@asynccontextmanager
async def read_primary(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as connection:
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        await connection.execute(text("SET LOCAL statement_timeout = '10s'"))
        await connection.execute(text("SET LOCAL lock_timeout = '2s'"))
        if await connection.scalar(text("SELECT pg_is_in_recovery()")):
            raise VerificationError("verification requires a primary database connection")
        yield connection


def check_entry(entry: event_log_pb2.EventEntry, cursor: int, source_id: str) -> None:
    if entry.cursor != cursor or entry.origin.sequence != cursor or entry.origin.source_id != source_id:
        raise VerificationError(f"cursor/source identity mismatch at {cursor}")


def compare_entry(left: event_log_pb2.EventEntry, right: event_log_pb2.EventEntry, cursor: int, source_id: str) -> None:
    check_entry(left, cursor, source_id)
    check_entry(right, cursor, source_id)
    if left.SerializeToString(deterministic=True) != right.SerializeToString(deterministic=True):
        raise VerificationError(f"Event mismatch at {cursor}")


async def read_archive(
    engine: AsyncEngine, session_id: UUID, after: int, through: int
) -> list[event_log_pb2.EventEntry]:
    async with read_primary(engine) as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT cursor, payload FROM session_event WHERE session_id = :id "
                    "AND cursor > :after AND cursor <= :through ORDER BY cursor"
                ),
                {"id": session_id, "after": after, "through": through},
            )
        ).all()
    if [row.cursor for row in rows] != list(range(after + 1, through + 1)):
        raise VerificationError(f"archive gap in ({after}, {through}]")
    return [event_log_pb2.EventEntry.FromString(row.payload) for row in rows]


async def verify(settings: Settings, destination: AsyncEngine, source: AsyncEngine | None) -> int:
    """Verify one bounded range; return last checked cursor, never update a database checkpoint."""
    async with read_primary(destination) as connection:
        history = (
            await connection.execute(
                text(
                    "SELECT sandbox_namespace, sandbox_name, sandbox_uid, runner_session_id, source_id, last_cursor "
                    "FROM session_history WHERE id = :id"
                ),
                {"id": settings.session_id},
            )
        ).one_or_none()
    if history is None or history.last_cursor < settings.through:
        raise VerificationError("archive missing or behind requested watermark")
    if settings.through and not history.source_id:
        raise VerificationError("nonempty archive lacks source identity")
    source_id = history.source_id
    end = min(settings.through, settings.after + settings.batch_size * settings.max_batches)
    runner = None
    attachment = None
    try:
        if settings.mode == "archive":
            if source is None:
                raise VerificationError("app database connection required")
            async with read_primary(source) as connection:
                locator = (
                    await connection.execute(
                        text("SELECT sandbox, session_id FROM event_log WHERE id = :id"), {"id": settings.session_id}
                    )
                ).one_or_none()
            if (
                locator is None
                or locator.sandbox != history.sandbox_name
                or not (
                    locator.session_id == history.runner_session_id
                    or (
                        locator.session_id == str(settings.session_id)
                        and history.runner_session_id == f"r-{settings.session_id}"
                    )
                )
            ):
                raise VerificationError("app/service locator mismatch")
        else:
            if not history.runner_session_id or settings.runner_target is None:
                raise VerificationError("runner locator and target required")
            runner = RunnerClient(grpc.aio.insecure_channel(settings.runner_target))
            summaries = await runner.list_sessions()
            if not any(row.session_id == history.runner_session_id for row in summaries):
                raise VerificationError("runner Session not found; refusing to Open")
            # No spec, setup script or Command: attach only to an existing runner Session.
            attachment = await runner.attach(history.runner_session_id, after_cursor=settings.after)
            if attachment.attached.last_cursor < settings.through:
                raise VerificationError("runner is behind requested overlap watermark")
        cursor = settings.after
        while cursor < end:
            stop = min(end, cursor + settings.batch_size)
            archived = await read_archive(destination, settings.session_id, cursor, stop)
            if source is not None and settings.mode == "archive":
                async with read_primary(source) as connection:
                    rows = (
                        await connection.execute(
                            text(
                                "SELECT cursor, payload::text AS payload FROM event WHERE thread_id = :id "
                                "AND cursor > :after AND cursor <= :through ORDER BY cursor"
                            ),
                            {"id": settings.session_id, "after": cursor, "through": stop},
                        )
                    ).all()
                if [row.cursor for row in rows] != list(range(cursor + 1, stop + 1)):
                    raise VerificationError(f"app gap in ({cursor}, {stop}]")
                observed = [ParseDict(json.loads(row.payload), event_log_pb2.EventEntry()) for row in rows]
            else:
                assert attachment is not None
                observed = [await attachment.next_entry() for _ in archived]
            for index, (left, right) in enumerate(zip(observed, archived, strict=True), start=cursor + 1):
                compare_entry(left, right, index, source_id)
            cursor = stop
            print(
                json.dumps(
                    {
                        "mode": settings.mode,
                        "session_id": str(settings.session_id),
                        "source_id": source_id,
                        "verified_after": settings.after,
                        "verified_through": cursor,
                        "requested_through": settings.through,
                        "sandbox_namespace": history.sandbox_namespace,
                        "sandbox_name": history.sandbox_name,
                        "stored_sandbox_uid": str(history.sandbox_uid) if history.sandbox_uid else None,
                        "runner_session_id": history.runner_session_id,
                    }
                ),
                flush=True,
            )
        return cursor
    except ParseError, DecodeError, json.JSONDecodeError:
        raise VerificationError("invalid Event encoding in the requested range") from None
    finally:
        if attachment is not None:
            attachment.cancel()
        if runner is not None:
            await runner.close()


async def async_main() -> None:
    settings = Settings()
    destination = create_async_engine(settings.database_url, hide_parameters=True)
    source = create_async_engine(settings.app_database_url, hide_parameters=True) if settings.app_database_url else None
    try:
        async with asyncio.timeout(settings.timeout_s):
            cursor = await verify(settings, destination, source)
        print(
            json.dumps(
                {
                    "complete_range": cursor == settings.through,
                    "next_after": cursor,
                    "requested_through": settings.through,
                }
            ),
            flush=True,
        )
        if cursor < settings.through:
            raise SystemExit(3)  # Bounded work completed; resume explicitly, not an automatic loop.
    finally:
        await destination.dispose()
        if source is not None:
            await source.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
