"""Signed App delivery, durable replay, provider matching, and access boundaries."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import create_autospec, patch
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import pytest_bazel
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import JsonValue, SecretStr, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.notification_service.api import authenticated_caller, create_app
from agentplane.notification_service.database_migrate import RUNNER
from agentplane.notification_service.db import GitHubDelivery, Subscription
from agentplane.notification_service.models import DestinationRef, Subscribe, SubscriptionUpdate
from agentplane.notification_service.service import Service
from agentplane.notification_service.settings import CONFIG_FILE_ENV, GitHubSettings, Settings
from agentplane.notification_service.sources.actions import Actions
from agentplane.notification_service.sources.github import GitHub, GitHubRetryError, GitHubUnavailableError, Repository
from agentplane.notification_service.sources.github_models import (
    BranchSubject,
    CommitSubject,
    EventFilter,
    EventName,
    GitHubSource,
    PullRequestSubject,
)
from agentplane.notification_service.store import ConflictError, NotFoundError, Store
from agentplane.sandbox_service.client import SandboxServiceClient
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.principal import WorkloadPrincipal, WorkloadPrincipalResolver

HEAD = "a" * 40
NEXT = "b" * 40
SECRET = b"fixture-signing-secret-not-a-real-secret"
PRINCIPAL = WorkloadPrincipal("test", "owner", "system:serviceaccount:test:owner", "pod", "uid")
SOURCE = GitHubSource(
    provider="github", repository="owner/repo", subject=PullRequestSubject(kind="pull_request", number=7)
)


def subscription(source: GitHubSource = SOURCE, key: str = "follow") -> Subscribe:
    return Subscribe(
        destination_ref=DestinationRef(namespace="test", name="sandbox", uid="uid"),
        session_id="session",
        idempotency_key=key,
        source=source,
    )


def comment(number: int = 7) -> dict[str, JsonValue]:
    return {
        "action": "created",
        "installation": {"id": 11},
        "repository": {"id": 100, "full_name": "owner/repo"},
        "issue": {"number": number, "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/7"}},
        "comment": {"body": "kept verbatim"},
    }


def check(sha: str = HEAD) -> dict[str, JsonValue]:
    return {
        "action": "completed",
        "installation": {"id": 11},
        "repository": {"id": 100, "full_name": "owner/repo"},
        "check_run": {"head_sha": sha, "pull_requests": []},
    }


def signed(payload: dict[str, JsonValue], event: str, delivery: UUID | None = None) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    return raw, {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": str(delivery or uuid4()),
        "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest(),
    }


@dataclass
class Upstream:
    public_key: bytes
    head: str | None = HEAD
    revoked: bool = False
    limited: bool = False
    fork: bool = False
    requests: list[str] = field(default_factory=list)
    responses: dict[str, httpx.Response] = field(default_factory=dict)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        path = request.url.path
        self.requests.append(path)
        if path.endswith(("/installation", "/access_tokens")):
            claims = jwt.decode(request.headers["Authorization"][7:], self.public_key, algorithms=["RS256"])
            assert claims["iss"] == "42"
        if path in self.responses:
            return self.responses[path]
        if self.limited:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "retry-after": "120"})
        if self.revoked:
            return httpx.Response(404)
        fork = "/fork/repo" in path
        if path.endswith("/installation"):
            return httpx.Response(200, json={"id": 22 if fork else 11})
        if path.endswith("/access_tokens"):
            permissions = json.loads(request.content)["permissions"]
            assert all(value == "read" for value in permissions.values())
            return httpx.Response(
                201,
                json={
                    "token": "fixture-installation-token",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        assert request.headers["Authorization"] == "Bearer fixture-installation-token"
        if path in {"/repos/owner/repo", "/repos/fork/repo"}:
            return httpx.Response(
                200, json={"id": 200 if fork else 100, "full_name": "fork/repo" if fork else "owner/repo"}
            )
        if "/pulls/" in path:
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "head": {
                        "sha": self.head,
                        "repo": {
                            "id": 200 if self.fork else 100,
                            "full_name": "fork/repo" if self.fork else "owner/repo",
                        },
                    },
                },
            )
        if "/git/ref/" in path:
            return (
                httpx.Response(404) if self.head is None else httpx.Response(200, json={"object": {"sha": self.head}})
            )
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": path.rsplit("/", 1)[1]})
        raise AssertionError(path)


@pytest.fixture
async def provider() -> AsyncIterator[tuple[GitHub, Upstream]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    upstream = Upstream(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    settings = GitHubSettings(app_id=42, private_key=SecretStr(private), webhook_secret=SecretStr(SECRET.decode()))
    async with httpx.AsyncClient(
        base_url="https://api.github.test", transport=httpx.MockTransport(upstream.handle)
    ) as http:
        github = GitHub(http, settings)
        github.start()
        yield github, upstream


async def ingest(github: GitHub, store: Store, payload: dict[str, JsonValue], event: str = "issue_comment") -> None:
    raw, headers = signed(payload, event)
    await github.ingest(store, event, UUID(headers["X-GitHub-Delivery"]), headers["X-Hub-Signature-256"], raw)


async def test_signed_http_durable_acceptance_and_disabled_provider(
    store: Store, provider: tuple[GitHub, Upstream]
) -> None:
    github, _ = provider
    service = Service(store, create_autospec(Actions), create_autospec(SandboxServiceClient), github)
    app = create_app(service, create_autospec(WorkloadPrincipalResolver))
    app.dependency_overrides[authenticated_caller] = lambda: PRINCIPAL
    raw, headers = signed(comment(), "issue_comment")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://notifications") as client:
        assert "github" in (await client.get("/v1/sources")).json()
        assert (
            await client.post("/v1/webhooks/github", content=raw, headers=headers | {"X-Hub-Signature-256": "bad"})
        ).status_code == 401
        assert (
            await client.post(
                "/v1/webhooks/github", content=b"x" * (github.settings.max_body_bytes + 1), headers=headers
            )
        ).status_code == 413
        with patch.object(Store, "ingest_github", side_effect=ConnectionError("database unavailable")):
            assert (await client.post("/v1/webhooks/github", content=raw, headers=headers)).status_code == 503
        for _ in range(github.settings.webhook_concurrency):
            await github.ingress_slots.acquire()
        try:
            assert (await client.post("/v1/webhooks/github", content=raw, headers=headers)).status_code == 503
        finally:
            for _ in range(github.settings.webhook_concurrency):
                github.ingress_slots.release()
        first = await client.post("/v1/webhooks/github", content=raw, headers=headers)
        assert first.status_code == 202
        assert first.json() == {"accepted": True, "duplicate": False}
        assert (await client.post("/v1/webhooks/github", content=raw, headers=headers)).json()["duplicate"]
        changed, changed_headers = signed(comment(8), "issue_comment", UUID(headers["X-GitHub-Delivery"]))
        assert (await client.post("/v1/webhooks/github", content=changed, headers=changed_headers)).status_code == 409
        malformed, malformed_headers = signed({"installation": {"id": 11}}, "issue_comment")
        assert (
            await client.post("/v1/webhooks/github", content=malformed, headers=malformed_headers)
        ).status_code == 400
        for event in ["check_suite", "unknown_event"]:
            # Event selection comes from the header; a check_run body must not select its own model.
            mismatched, mismatched_headers = signed(check(), event)
            assert (
                await client.post("/v1/webhooks/github", content=mismatched, headers=mismatched_headers)
            ).status_code == 400
        service.github = None
        assert "github" not in (await client.get("/v1/sources")).json()
        assert (await client.post("/v1/webhooks/github", content=raw, headers=headers)).status_code == 404
    async with store.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GitHubDelivery)) == 1
        delivery = await session.scalar(select(GitHubDelivery))
        assert delivery is not None
        assert delivery.payload == comment()


@pytest.mark.parametrize(
    "values", [{"actions_after_sequence": 0}, {"github_start_position": None}, {"github_binding": None}]
)
async def test_github_subscription_state_is_source_specific(
    store: Store, provider: tuple[GitHub, Upstream], values: dict[str, int | None]
) -> None:
    github, _ = provider
    sub = await store.subscribe(PRINCIPAL, subscription(), (await github.context(SOURCE)).binding)
    with pytest.raises(IntegrityError, match="subscription_source_state"):
        async with store.sessions.begin() as session:
            await session.execute(update(Subscription).where(Subscription.id == sub.id).values(**values))


@pytest.mark.parametrize("name", ["owner/repo", "o/" + "r" * 198])
def test_repository_names_accept_valid_names(name: str) -> None:
    assert Repository(id=1, full_name=name).full_name == name
    assert GitHubSource(provider="github", repository=name, subject=SOURCE.subject).repository == name


@pytest.mark.parametrize("name", ["repo", "owner/repo/extra", "owner/repo name", "o/" + "r" * 199])
def test_repository_names_reject_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        Repository(id=1, full_name=name)
    with pytest.raises(ValidationError):
        GitHubSource(provider="github", repository=name, subject=SOURCE.subject)


async def test_replay_boundary_overlapping_matches_and_revocation(
    store: Store, engine: AsyncEngine, provider: tuple[GitHub, Upstream]
) -> None:
    github, upstream = provider
    await ingest(github, store, comment())  # Before subscription boundary: not a historical replay.
    binding = (await github.context(SOURCE)).binding
    first = await store.subscribe(PRINCIPAL, subscription(), binding)
    second = await store.subscribe(PRINCIPAL, subscription(key="overlap"), binding)
    await ingest(github, store, comment(8))
    await ingest(github, store, comment())
    claim = await store.claim()
    assert claim is not None
    # A fresh provider/Store can finish fanout after HTTP acceptance; no in-memory queue is needed.
    recovered = Store(engine)
    for identity in [first.id, second.id]:
        async with recovered.sessions() as session:
            row = await session.get(Subscription, identity)
        assert row is not None
        await github.reconcile(recovered, claim, row, SOURCE)
    page = await store.read(PRINCIPAL.account, first.inbox_id, 0, 128)
    assert len(page.entries) == 1
    assert set(page.entries[0].subscriptions) == {first.id, second.id}
    assert page.entries[0].payload == comment()
    assert page.inbox.acknowledged == 0
    notice = await store.notice(claim)
    assert notice is not None
    assert notice.through_cursor == 1
    page = await store.read(PRINCIPAL.account, first.inbox_id, 0, 128)
    with pytest.raises(NotFoundError):
        await store.read(ServiceAccountRef(namespace="test", name="other"), first.inbox_id, 0, 128)
    await ingest(github, store, comment())
    async with store.sessions() as session:
        row = await session.get(Subscription, first.id)
    assert row is not None
    upstream.revoked = True
    with pytest.raises(GitHubUnavailableError):
        await github.reconcile(store, claim, row, SOURCE)
    after = await store.read(PRINCIPAL.account, first.inbox_id, 0, 128)
    assert after.entries == page.entries
    assert after.inbox == page.inbox
    upstream.revoked = False
    upstream.limited = True
    with pytest.raises(GitHubRetryError) as error:
        await github.context(SOURCE)
    assert error.value.retry_seconds == 120


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/repos/fork/repo/installation", 401),
        ("/repos/fork/repo/installation", 403),
        ("/app/installations/22/access_tokens", 401),
        ("/app/installations/22/access_tokens", 403),
        ("/app/installations/22/access_tokens", 404),
        ("/repos/fork/repo", 404),
    ],
)
async def test_fork_access_failures_are_not_treated_as_uninstalled(
    provider: tuple[GitHub, Upstream], path: str, status: int
) -> None:
    github, upstream = provider
    upstream.fork = True
    upstream.responses[path] = httpx.Response(status)
    with pytest.raises(GitHubUnavailableError, match=f"HTTP {status}"):
        await github.context(SOURCE)


async def test_uninstalled_fork_is_optional_but_suspension_is_an_error(provider: tuple[GitHub, Upstream]) -> None:
    github, upstream = provider
    upstream.fork = True
    upstream.responses["/repos/fork/repo/installation"] = httpx.Response(404)
    context = await github.context(SOURCE)
    assert context.installations == {100: 11}
    assert context.heads == {HEAD}
    upstream.responses["/repos/fork/repo/installation"] = httpx.Response(
        200, json={"id": 22, "suspended_at": datetime.now(UTC).isoformat()}
    )
    with pytest.raises(GitHubUnavailableError, match="suspended"):
        await github.context(SOURCE)


async def test_filter_order_and_duplicates_do_not_change_subscription_identity(
    store: Store, provider: tuple[GitHub, Upstream]
) -> None:
    github, _ = provider
    source = GitHubSource(
        provider="github",
        repository=SOURCE.repository,
        subject=SOURCE.subject,
        events={
            EventFilter(event=EventName.ISSUE_COMMENT, actions={"created", "edited"}),
            EventFilter(event=EventName.CHECK_RUN, actions={"completed"}),
        },
    )
    body = subscription(source)
    binding = (await github.context(source)).binding
    original = await store.subscribe(PRINCIPAL, body, binding)
    # Alter ordering and duplicates at the JSON request boundary, not in typed sets.
    wire = json.loads(body.model_dump_json())
    filters = wire["source"]["events"]
    filters.reverse()
    for event_filter in filters:
        event_filter["actions"].reverse()
        event_filter["actions"].append(event_filter["actions"][0])
    filters.append(filters[0])
    retry = Subscribe.model_validate(wire)
    assert retry.model_dump(mode="json") == body.model_dump(mode="json")
    assert (await store.subscribe(PRINCIPAL, retry, binding)).id == original.id
    # Existing noncanonical JSON is interpreted using the same set semantics.
    async with store.sessions.begin() as session:
        row = await session.get(Subscription, original.id)
        assert row is not None
        row.creation = wire
    assert (await store.subscribe(PRINCIPAL, body, binding)).id == original.id
    filters[0]["actions"] = ["deleted"]
    with pytest.raises(ConflictError):
        await store.subscribe(PRINCIPAL, Subscribe.model_validate(wire), binding)


@pytest.mark.parametrize("kind", ["pull_request", "branch"])
@pytest.mark.parametrize("ci_first", [True, False])
async def test_late_correlation_survives_restart_and_does_not_block_other_events(
    store: Store, engine: AsyncEngine, provider: tuple[GitHub, Upstream], kind: str, ci_first: bool
) -> None:
    github, upstream = provider
    source = (
        SOURCE
        if kind == "pull_request"
        else SOURCE.model_copy(update={"subject": BranchSubject(kind="branch", name="devel")})
    )
    base: dict[str, JsonValue] = {"installation": {"id": 11}, "repository": {"id": 100, "full_name": "owner/repo"}}
    association = (
        base | {"action": "synchronize", "pull_request": {"number": 7, "head": {"sha": NEXT}}}
        if kind == "pull_request"
        else base | {"ref": "refs/heads/devel", "after": NEXT}
    )
    event = "pull_request" if kind == "pull_request" else "push"
    # A later association must not pull receipts from before subscription creation into the inbox.
    await ingest(github, store, check(NEXT), "check_run")
    sub = await store.subscribe(PRINCIPAL, subscription(source), (await github.context(source)).binding)
    if ci_first:
        await ingest(github, store, check(NEXT), "check_run")
    else:
        await ingest(github, store, association, event)
    # No prefix cap: unrelated receipts must not hide a definite match farther into the journal.
    for _ in range(130):
        await ingest(github, store, check("c" * 40), "check_run")
    await ingest(github, store, check(HEAD), "check_run")
    claim = await store.claim()
    assert claim is not None
    row = await store.source(claim)
    assert row is not None
    boundary = row.github_start_position
    await github.reconcile(store, claim, row, source)
    page = await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)
    assert [entry.payload for entry in page.entries] == ([check(HEAD)] if ci_first else [association, check(HEAD)])
    async with store.sessions() as session:
        assert await session.scalar(select(Subscription.next_attempt).where(Subscription.id == sub.id)) is None
    await store.release(claim, None)
    # The next association/receipt arrives long after the former grace window, with fresh objects.
    async with store.sessions.begin() as session:
        await session.execute(update(GitHubDelivery).values(received_at=datetime.now(UTC) - timedelta(days=2)))
    recovered = Store(engine)
    restarted = GitHub(github.http, github.settings)
    if ci_first:
        await ingest(restarted, recovered, association, event)
    else:
        await ingest(restarted, recovered, check(NEXT), "check_run")
    # Upstream has already moved on: only durable webhook evidence can associate NEXT.
    upstream.head = "d" * 40
    claim = await recovered.claim()
    assert claim is not None
    row = await recovered.source(claim)
    assert row is not None
    await restarted.reconcile(recovered, claim, row, source)
    page = await recovered.read(PRINCIPAL.account, sub.inbox_id, 0, 128)
    assert len(page.entries) == 3
    assert sum(entry.payload == check(NEXT) for entry in page.entries) == 1
    async with recovered.sessions() as session:
        row = await session.get(Subscription, sub.id)
    assert row is not None
    assert row.github_start_position == boundary
    assert row.next_attempt is None
    await restarted.reconcile(recovered, claim, row, source)
    assert (await recovered.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).entries == page.entries


async def test_matching_pages_and_old_head_associations_are_not_capped(
    store: Store, provider: tuple[GitHub, Upstream]
) -> None:
    github, _ = provider
    source = SOURCE.model_copy(update={"events": {EventFilter(event=EventName.CHECK_RUN, actions={"completed"})}})
    # Association history predates this subscription and is longer than a delivery page.
    for index in range(130):
        await ingest(
            github,
            store,
            {
                "installation": {"id": 11},
                "repository": {"id": 100, "full_name": "owner/repo"},
                "action": "synchronize",
                "pull_request": {"number": 7, "head": {"sha": f"{index:040x}"}},
            },
            "pull_request",
        )
    sub = await store.subscribe(PRINCIPAL, subscription(source), (await github.context(source)).binding)
    await ingest(github, store, check(f"{1:040x}") | {"action": "created"}, "check_run")
    for _ in range(130):
        await ingest(github, store, check(f"{1:040x}"), "check_run")
    claim = await store.claim()
    assert claim is not None
    row = await store.source(claim)
    assert row is not None
    await github.reconcile(store, claim, row, source)
    assert (await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).inbox.last_cursor == 128
    row = await store.source(claim)
    assert row is not None  # Full matching page schedules immediate continuation.
    await github.reconcile(store, claim, row, source)
    page = await store.read(PRINCIPAL.account, sub.inbox_id, 128, 128)
    assert len(page.entries) == 2
    assert page.inbox.last_cursor == 130
    assert await store.source(claim) is None


async def test_retained_fork_receipt_requires_current_installation_access(
    store: Store, provider: tuple[GitHub, Upstream]
) -> None:
    github, upstream = provider
    upstream.fork = True
    sub = await store.subscribe(PRINCIPAL, subscription(), (await github.context(SOURCE)).binding)
    payload = check(NEXT) | {"repository": {"id": 200, "full_name": "fork/repo"}, "installation": {"id": 22}}
    await ingest(github, store, payload, "check_run")
    # Same SHA in an unrelated installation must never be admitted.
    await ingest(github, store, payload | {"installation": {"id": 33}}, "check_run")
    upstream.head = NEXT
    upstream.responses["/repos/fork/repo/installation"] = httpx.Response(404)
    claim = await store.claim()
    assert claim is not None
    row = await store.source(claim)
    assert row is not None
    await github.reconcile(store, claim, row, SOURCE)
    assert not (await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).entries
    del upstream.responses["/repos/fork/repo/installation"]
    await ingest(github, store, comment())
    row = await store.source(claim)
    assert row is not None
    await github.reconcile(store, claim, row, SOURCE)
    page = await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)
    assert [entry.payload for entry in page.entries] == [payload, comment()]


@pytest.mark.parametrize("kind", ["branch", "commit"])
async def test_branch_activity_and_fixed_commit(store: Store, provider: tuple[GitHub, Upstream], kind: str) -> None:
    github, upstream = provider
    subject = BranchSubject(kind="branch", name="devel") if kind == "branch" else CommitSubject(kind="commit", sha=HEAD)
    source = SOURCE.model_copy(update={"subject": subject})
    sub = await store.subscribe(PRINCIPAL, subscription(source), (await github.context(source)).binding)
    base: dict[str, JsonValue] = {"installation": {"id": 11}, "repository": {"id": 100, "full_name": "owner/repo"}}
    await ingest(github, store, base | {"ref": "refs/heads/devel", "after": HEAD}, "push")
    upstream.head = NEXT
    await ingest(github, store, check(HEAD), "check_run")
    await ingest(github, store, base | {"ref": "devel", "ref_type": "branch"}, "delete")
    if kind == "branch":
        upstream.head = None
    else:
        # A fixed-SHA mismatch cannot become a match later.
        await ingest(github, store, check(NEXT), "check_run")
    claim = await store.claim()
    assert claim is not None
    async with store.sessions() as session:
        row = await session.get(Subscription, sub.id)
    assert row is not None
    await github.reconcile(store, claim, row, source)
    assert len((await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).entries) == (3 if kind == "branch" else 1)
    if kind == "commit":
        async with store.sessions() as session:
            assert await session.scalar(select(Subscription.next_attempt).where(Subscription.id == sub.id)) is None


@pytest.mark.parametrize(
    "event", [EventName.CHECK_RUN, EventName.CHECK_SUITE, EventName.STATUS, EventName.WORKFLOW_RUN]
)
async def test_native_ci_references_supply_durable_associations(
    store: Store, provider: tuple[GitHub, Upstream], event: EventName
) -> None:
    github, _ = provider
    source = (
        SOURCE
        if event in {EventName.CHECK_RUN, EventName.CHECK_SUITE}
        else SOURCE.model_copy(update={"subject": BranchSubject(kind="branch", name="devel")})
    )
    explicit = source.model_copy(update={"events": {EventFilter(event=event)}})
    binding = (await github.context(source)).binding
    default_sub = await store.subscribe(PRINCIPAL, subscription(source), binding)
    explicit_sub = await store.subscribe(PRINCIPAL, subscription(explicit, key="explicit"), binding)
    payload: dict[str, JsonValue] = {"installation": {"id": 11}, "repository": {"id": 100, "full_name": "owner/repo"}}
    match event:
        case EventName.CHECK_RUN | EventName.CHECK_SUITE:
            payload |= {"action": "completed", event: {"head_sha": NEXT, "pull_requests": [{"number": 7}]}}
        case EventName.STATUS:
            payload |= {"sha": NEXT, "branches": [{"name": "devel"}]}
        case EventName.WORKFLOW_RUN:
            payload |= {"action": "completed", "workflow_run": {"head_sha": NEXT, "head_branch": "devel"}}
    # The empty-reference check arrives before its association, and upstream still reports HEAD.
    await ingest(github, store, check(NEXT), "check_run")
    await ingest(github, store, payload, event)
    claim = await store.claim()
    assert claim is not None
    for sub, spec in [(default_sub, source), (explicit_sub, explicit)]:
        async with store.sessions() as session:
            row = await session.get(Subscription, sub.id)
        assert row is not None
        await github.reconcile(store, claim, row, spec)
    page = await store.read(PRINCIPAL.account, default_sub.inbox_id, 0, 128)
    assert len(page.entries) == 2
    first, second = page.entries
    assert first.payload == check(NEXT)
    assert second.payload == payload
    assert (default_sub.id in second.subscriptions) == (event in {EventName.CHECK_RUN, EventName.STATUS})
    assert explicit_sub.id in second.subscriptions


async def test_cancellation_fences_accepted_github_work(store: Store, provider: tuple[GitHub, Upstream]) -> None:
    github, _ = provider
    sub = await store.subscribe(PRINCIPAL, subscription(), (await github.context(SOURCE)).binding)
    await ingest(github, store, comment())
    claim = await store.claim()
    assert claim is not None
    async with store.sessions() as session:
        row = await session.get(Subscription, sub.id)
    assert row is not None
    await store.change(PRINCIPAL.account, sub.id, None)
    await github.reconcile(store, claim, row, SOURCE)
    assert not (await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).entries
    assert await store.source(claim) is None


async def test_webhook_wakes_idle_source_and_fences_concurrent_ingress(
    store: Store, provider: tuple[GitHub, Upstream]
) -> None:
    github, _ = provider
    sub = await store.subscribe(PRINCIPAL, subscription(), (await github.context(SOURCE)).binding)
    claim = await store.claim()
    assert claim is not None
    row = await store.source(claim)
    assert row is not None
    await github.reconcile(store, claim, row, SOURCE)
    await store.release(claim, None)
    assert await store.get_next_work_at() is None  # No GitHub polling deadline while idle.
    await store.change(PRINCIPAL.account, sub.id, SubscriptionUpdate(version=sub.version, lifetime_days=7))
    claim = await store.claim()
    assert claim is not None
    row = await store.source(claim)
    assert row is not None  # Renewal also schedules an idle source, without waiting for a webhook.
    await github.reconcile(store, claim, row, SOURCE)
    await store.release(claim, None)
    assert await store.get_next_work_at() is None
    async with store.wakeups.listener.listen():
        with store.wakeups.subscribe() as changed:
            await ingest(github, store, comment())
            async with asyncio.timeout(10):
                await changed.wait()
        claim = await store.claim()
        assert claim is not None
        source = await store.source(claim)
        assert source is not None
        # Simulate another receipt committed after the worker took its source snapshot.
        await ingest(github, store, comment())
        await store.record_github(claim, source, [], more=False)
        await store.release(claim, None)
        claim = await store.claim()
        assert claim is not None
        source = await store.source(claim)
        assert source is not None
        await github.reconcile(store, claim, source, SOURCE)
        assert len((await store.read(PRINCIPAL.account, sub.inbox_id, 0, 128)).entries) == 2
        async with store.sessions() as session:
            source = await session.get(Subscription, sub.id)
            assert source is not None
            assert source.next_attempt is None


async def test_github_data_prevents_lossy_downgrade(
    store: Store, engine: AsyncEngine, provider: tuple[GitHub, Upstream]
) -> None:
    github, _ = provider
    await ingest(github, store, comment())

    def downgrade(connection: Connection) -> None:
        config = Config()
        config.set_main_option("script_location", str(RUNNER.migrations_dir))
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="refusing data loss"):
            command.downgrade(config, "0004_source_union")

    async with engine.begin() as connection:
        await connection.run_sync(downgrade)
    async with store.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GitHubDelivery)) == 1


def test_yaml_settings_and_secret_separation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""namespace: test
actions:
  url: http://actions
  token_file: /tokens/actions
sandbox_service:
  target: sandboxes:8080
  token_file: /tokens/sandboxes
github: null
""")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    settings = Settings(database_url="postgresql://unused", _cli_parse_args=False)
    assert settings.actions.url == "http://actions"
    assert settings.actions.token_file == Path("/tokens/actions")
    assert settings.sandbox_service.target == "sandboxes:8080"
    assert settings.sandbox_service.token_file == Path("/tokens/sandboxes")
    assert settings.github is None
    config.write_text(config.read_text().replace("github: null\n", ""))
    assert Settings(database_url="postgresql://unused", _cli_parse_args=False).github is None
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_SANDBOX_SERVICE__TARGET", "overridden-sandboxes:8080")
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_ACTIONS__URL", "http://overridden-actions")
    settings = Settings(database_url="postgresql://unused", _cli_parse_args=False)
    assert settings.actions.url == "http://overridden-actions"
    assert settings.sandbox_service.target == "overridden-sandboxes:8080"
    assert settings.sandbox_service.token_file == Path("/tokens/sandboxes")
    # A present mapping enables GitHub and must be complete; secrets overlay public YAML.
    with config.open("a") as file:
        file.write("github:\n  app_id: 42\n")
    with pytest.raises(ValidationError, match="Field required"):
        Settings(database_url="postgresql://unused", _cli_parse_args=False)
    private = "fixture-private-key\nmultiline"
    secret = "fixture-webhook-secret-that-is-long-enough"
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_GITHUB__PRIVATE_KEY", private)
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_GITHUB__WEBHOOK_SECRET", secret)
    settings = Settings(database_url="postgresql://unused", _cli_parse_args=False)
    assert settings.github is not None
    assert settings.github.app_id == 42
    assert settings.github.private_key.get_secret_value() == private
    assert settings.github.webhook_secret.get_secret_value() == secret
    assert private not in repr(settings)
    assert secret not in settings.model_dump_json()
    # Nested environment fields contribute presence even when YAML says null.
    config.write_text(config.read_text().replace("github:\n  app_id: 42\n", "github: null\n"))
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_GITHUB__APP_ID", "42")
    assert Settings(database_url="postgresql://unused", _cli_parse_args=False).github is not None
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_GITHUB__WEBHOOK_SECRET", "too-short-secret")
    with pytest.raises(ValidationError) as failure:
        Settings(database_url="postgresql://unused", _cli_parse_args=False)
    assert "too-short-secret" not in str(failure.value)
    config.unlink()
    with pytest.raises(ValueError, match="regular file"):
        Settings(database_url="postgresql://unused", _cli_parse_args=False)


if __name__ == "__main__":
    pytest_bazel.main()
