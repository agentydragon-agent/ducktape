"""Ergonomic wrapper for Agentplane's own `ActionPolicySet` CRD
(agentplane/crds/manifests/crd-actionpolicysets.yaml), following cdk8s-plus's own construction
pattern: a class named after the kind, and a named `@staticmethod` factory group for
`autoApproveIf`'s real variant shapes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agentplane_actionpolicyset_crds.works.allegedly.agentplane import (
    ActionPolicySet as _ActionPolicySet,
    ActionPolicySetSpec,
    ActionPolicySetSpecAutoApproveIf,
    ActionPolicySetSpecAutoApproveIfType,
)
from cdk8s import ApiObjectMetadata
from constructs import Construct


class AutoApproveIf:
    """`ActionPolicySetSpecAutoApproveIf`'s real variant shapes this repo uses: `exact_actions`
    (an Action name allowlist), `github_repository` (a fixed owner/repository),
    `github_public_repository` (a live, unauthenticated visibility check in place of a fixed
    owner/repository), and `argument_schema` (arguments satisfying a JSON Schema). The schema also
    defines `home_assistant_entity_control` (a Home Assistant service call confined to configured
    entities and services) -- add a factory the day this repo builds one.

    """

    @staticmethod
    def exact_actions(*, actions: Mapping[str, Sequence[str]]) -> ActionPolicySetSpecAutoApproveIf:
        """Matches by Action name alone."""
        return ActionPolicySetSpecAutoApproveIf(
            type=ActionPolicySetSpecAutoApproveIfType.EXACT_UNDERSCORE_ACTIONS, actions=actions
        )

    @staticmethod
    def github_repository(
        *, owner: str, repository: str, actions: Mapping[str, Sequence[str]]
    ) -> ActionPolicySetSpecAutoApproveIf:
        """Requires a GitHub MCP call to target `owner`/`repository`."""
        return ActionPolicySetSpecAutoApproveIf(
            type=ActionPolicySetSpecAutoApproveIfType.GITHUB_UNDERSCORE_REPOSITORY,
            owner=owner,
            repository=repository,
            actions=actions,
        )

    @staticmethod
    def argument_schema(
        *, actions: Mapping[str, Sequence[str]], schema: dict[str, Any]
    ) -> ActionPolicySetSpecAutoApproveIf:
        """Requires a listed Action's arguments to satisfy `schema`."""
        return ActionPolicySetSpecAutoApproveIf(
            type=ActionPolicySetSpecAutoApproveIfType.ARGUMENT_UNDERSCORE_SCHEMA,
            actions=actions,
            schema=schema,
        )

    @staticmethod
    def github_public_repository(*, actions: Mapping[str, Sequence[str]]) -> ActionPolicySetSpecAutoApproveIf:
        """Requires a GitHub MCP call to target a repository a live, unauthenticated lookup
        confirms public."""
        return ActionPolicySetSpecAutoApproveIf(
            type=ActionPolicySetSpecAutoApproveIfType.GITHUB_UNDERSCORE_PUBLIC_UNDERSCORE_REPOSITORY, actions=actions
        )


class ActionPolicySet(_ActionPolicySet):
    """Agentplane's `ActionPolicySet`: a reusable, subject-free set of Action auto-approval
    policies. Build `auto_approve_if` entries with `AutoApproveIf`'s factories.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        metadata: ApiObjectMetadata,
        auto_approve_if: Sequence[ActionPolicySetSpecAutoApproveIf] | None = None,
    ) -> None:
        super().__init__(
            scope,
            id,
            metadata=metadata,
            spec=ActionPolicySetSpec(auto_approve_if=list(auto_approve_if) if auto_approve_if is not None else None),
        )
