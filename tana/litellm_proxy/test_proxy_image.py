"""Verify the deployed interpreter imports the same patched publication code."""

import docker
import pytest_bazel

from tana.litellm_proxy import proxy_image
from util.oci import load_oci_image


def test_image_uses_patched_metadata_handlers() -> None:
    load_oci_image(proxy_image.IMAGE)
    # Import the actual image's server/utils, not a test-mounted copy. No startup,
    # database, or provider calls; the existing upstream entrypoint is unchanged.
    script = """
from litellm.proxy import proxy_server, utils
from litellm.proxy.common_utils.token_limit_publication import project_token_limits
assert proxy_server.project_token_limits is project_token_limits
assert utils.project_token_limits is project_token_limits
assert project_token_limits(
    {"max_tokens": 99, "max_input_tokens": 100, "input_cost_per_token": 0.1},
    [{"publish_token_limits": False}],
) == {"input_cost_per_token": 0.1}
"""
    with docker.from_env() as client:
        container = client.containers.create(
            proxy_image.IMAGE.tag,
            entrypoint=["/app/.venv/bin/python"],
            command=["-c", script],
            environment={"LITELLM_LOCAL_MODEL_COST_MAP": "True"},
            network_disabled=True,
        )
        try:
            container.start()
            result = container.wait(timeout=120)
            assert result["StatusCode"] == 0, container.logs().decode()
        finally:
            container.remove(force=True)


if __name__ == "__main__":
    pytest_bazel.main()
