"""Read-only list-and-watch of enforcement resources into this replica's Index."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import CoreV1Api

from util.kubernetes import CustomObjectsClient
from x.agentplane.egress.policy import Index
from x.agentplane.egress.resources import (
    BINDINGS_PLURAL,
    CREDENTIALS_PLURAL,
    GROUP,
    POLICIES_PLURAL,
    SANDBOX_GROUP,
    SANDBOX_VERSION,
    SANDBOXES_PLURAL,
    VERSION,
    EgressBinding,
    EgressCredential,
    EgressPolicy,
    Sandbox,
    Secret,
)
from x.agentplane.kubernetes_watch import ListWatch, WatchedKind, apply_to


def _parse_policy(raw: dict[str, Any]) -> tuple[str, EgressPolicy]:
    policy = EgressPolicy.model_validate(raw)
    return policy.metadata.name, policy


def _parse_credential(raw: dict[str, Any]) -> tuple[str, EgressCredential]:
    credential = EgressCredential.model_validate(raw)
    return credential.metadata.name, credential


def _parse_binding(raw: dict[str, Any]) -> tuple[str, EgressBinding]:
    binding = EgressBinding.model_validate(raw)
    return binding.metadata.name, binding


def _parse_sandbox(raw: dict[str, Any]) -> tuple[str, Sandbox]:
    sandbox = Sandbox.model_validate(raw)
    return sandbox.metadata.name, sandbox


def _parse_secret(raw: k8s_client.V1Secret) -> tuple[str, Secret]:
    secret = Secret.from_v1(raw)
    return secret.name, secret


class Informer:
    def __init__(
        self,
        *,
        index: Index,
        custom_objects: CustomObjectsClient,
        core_v1: CoreV1Api,
        namespace: str,
        sandbox_namespace: str,
        credentials_namespace: str,
        resync_seconds: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._index = index
        self._watch = ListWatch(
            kinds=(
                WatchedKind(
                    name=POLICIES_PLURAL,
                    list=custom_objects.list_namespaced_custom_object,
                    args=(GROUP, VERSION, namespace, POLICIES_PLURAL),
                    parse=_parse_policy,
                    names=lambda: set(index.policies),
                    apply=lambda name, obj: apply_to(index.policies, name, obj),
                ),
                WatchedKind(
                    name=BINDINGS_PLURAL,
                    list=custom_objects.list_namespaced_custom_object,
                    args=(GROUP, VERSION, namespace, BINDINGS_PLURAL),
                    parse=_parse_binding,
                    names=lambda: set(index.bindings),
                    apply=lambda name, obj: apply_to(index.bindings, name, obj),
                ),
                WatchedKind(
                    name=CREDENTIALS_PLURAL,
                    list=custom_objects.list_namespaced_custom_object,
                    args=(GROUP, VERSION, namespace, CREDENTIALS_PLURAL),
                    parse=_parse_credential,
                    names=lambda: set(index.credentials),
                    apply=lambda name, obj: apply_to(index.credentials, name, obj),
                ),
                WatchedKind(
                    name=SANDBOXES_PLURAL,
                    list=custom_objects.list_namespaced_custom_object,
                    args=(SANDBOX_GROUP, SANDBOX_VERSION, sandbox_namespace, SANDBOXES_PLURAL),
                    parse=_parse_sandbox,
                    names=lambda: set(index.sandboxes),
                    apply=lambda name, obj: apply_to(index.sandboxes, name, obj),
                ),
                WatchedKind(
                    name="secrets",
                    list=core_v1.list_namespaced_secret,
                    args=(credentials_namespace,),
                    parse=_parse_secret,
                    names=lambda: set(index.secrets),
                    apply=lambda name, obj: apply_to(index.secrets, name, obj),
                ),
            ),
            resync_seconds=resync_seconds,
            on_change=self._changed,
            on_cycle=self._completed,
            clock=clock,
        )

    async def run(self) -> None:
        """Watch until cancelled."""
        await self._watch.run()

    async def _changed(self, kind: WatchedKind) -> None:
        self._index.synced = self._watch.synced
        await self._index.notify()

    async def _completed(self, kind: WatchedKind, at: datetime) -> None:
        self._index.refreshed[kind.name] = at
        await self._index.notify()
