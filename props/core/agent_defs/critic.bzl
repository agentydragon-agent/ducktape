"""Shared Bazel rules for building critic agent variants.

Each critic variant differs only in its agent.md file. This macro
reduces duplication by generating all standard targets from a single
variant-specific markdown file.
"""

load("@rules_oci//oci:defs.bzl", "oci_image", "oci_load", "oci_push")
load("@rules_pkg//pkg:tar.bzl", "pkg_tar")

def critic_variant(name, agent_md):
    """Build a critic variant image with custom agent.md.

    Generates standard targets for building and publishing a critic variant:
    - :<name> - OCI image
    - :<name>_load - Load into local Docker
    - :<name>_push - Push to local registry

    Args:
        name: Variant name (e.g., "contract-truthfulness")
        agent_md: Source markdown file for agent instructions
    """

    # Package props CLI and dependencies
    pkg_tar(
        name = name + "_app_tar",
        srcs = ["//props/core:props"],
        include_runfiles = True,
        package_dir = "/app",
        strip_prefix = ".",
    )

    # Package variant-specific agent.md
    pkg_tar(
        name = name + "_agent_md_tar",
        srcs = [agent_md],
        package_dir = "/",
        renames = {agent_md: "agent.md"},  # Rename to standard agent.md
    )

    # Build OCI image
    oci_image(
        name = name,
        base = "@python_slim_linux_amd64",
        entrypoint = ["/init"],
        env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        },
        tars = [
            ":" + name + "_app_tar",
            "//props/core/agent_defs:critic_dev_init_tar",
            ":" + name + "_agent_md_tar",
        ],
        workdir = "/workspace",
    )

    # Load into local Docker
    oci_load(
        name = name + "_load",
        image = ":" + name,
        repo_tags = ["critic-agent:" + name],
    )

    # Push to registry
    oci_push(
        name = name + "_push",
        image = ":" + name,
        remote_tags = [name],
        repository = "localhost:5050/critic",
    )
