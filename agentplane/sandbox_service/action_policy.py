"""Concrete Action-policy grant provisioning, independent of the integration app."""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from agentplane.action_service.policies.resources import (
    BINDINGS_PLURAL,
    POLICY_SETS_PLURAL,
    ActionPolicySet,
    InvalidResource,
    parse_policy_set,
)
from agentplane.action_service.policy_view import ActionPolicySetView, set_view
from agentplane.crd_group import GROUP, VERSION
from agentplane.sandbox_service.inventory import InventoryError, SandboxView
from agentplane.sandbox_service.owned_binding import create_binding
from util.agent_sandbox import SANDBOX_API, SANDBOX_KIND
from util.kubernetes import CustomObjectsClient

ACTION_POLICY_API = (GROUP, VERSION)
# Preserve these existing ownership stamps when adopting staging resources.
MANAGED_BY_LABEL = "app.agentplane.allegedly.works/managed-by"
MANAGED_BY_APP = "integration-app"


class UnknownPolicySetError(InventoryError):
    """A binding naming a set the namespace does not hold, which would grant nothing.

    The CRD admits any string in `spec.policySets` and the Action Service treats a name that
    resolves to nothing as contributing nothing, so a dangling name is a state the system already
    handles. This refuses one at the moment it would be written; one the operator deletes
    afterwards still lands there without granting anything from the missing set.
    """

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"no ActionPolicySet in the namespace is named {', '.join(names)}")
        self.names = names


class _ResourceList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[dict[str, Any]]


class ActionPolicyBindings:
    """The namespace's sets and bindings: written through the API server, read back from the
    Action Service that evaluates them."""

    def __init__(self, *, namespace: str, custom_objects: CustomObjectsClient) -> None:
        self._namespace = namespace
        self._custom_objects = custom_objects

    async def require_policy_sets(self, names: Sequence[str]) -> None:
        """Every name must resolve to a set the namespace holds, or nothing is written."""
        _require_known(names, await self._policy_sets_by_name())

    async def list_policy_sets(self) -> list[ActionPolicySetView]:
        """Every set in the namespace, refused ones included, in name order."""
        return [set_view(policy_set) for name, policy_set in sorted((await self._policy_sets_by_name()).items())]

    async def bind(self, sandbox: SandboxView, policy_sets: Sequence[str], *, initial: bool = False) -> None:
        """One binding of the ServiceAccount the sandbox runs as to the sets, owned by the Sandbox
        so its deletion garbage-collects it. Creating it is the whole grant; the Action Service
        reads `spec` and learns nothing of which preset chose the sets.
        """
        _require_known(policy_sets, await self._policy_sets_by_name())
        await create_binding(
            self._custom_objects,
            *ACTION_POLICY_API,
            self._namespace,
            BINDINGS_PLURAL,
            {
                "apiVersion": "/".join(ACTION_POLICY_API),
                "kind": "ActionPolicyBinding",
                "metadata": {
                    # The API server names it, as it does the egress binding: a Sandbox may be
                    # bound again later, and a name derived from the Sandbox alone would 409.
                    **({"name": f"ap-init-{sandbox.uid.hex}"} if initial else {"generateName": f"{sandbox.name}-"}),
                    "labels": {MANAGED_BY_LABEL: MANAGED_BY_APP},
                    # Not the controller: the Sandbox controller owns the Pod and PVC, and this
                    # reference is for cascading deletion only. The binding lives in the Sandbox's
                    # namespace, which is also where the Action Service matches it to the caller,
                    # so the cascade holds.
                    "ownerReferences": [
                        {
                            "apiVersion": SANDBOX_API.api_version,
                            "kind": SANDBOX_KIND,
                            "name": sandbox.name,
                            "uid": str(sandbox.uid),
                            "controller": False,
                            "blockOwnerDeletion": False,
                        }
                    ],
                },
                "spec": {"subject": sandbox.service_account.model_dump(), "policySets": list(policy_sets)},
            },
        )

    async def _policy_sets_by_name(self) -> dict[str, ActionPolicySet | InvalidResource]:
        listed = await self._custom_objects.list_namespaced_custom_object(
            *ACTION_POLICY_API, self._namespace, POLICY_SETS_PLURAL
        )
        return {
            parsed.metadata.name: parsed for parsed in map(parse_policy_set, _ResourceList.model_validate(listed).items)
        }


def _require_known(names: Sequence[str], policy_sets: dict[str, ActionPolicySet | InvalidResource]) -> None:
    if unknown := [name for name in names if name not in policy_sets]:
        raise UnknownPolicySetError(unknown)
