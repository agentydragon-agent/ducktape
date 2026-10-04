"""GitHub App authentication, signed ingress, and provider-owned subject matching."""

import asyncio
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, TypeAdapter

from agentplane.notification_service.db import GitHubDelivery, Inbox, Subscription
from agentplane.notification_service.sources.github_models import (
    CI_EVENTS,
    PR_EVENTS,
    REF_EVENTS,
    BranchSubject,
    CommitSubject,
    EventName,
    GitHubBinding,
    GitHubEvent,
    GitHubSource,
    PullRequestSubject,
)
from agentplane.notification_service.settings import GitHubSettings
from agentplane.notification_service.store import Store

# RS256 is loaded dynamically by PyJWT.
# gazelle:include_dep @pypi//cryptography

logger = logging.getLogger(__name__)

_PAYLOAD = TypeAdapter(dict[str, JsonValue])
LIFECYCLE_EVENTS = {"installation", "installation_repositories"}
SUPPORTED_EVENTS = CI_EVENTS | PR_EVENTS | REF_EVENTS


class GitHubUnavailableError(Exception):
    """Disabled provider or confirmed loss of repository/installation access."""


class GitHubNotInstalledError(GitHubUnavailableError):
    """The App's installation lookup returned 404 for this repository."""


class GitHubRetryError(Exception):
    def __init__(self, retry_seconds: int = 60) -> None:
        self.retry_seconds = retry_seconds
        super().__init__("GitHub temporarily unavailable")


class InvalidSignatureError(Exception):
    pass


class Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class Installation(Upstream):
    id: int = Field(gt=0)
    suspended_at: datetime | None = None


class Repository(Upstream):
    id: int = Field(gt=0)
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)


class Envelope(Upstream):
    installation: Installation
    repository: Repository | None = None
    action: str | None = Field(default=None, max_length=64)


class Revision(Upstream):
    sha: str
    repo: Repository | None = None


class PullRequest(Upstream):
    number: int
    head: Revision


class PullRequestPayload(Envelope):
    pull_request: PullRequest


class Issue(Upstream):
    number: int
    pull_request: dict[str, JsonValue] | None = None


class IssuePayload(Envelope):
    issue: Issue


class PullReference(Upstream):
    number: int


class Check(Upstream):
    head_sha: str
    pull_requests: list[PullReference] = Field(default_factory=list)


class CheckRunPayload(Envelope):
    check_run: Check


class CheckSuitePayload(Envelope):
    check_suite: Check


class Workflow(Check):
    head_branch: str | None = None


class WorkflowPayload(Envelope):
    workflow_run: Workflow


class Branch(Upstream):
    name: str


class StatusPayload(Envelope):
    sha: str
    branches: list[Branch] = Field(default_factory=list)


class PushPayload(Envelope):
    ref: str
    after: str


class RefPayload(Envelope):
    ref: str
    ref_type: Literal["branch", "tag"]


class GitRef(Upstream):
    object: Revision


class Commit(Upstream):
    sha: str


class Token(Upstream):
    token: SecretStr
    expires_at: datetime


@dataclass
class Context:
    binding: GitHubBinding
    installations: dict[int, int]
    heads: set[str]


def validate_payload(event: str, payload: dict[str, JsonValue]) -> Envelope:
    match event:
        case EventName.PULL_REQUEST | EventName.PULL_REQUEST_REVIEW | EventName.PULL_REQUEST_REVIEW_COMMENT:
            return PullRequestPayload.model_validate(payload)
        case EventName.ISSUE_COMMENT:
            return IssuePayload.model_validate(payload)
        case EventName.CHECK_RUN:
            return CheckRunPayload.model_validate(payload)
        case EventName.CHECK_SUITE:
            return CheckSuitePayload.model_validate(payload)
        case EventName.WORKFLOW_RUN:
            return WorkflowPayload.model_validate(payload)
        case EventName.STATUS:
            return StatusPayload.model_validate(payload)
        case EventName.PUSH:
            return PushPayload.model_validate(payload)
        case EventName.CREATE | EventName.DELETE:
            return RefPayload.model_validate(payload)
        case _:
            return Envelope.model_validate(payload)


