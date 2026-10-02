"""Sandbox provisioning orchestration over existing Kubernetes-owned state.

The app may select form presets, but this service owns concrete grants and launch bindings.
Existing labels/finalizers and deletion semantics are retained for an in-place ownership handoff.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from agentplane.sandbox_service.action_policy import ActionPolicyBindings
from agentplane.sandbox_service.egress import EgressInventory
from agentplane.sandbox_service.inventory import (
    KUBERNETES_GRANTS_ANNOTATION,
    PROVISIONING_ANNOTATION,
    SANDBOX_BINDING_ANNOTATION,
    NewSandbox,
    SandboxInventory,
    SandboxView,
)
from agentplane.sandbox_service.kubernetes_bindings import KUBERNETES_BINDINGS_FINALIZER, KubernetesBindings
from agentplane.sandbox_service.kubernetes_grants import ClusterRoleBindingGrant, KubernetesGrant, resolve_grants
from agentplane.sandbox_service.session_config import LaunchGrants, SandboxBinding


class SandboxProvisioner(Protocol):
    async def create(self, spec: NewSandbox) -> SandboxView: ...


@dataclass(frozen=True)
class Provisioning:
    inventory: SandboxInventory
    egress: EgressInventory
    action_policy: ActionPolicyBindings
    grants: dict[str, KubernetesGrant]
    bindings: KubernetesBindings | None

    async def create(self, spec: NewSandbox) -> SandboxView:
        grants = resolve_grants(spec.kubernetes_grants, self.grants)
        if grants and self.bindings is None:
            raise ValueError("Kubernetes grant provisioning is unavailable")
        policies = self.egress.launch_policies(spec.policies)
        await self.egress.require_policies(policies)
        await self.action_policy.require_policy_sets(spec.action_policy_sets)
        binding = (
            SandboxBinding(thread_defaults=spec.thread_defaults, bootstrap=spec.bootstrap)
            if spec.thread_defaults is not None or spec.bootstrap
            else None
        )
        annotations = {
            PROVISIONING_ANNOTATION: LaunchGrants(
                policies=policies, action_policy_sets=spec.action_policy_sets
            ).model_dump_json()
        }
        if binding is not None:
            annotations[SANDBOX_BINDING_ANNOTATION] = binding.model_dump_json(exclude_none=True)
        if grants:
            annotations[KUBERNETES_GRANTS_ANNOTATION] = json.dumps([grant.model_dump(mode="json") for grant in grants])
        view = await self.inventory.create(
            spec,
            annotations=annotations or None,
            finalizers=[KUBERNETES_BINDINGS_FINALIZER]
            if any(
                isinstance(grant.grant, ClusterRoleBindingGrant) or grant.grant.namespace != self.inventory.namespace
                for grant in grants
            )
            else None,
        )
        await self.ensure(view)
        return await self.inventory.get(view.name)

    async def ensure(self, sandbox: SandboxView) -> None:
        if sandbox.deleting:
            return
        intent = await self.inventory.pending_grants(sandbox.name)
        if intent is None:
            return  # Existing staging resources have no new intent to reinterpret or replace.
        if intent.policies:
            await self.egress.grant(sandbox, intent.policies, initial=True)
        if intent.action_policy_sets:
            await self.action_policy.bind(sandbox, intent.action_policy_sets, initial=True)
        if sandbox.kubernetes_grants:
            if self.bindings is None:
                raise ValueError("Kubernetes grant provisioning is unavailable")
            await self.bindings.ensure(sandbox)
            if not (await self.inventory.get(sandbox.name)).kubernetes_grants_ready:
                return
        await self.inventory.finish_provisioning(sandbox)

    async def reconcile_once(self) -> None:
        if self.bindings is not None:
            await self.bindings.reconcile_once()
        for sandbox in await self.inventory.list_sandboxes():
            try:
                await self.ensure(sandbox)
            except Exception:
                logging.getLogger(__name__).exception("provisioning incomplete for %s", sandbox.name)

    async def run(self, *, interval_seconds: float = 30) -> None:
        while True:
            try:
                await self.reconcile_once()
            except Exception:
                logging.getLogger(__name__).exception("provisioning reconciliation failed")
            await asyncio.sleep(interval_seconds)
