"""Provisioning intent persisted in Kubernetes, not a service API representation."""

from pydantic import BaseModel, ConfigDict


class LaunchGrants(BaseModel):
    """Pending concrete policy grants, persisted on the Sandbox until provisioning completes."""

    model_config = ConfigDict(extra="forbid")

    policies: list[str]
    action_policy_sets: list[str]