class GitHub:
    def __init__(self, http: httpx.AsyncClient, settings: GitHubSettings) -> None:
        self.http, self.settings = http, settings
        self.tokens: dict[int, Token] = {}
        self.token_lock = asyncio.Lock()
        self.ingress_slots = asyncio.Semaphore(settings.webhook_concurrency)

    def app_headers(self) -> dict[str, str]:
        private_key = self.settings.private_key.get_secret_value()
        now = int(time.time())
        bearer = jwt.encode(
            {"iat": now - 30, "exp": now + 540, "iss": str(self.settings.app_id)}, private_key, algorithm="RS256"
        )
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def start(self) -> None:
        # Enabled-but-incomplete configuration must fail before HTTP readiness.
        self.app_headers()
        self.signing_secret()

    def signing_secret(self) -> bytes:
        secret = self.settings.webhook_secret.get_secret_value().encode()
        if len(secret) < 32:
            raise ValueError("GitHub signing secret must have at least 32 bytes")
        return secret

    async def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        *,
        json: dict[str, JsonValue] | None = None,
        allow_missing: bool = False,
    ) -> httpx.Response:
        # No redirects: credentials must never follow repository redirects to another origin.
        response = await self.http.request(method, path, headers=headers, json=json)
        if response.status_code == 429 or (
            response.status_code == 403
            and (response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers)
        ):
            delay = response.headers.get("retry-after", "60")
            raise GitHubRetryError(min(3600, max(60, int(delay) if delay.isdecimal() else 60)))
        if allow_missing and response.status_code == 404:
            return response
        if response.status_code == 401:
            self.tokens.clear()
        if response.status_code in (401, 403, 404):
            raise GitHubUnavailableError(
                f"GitHub App access unavailable (HTTP {response.status_code}); check credentials and permissions"
            )
        response.raise_for_status()
        return response

    async def installation_headers(self, installation_id: int) -> dict[str, str]:
        async with self.token_lock:
            token = self.tokens.get(installation_id)
            if token is None or token.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
                response = await self.request(
                    "POST",
                    f"/app/installations/{installation_id}/access_tokens",
                    self.app_headers(),
                    json={"permissions": {"metadata": "read", "contents": "read", "pull_requests": "read"}},
                )
                token = Token.model_validate_json(response.content)
                self.tokens[installation_id] = token
        return {
            "Authorization": f"Bearer {token.token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def repository(self, name: str) -> tuple[GitHubBinding, dict[str, str]]:
        response = await self.request("GET", f"/repos/{name}/installation", self.app_headers(), allow_missing=True)
        if response.status_code == 404:
            raise GitHubNotInstalledError("GitHub App has no accessible installation for this repository")
        installation = Installation.model_validate_json(response.content)
        if installation.suspended_at is not None:
            raise GitHubUnavailableError("GitHub App installation is suspended")
        headers = await self.installation_headers(installation.id)
        repository = Repository.model_validate_json((await self.request("GET", f"/repos/{name}", headers)).content)
        return GitHubBinding(
            app_id=self.settings.app_id, installation_id=installation.id, repository_id=repository.id
        ), headers

    async def context(self, source: GitHubSource) -> Context:
        binding, headers = await self.repository(source.repository)
        context = Context(binding, {binding.repository_id: binding.installation_id}, set())
        match source.subject:
            case PullRequestSubject(number=number):
                pr = PullRequest.model_validate_json(
                    (await self.request("GET", f"/repos/{source.repository}/pulls/{number}", headers)).content
                )
                context.heads.add(pr.head.sha)
                if pr.head.repo is not None and pr.head.repo.id != binding.repository_id:
                    # A base installation does not grant authority over an uninstalled fork.
                    try:
                        fork, _ = await self.repository(pr.head.repo.full_name)
                    except GitHubNotInstalledError as error:
                        logger.warning("PR fork %s is not covered: %s", pr.head.repo.full_name, error)
                    else:
                        if fork.repository_id != pr.head.repo.id:
                            raise GitHubUnavailableError("GitHub fork repository identity changed")
                        context.installations[fork.repository_id] = fork.installation_id
            case BranchSubject(name=name):
                response = await self.request(
                    "GET",
                    f"/repos/{source.repository}/git/ref/heads/{quote(name, safe='')}",
                    headers,
                    allow_missing=True,
                )
                if response.status_code != 404:
                    response.raise_for_status()
                    context.heads.add(GitRef.model_validate_json(response.content).object.sha)
            case CommitSubject(sha=sha):
                commit = Commit.model_validate_json(
                    (await self.request("GET", f"/repos/{source.repository}/commits/{sha}", headers)).content
                )
                if commit.sha != sha:
                    raise GitHubUnavailableError("GitHub commit identity changed")
                context.heads.add(sha)
        return context

    async def ingest(self, store: Store, event: str, delivery_id: UUID, signature: str, raw: bytes) -> bool:
        expected = "sha256=" + hmac.new(self.signing_secret(), raw, hashlib.sha256).hexdigest()
        if not signature.isascii() or not hmac.compare_digest(expected, signature):
            raise InvalidSignatureError
        if event == "ping":
            return True
        if event not in SUPPORTED_EVENTS | LIFECYCLE_EVENTS:
            raise ValueError("unsupported GitHub webhook event")
        payload = _PAYLOAD.validate_json(raw)
        envelope = validate_payload(event, payload)
        if event in SUPPORTED_EVENTS and envelope.repository is None:
            raise ValueError("repository event requires a repository")
        return await store.ingest_github(
            self.settings.app_id,
            delivery_id,
            envelope.installation.id,
            envelope.repository.id if envelope.repository else None,
            event,
            hashlib.sha256(event.encode() + b"\0" + raw).digest(),
            payload,
        )

    def matches(self, source: GitHubSource, context: Context, delivery: GitHubDelivery, payload: Envelope) -> bool:
        if not source.selects(delivery.event, payload.action):
            return False
        subject = source.subject
        base = delivery.repository_id == context.binding.repository_id
        if isinstance(payload, PullRequestPayload):
            return base and isinstance(subject, PullRequestSubject) and payload.pull_request.number == subject.number
        if isinstance(payload, IssuePayload):
            return (
                base
                and isinstance(subject, PullRequestSubject)
                and payload.issue.pull_request is not None
                and payload.issue.number == subject.number
            )
        if isinstance(payload, PushPayload):
            return base and isinstance(subject, BranchSubject) and payload.ref == f"refs/heads/{subject.name}"
        if isinstance(payload, RefPayload):
            return (
                base
                and isinstance(subject, BranchSubject)
                and payload.ref_type == "branch"
                and payload.ref == subject.name
            )
        match payload:
            case CheckRunPayload(check_run=check) | CheckSuitePayload(check_suite=check):
                sha, prs = check.head_sha, check.pull_requests
            case WorkflowPayload(workflow_run=workflow):
                sha, prs = workflow.head_sha, workflow.pull_requests
                if base and isinstance(subject, BranchSubject) and workflow.head_branch == subject.name:
                    return True
            case StatusPayload(sha=sha, branches=branches):
                prs = []
                if base and isinstance(subject, BranchSubject) and any(b.name == subject.name for b in branches):
                    return True
            case _:
                return False
        return sha in context.heads or (
            base and isinstance(subject, PullRequestSubject) and any(pr.number == subject.number for pr in prs)
        )

    async def reconcile(self, store: Store, claim: Inbox, subscription: Subscription, source: GitHubSource) -> None:
        context = await self.context(source)
        if context.binding != GitHubBinding.model_validate(subscription.binding):
            raise GitHubUnavailableError("GitHub source installation/repository changed; recreate the subscription")
        if isinstance(source.subject, PullRequestSubject):
            context.heads |= await store.pr_heads(
                context.binding.app_id, context.binding.repository_id, source.subject.number
            )
        if isinstance(source.subject, BranchSubject):
            context.heads |= await store.branch_heads(
                context.binding.app_id, context.binding.repository_id, source.subject.name
            )
        deliveries = await store.github_deliveries(
            context.binding.app_id, set(context.installations), subscription.position
        )
        matched = []
        through = subscription.position
        retry_at: datetime | None = None
        for delivery in deliveries:
            # Check current access for every repository considered, including an installed PR fork.
            if context.installations.get(delivery.repository_id or 0) != delivery.installation_id:
                if retry_at is None:
                    through = delivery.position
                continue
            payload = validate_payload(delivery.event, delivery.payload)
            if self.matches(source, context, delivery, payload):
                assert delivery.repository_id is not None
                matched.append(
                    (
                        delivery,
                        GitHubEvent(
                            provider="github",
                            app_id=delivery.app_id,
                            delivery_id=delivery.delivery_id,
                            repository_id=delivery.repository_id,
                            event=EventName(delivery.event),
                            action=payload.action,
                        ),
                    )
                )
            elif (
                delivery.event in CI_EVENTS
                and not isinstance(source.subject, CommitSubject)
                and source.selects(delivery.event, payload.action)
                and delivery.received_at + timedelta(seconds=self.settings.reconciliation_seconds) > datetime.now(UTC)
            ):
                # Revisit ambiguous/out-of-order CI after refreshing the authoritative head.
                expires = delivery.received_at + timedelta(seconds=self.settings.reconciliation_seconds)
                retry_at = min(retry_at, expires) if retry_at is not None else expires
            if retry_at is None:
                through = delivery.position
        if retry_at is None and len(deliveries) == 128:
            retry_at = datetime.now(UTC)  # Drain the next bounded page without waiting for another webhook.
        await store.record_github(claim, subscription, matched, through, retry_at)
