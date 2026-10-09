"""GitHub App authentication, signed ingress, and provider-owned subject matching."""

import asyncio
import hashlib
import hmac
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
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
    RepositoryName,
)
from agentplane.notification_service.store import Store

# RS256 is loaded dynamically by PyJWT.
# gazelle:include_dep @pypi//cryptography

logger = logging.getLogger(__name__)

_PAYLOAD = TypeAdapter(dict[str, JsonValue])
SUPPORTED_EVENTS = CI_EVENTS | PR_EVENTS | REF_EVENTS


class GitHubUnavailableError(Exception):
    """Disabled provider or confirmed loss of repository/installation access."""


class GitHubAccessError(GitHubUnavailableError):
    """Access is denied or the installation is suspended."""


class GitHubSourceChangedError(GitHubUnavailableError):
    """The authorized repository, installation or commit identity changed."""


class GitHubNotInstalledError(GitHubAccessError):
    """The App's installation lookup returned 404 for this repository."""


class GitHubRetryError(Exception):
    def __init__(self, status_code: int, retry_seconds: int) -> None:
        self.retry_seconds = retry_seconds
        super().__init__(f"GitHub rate limited (HTTP {status_code}); retry in {retry_seconds}s")


def rate_limit_delay(headers: httpx.Headers, now: float) -> int:
    # GitHub primary limits use an epoch reset; secondary limits may supply Retry-After.
    # Neither deadline may be shortened by our fallback or a maximum-delay clamp.
    delay = 60
    retry_after = headers.get("retry-after", "")
    if retry_after.isascii() and retry_after.isdecimal():
        delay = max(delay, int(retry_after))
    elif retry_after:
        try:
            deadline = parsedate_to_datetime(retry_after)
        except ValueError, OverflowError:
            pass
        else:
            if deadline.tzinfo is not None:
                delay = max(delay, math.ceil(deadline.timestamp() - now))
    reset = headers.get("x-ratelimit-reset", "")
    if headers.get("x-ratelimit-remaining") == "0" and reset.isascii() and reset.isdecimal():
        delay = max(delay, math.ceil(int(reset) - now))
    return delay


class InvalidSignatureError(Exception):
    pass


class Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class Installation(Upstream):
    id: int = Field(gt=0)
    suspended_at: datetime | None = None


class Repository(Upstream):
    id: int = Field(gt=0)
    full_name: RepositoryName


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


# GitHub supplies the discriminator in a header, not in the JSON body.
PAYLOAD_MODELS: dict[str, type[Envelope]] = {
    EventName.PULL_REQUEST: PullRequestPayload,
    EventName.PULL_REQUEST_REVIEW: PullRequestPayload,
    EventName.PULL_REQUEST_REVIEW_COMMENT: PullRequestPayload,
    EventName.ISSUE_COMMENT: IssuePayload,
    EventName.CHECK_RUN: CheckRunPayload,
    EventName.CHECK_SUITE: CheckSuitePayload,
    EventName.WORKFLOW_RUN: WorkflowPayload,
    EventName.STATUS: StatusPayload,
    EventName.PUSH: PushPayload,
    EventName.CREATE: RefPayload,
    EventName.DELETE: RefPayload,
    "installation": Envelope,
    "installation_repositories": Envelope,
}


def api_headers(bearer: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


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
        return api_headers(bearer)

    def start(self) -> None:
        # Validate the App private key before HTTP readiness; Settings validates the signing secret.
        self.app_headers()

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
            raise GitHubRetryError(response.status_code, rate_limit_delay(response.headers, time.time()))
        if allow_missing and response.status_code == 404:
            return response
        if response.status_code == 401:
            self.tokens.clear()
        if response.status_code in (401, 403, 404):
            raise GitHubAccessError(
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
        return api_headers(token.token.get_secret_value())

    async def repository(self, name: str) -> tuple[GitHubBinding, dict[str, str]]:
        response = await self.request("GET", f"/repos/{name}/installation", self.app_headers(), allow_missing=True)
        if response.status_code == 404:
            raise GitHubNotInstalledError("GitHub App has no accessible installation for this repository")
        installation = Installation.model_validate_json(response.content)
        if installation.suspended_at is not None:
            raise GitHubAccessError("GitHub App installation is suspended")
        headers = await self.installation_headers(installation.id)
        repository = Repository.model_validate_json((await self.request("GET", f"/repos/{name}", headers)).content)
        return GitHubBinding(
            app_id=self.settings.app_id, installation_id=installation.id, repository_id=repository.id
        ), headers

    async def context(self, source: GitHubSource) -> Context:
        # TODO: Bootstrap head/fork associations once, then maintain them from durable webhooks.
        # Keep access revalidation separate, with an explicit repair path for missed deliveries.
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
                            raise GitHubSourceChangedError("GitHub fork repository identity changed")
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
                    raise GitHubSourceChangedError("GitHub commit identity changed")
                context.heads.add(sha)
        return context

    async def ingest(self, store: Store, event: str, delivery_id: UUID, signature: str, raw: bytes) -> bool:
        expected = (
            "sha256="
            + hmac.new(self.settings.webhook_secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
        )
        if not signature.isascii() or not hmac.compare_digest(expected, signature):
            raise InvalidSignatureError
        if event == "ping":
            return True
        if event not in PAYLOAD_MODELS:
            raise ValueError("unsupported GitHub webhook event")
        payload = _PAYLOAD.validate_json(raw)
        envelope = PAYLOAD_MODELS[event].model_validate(payload)
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
        if context.binding != GitHubBinding.model_validate(subscription.github_binding):
            raise GitHubSourceChangedError("GitHub source installation/repository changed; recreate the subscription")
        delivery = GitHubDelivery
        direct: ColumnElement[bool] = false()
        heads: ColumnElement[bool] = delivery.head_sha.in_(context.heads)
        subject: str | None
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
