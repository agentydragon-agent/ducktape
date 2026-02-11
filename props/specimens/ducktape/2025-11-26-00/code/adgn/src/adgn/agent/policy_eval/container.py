from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os

from docker.client import DockerClient

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.agent.policy_eval.runner import run_policy_source
from adgn.agent.runtime.images import resolve_runtime_image

logger = logging.getLogger(__name__)


@dataclass
class ContainerPolicyEvaluator:
    """Evaluate policy decisions inside a one-off Docker container (isolated).

    The active policy source is executed directly via `python -c <source>`; no
    per-agent volumes are required. The image must have the `adgn` package
    installed so the policy can import helpers. Network is disabled; no RW
    mounts; no container reuse.
    """

    agent_id: str
    docker_client: DockerClient
    engine: ApprovalPolicyEngine
    image: str = field(default_factory=resolve_runtime_image)
    timeout_secs: float = field(
        default_factory=lambda: float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
    )

    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        """Evaluate using the current policy source via run_policy_source."""
        policy_src, _ver = self.engine.get_policy()
        return run_policy_source(
            docker_client=self.docker_client,
            source=policy_src,
            input_payload=policy_input,
            image=self.image,
            timeout_secs=self.timeout_secs,
        )
