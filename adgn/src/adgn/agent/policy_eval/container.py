from __future__ import annotations

import logging
import os

from docker import DockerClient

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.agent.policy_eval.runner import run_policy_source
from adgn.agent.runtime.images import resolve_runtime_image
from adgn.agent.types import AgentID

logger = logging.getLogger(__name__)


class ContainerPolicyEvaluator:
    """Evaluate policy decisions inside a one-off Docker container (isolated).

    The active policy source is executed directly via `python -c <source>`; no
    per-agent volumes are required. The image must have the `adgn` package
    installed so the policy can import helpers. Network is disabled; no RW
    mounts; no container reuse.
    """

    def __init__(
        self,
        *,
        agent_id: AgentID,
        docker_client: DockerClient,
        engine: ApprovalPolicyEngine,
        image: str | None = None,
        timeout_secs: float | None = None,
    ) -> None:
        if not agent_id:
            raise ValueError("ContainerPolicyEvaluator requires agent_id")
        self.agent_id = agent_id
        self.image: str = image or resolve_runtime_image()
        self.timeout_secs = (
            timeout_secs if timeout_secs is not None else float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
        )
        self._docker = docker_client
        self._engine = engine

    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        """Evaluate using the current policy source via run_policy_source."""
        payload = {"name": policy_input.name, "arguments": policy_input.arguments}
        policy_src, _ver = self._engine.get_policy()
        return run_policy_source(
            docker_client=self._docker,
            source=policy_src,
            input_payload=payload,
            image=self.image,
            timeout_secs=self.timeout_secs,
        )


## run_policy_source moved to adgn.agent.policy_eval.runner
