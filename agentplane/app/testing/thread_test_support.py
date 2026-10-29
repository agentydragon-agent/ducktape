"""HTTP observations and mutations of real Go app Threads."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from google.protobuf.timestamp_pb2 import Timestamp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_delay, wait_fixed

from agentplane.app.testing.models import ThreadPage, ThreadView
from agentplane.proto import event_log_pb2, event_pb2, runner_pb2

SPEC = runner_pb2.SessionSpec(
    harness=runner_pb2.HARNESS_CLAUDE, cwd="/state/work", model="test-model", reasoning_effort="low"
)


def event_entry(cursor: int, **observation: object) -> event_log_pb2.EventEntry:
    at = Timestamp()
    at.FromDatetime(datetime(2026, 9, 2, 12, 0, tzinfo=UTC) + timedelta(seconds=cursor))
    event = event_pb2.Event(at=at, **observation)  # type: ignore[arg-type]
    return event_log_pb2.EventEntry(
        cursor=cursor, origin=event_log_pb2.EventOrigin(source_id="test-runner", sequence=cursor), event=event
    )


class ThreadHTTP:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def wait(self, thread_id: UUID) -> None:
        async for attempt in AsyncRetrying(
            stop=stop_after_delay(15), wait=wait_fixed(0.05), retry=retry_if_exception_type(AssertionError)
        ):
            with attempt:
                response = await self.http.get(f"/threads/{thread_id}")
                assert response.status_code == 200, response.text

    async def rename(self, thread_id: UUID, name: str) -> None:
        await self.wait(thread_id)
        response = await self.http.patch(f"/threads/{thread_id}", json={"name": name})
        response.raise_for_status()

    async def archive(self, thread_id: UUID) -> None:
        response = await self.http.post(f"/threads/{thread_id}/archive")
        response.raise_for_status()

    async def list_threads(self, *, sandbox: str | None = None) -> list[ThreadView]:
        params = {"include_archived": "true"}
        if sandbox is not None:
            params["sandbox"] = sandbox
        threads: list[ThreadView] = []
        while True:
            response = await self.http.get("/threads", params=params)
            response.raise_for_status()
            page = ThreadPage.model_validate(response.json())
            threads.extend(page.threads)
            if page.next_page_token is None:
                return threads
            params["page_token"] = page.next_page_token
