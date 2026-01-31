"""Bazel macros for tests that require Docker/container support.

On BuildBuddy RBE, these tests run inside Firecracker microVMs with a Docker
daemon started automatically via the init-dockerd exec property.
"""

load("@rules_python//python:defs.bzl", "py_test")

# Exec properties for tests needing Docker on RBE (Firecracker microVM).
# The test. prefix scopes these to the test action only (not build actions).
DOCKER_EXEC_PROPERTIES = {
    "test.workload-isolation-type": "firecracker",
    "test.init-dockerd": "true",
    "test.recycle-runner": "false",
    "test.EstimatedComputeUnits": "3",
}

def docker_py_test(name, tags = None, exec_properties = None, **kwargs):
    """py_test wrapper that adds Firecracker Docker exec properties.

    Automatically adds the "requires_docker" tag and Firecracker exec
    properties so the test gets a Docker daemon on RBE workers.

    Args:
        name: Target name.
        tags: Additional tags. "requires_docker" is added automatically.
        exec_properties: Extra exec properties merged with Docker defaults.
        **kwargs: Passed through to py_test.
    """
    base_tags = tags or []
    if "requires_docker" not in base_tags:
        base_tags = base_tags + ["requires_docker"]

    merged_props = dict(DOCKER_EXEC_PROPERTIES)
    if exec_properties:
        merged_props.update(exec_properties)

    py_test(
        name = name,
        tags = base_tags,
        exec_properties = merged_props,
        **kwargs
    )
