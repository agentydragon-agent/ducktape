"""Shared Bazel rules for building critic agent variants.

Each critic variant differs only in its system prompt markdown file.
All variants share the same agent loop code (main.py) and tools.

Architecture:
- All variants use //props/agents/critic:main_tar (shared agent loop + variant prompts)
- PROMPT_TEMPLATE_PATH env var selects which variant prompt to use at runtime
"""

load("@rules_oci//oci:defs.bzl", "oci_image", "oci_load", "oci_push")
load("//props:oci.bzl", "py_binary_distroless_cmd", "py_binary_distroless_env")

def critic_variant(name, prompt_md):
    """Build a critic variant using the in-container model.

    All variants share:
    - //props/agents/critic:main_tar (agent loop, tool definitions, all variant prompts)
    - Same container base, env, workdir

    Each variant differs only in:
    - PROMPT_TEMPLATE_PATH env var pointing to the variant prompt in runfiles

    Generates targets:
    - :<name> - OCI image
    - :<name>_load - Load into local Docker
    - :<name>_push - Push to local registry

    Args:
        name: Variant name (e.g., "dead_code")
        prompt_md: Source markdown file for system prompt
    """

    # Runfiles path for the variant prompt inside the container
    prompt_runfiles_path = "/app/critic.runfiles/_main/props/agents/critic/variants/" + prompt_md

    # Build OCI image: shared main_tar (includes variant prompts via data)
    oci_image(
        name = name,
        base = "@distroless_cc_linux_amd64",
        cmd = py_binary_distroless_cmd("critic", binary_package = "props/agents/critic"),
        env = py_binary_distroless_env("critic", extra_env = {
            "PROMPT_TEMPLATE_PATH": prompt_runfiles_path,
        }),
        tars = [
            "//props/agents/critic:main_tar",
        ],
        workdir = "/workspace",
    )

    # Load into local Docker
    oci_load(
        name = name + "_load",
        image = ":" + name,
        repo_tags = ["critic:" + name],
    )

    # Push to registry
    oci_push(
        name = name + "_push",
        image = ":" + name,
        remote_tags = [name],
        repository = "localhost:8000/critic",
    )
