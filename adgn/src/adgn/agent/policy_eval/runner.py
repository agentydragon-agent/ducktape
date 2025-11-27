from __future__ import annotations

import logging
import os

import docker
from docker.client import DockerClient
import docker.errors

from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.agent.runtime.images import resolve_runtime_image

logger = logging.getLogger(__name__)


def run_policy_source(
    *,
    docker_client: DockerClient,
    source: str,
    input_payload: PolicyRequest,
    image: str | None = None,
    timeout_secs: float | None = None,
) -> PolicyResponse:
    """Run a policy source program once and return PolicyResponse.

    Synchronous helper intended for sanity checks when activating policy text.
    """
    # Resolve image to a concrete string (no Optional)
    img: str = image if image else resolve_runtime_image()
    tmo = timeout_secs if timeout_secs is not None else float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
    try:
        docker_client.images.get(img)
    except docker.errors.ImageNotFound as e:
        raise RuntimeError(f"policy eval image not found: {img}") from e

    # Avoid attach_socket/stdin I/O (flaky on some Docker backends e.g., Colima).
    # Inject the request JSON and the policy source via environment variables,
    # and run a tiny shim that feeds POLICY_INPUT to sys.stdin before exec'ing the policy source.
    ctx_json = input_payload.model_dump_json()
    # Execute the packaged shim module that reads POLICY_INPUT/POLICY_SRC
    container = docker_client.containers.create(
        image=img,
        command=["python", "-m", "adgn.agent.policy_eval.shim"],
        detach=True,
        tty=False,
        environment={"PYTHONUNBUFFERED": "1", "POLICY_SRC": source, "POLICY_INPUT": ctx_json},
        network_mode="none",
        volumes={},
        stdin_open=False,
        read_only=True,
        mem_limit=os.getenv("ADGN_POLICY_EVAL_MEM", "128m"),
        nano_cpus=int(os.getenv("ADGN_POLICY_EVAL_NANO_CPUS", str(500_000_000))),
        auto_remove=True,
    )
    try:
        container.start()
        # Enforce a hard wall-time timeout for evaluation.
        # If the container does not exit within tmo, stop it and raise.
        try:
            res = container.wait(timeout=float(tmo))
        except Exception as e:
            # Treat wait timeout or transport timeout as evaluation timeout
            try:
                container.stop(timeout=0)
            finally:
                raise RuntimeError("policy eval timeout") from e
        status = int(res.get("StatusCode", 1)) if isinstance(res, dict) else 1
        logs = container.logs(stdout=True, stderr=True) or b""
        if status != 0:
            text = logs.decode("utf-8", errors="replace")
            raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
        try:
            return PolicyResponse.model_validate_json(logs.strip())
        except Exception as e:
            text = logs.decode("utf-8", errors="replace")
            raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    finally:
        try:
            container.remove(force=True)
        except (docker.errors.APIError, docker.errors.NotFound) as e:
            logger.warning("policy eval container cleanup failed", exc_info=e)
