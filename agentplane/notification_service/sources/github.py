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
from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.orm import aliased

from agentplane.notification_service.db import GitHubDelivery, Inbox, Subscription
from agentplane.notification_service.settings import GitHubSettings
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


def correlation(payload: Envelope) -> tuple[str | None, list[str]]:
    """Index upstream subject references without imposing a universal filter vocabulary."""
    match payload:
        case PullRequestPayload(pull_request=pr):
            return pr.head.sha, [f"pull_request:{pr.number}"]
        case IssuePayload(issue=issue) if issue.pull_request is not None:
            return None, [f"pull_request:{issue.number}"]
        case PushPayload(ref=ref, after=sha) if ref.startswith("refs/heads/"):
            return (None if sha == "0" * 40 else sha), [f"branch:{ref.removeprefix('refs/heads/')}"]
        case RefPayload(ref=ref, ref_type="branch"):
            return None, [f"branch:{ref}"]
        case CheckRunPayload(check_run=check) | CheckSuitePayload(check_suite=check):
            return check.head_sha, [f"pull_request:{pr.number}" for pr in check.pull_requests]
        case WorkflowPayload(workflow_run=workflow):
            subjects = [f"pull_request:{pr.number}" for pr in workflow.pull_requests]
            if workflow.head_branch is not None:
                subjects.append(f"branch:{workflow.head_branch}")
            return workflow.head_sha, subjects
        case StatusPayload(sha=sha, branches=branches):
            return sha, [f"branch:{branch.name}" for branch in branches]
        case _:
            return None, []


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
        sha, subjects = correlation(envelope)
        return await store.ingest_github(
            self.settings.app_id,
            delivery_id,
            envelope.installation.id,
            envelope.repository.id if envelope.repository else None,
            event,
            hashlib.sha256(event.encode() + b"\0" + raw).digest(),
            payload,
            action=envelope.action,
            head_sha=sha,
            subjects=subjects,
        )

    async def reconcile(self, store: Store, claim: Inbox, subscription: Subscription, source: GitHubSource) -> None:
        context = await self.context(source)
        if context.binding != GitHubBinding.model_validate(subscription.binding):
            raise GitHubUnavailableError("GitHub source installation/repository changed; recreate the subscription")
        delivery = GitHubDelivery
        direct: ColumnElement[bool] = false()
        heads: ColumnElement[bool] = delivery.head_sha.in_(context.heads)
        match source.subject:
            case PullRequestSubject(number=number):
                subject = f"pull_request:{number}"
            case BranchSubject(name=name):
                subject = f"branch:{name}"
            case CommitSubject():
                subject = None
        if subject is not None:
            direct = (delivery.repository_id == context.binding.repository_id) & delivery.subjects.contains([subject])
            association = aliased(GitHubDelivery)
            # Association lookup is independent of subscription/processing position. A late PR/push
            # can explain an earlier receipt, even after a restart or many unrelated deliveries.
            known_heads = select(association.head_sha).where(
                association.app_id == context.binding.app_id,
                association.repository_id == context.binding.repository_id,
                association.installation_id == context.binding.installation_id,
                association.subjects.contains([subject]),
                association.head_sha.is_not(None),
            )
            heads |= delivery.head_sha.in_(known_heads)
        selected = or_(
            *(
                (delivery.event == selector.event)
                & (delivery.action.in_(selector.actions) if selector.actions is not None else true())
                for selector in source.filters
            )
        )
        accessible = or_(
            *(
                (delivery.repository_id == repository) & (delivery.installation_id == installation)
                for repository, installation in context.installations.items()
            )
        )
        deliveries = await store.github_deliveries(
            subscription,
            (delivery.app_id == context.binding.app_id)
            & accessible
            & selected
            & (direct | (delivery.event.in_(CI_EVENTS) & heads)),
        )
        matched = []
        for receipt in deliveries:
            assert receipt.repository_id is not None
            matched.append(
                (
                    receipt,
                    GitHubEvent(
                        provider="github",
                        app_id=receipt.app_id,
                        delivery_id=receipt.delivery_id,
                        repository_id=receipt.repository_id,
                        event=EventName(receipt.event),
                        action=receipt.action,
                    ),
                )
            )
        # Only matching, previously undelivered receipts occupy the bounded page.
        await store.record_github(claim, subscription, matched, more=len(deliveries) == 128)
