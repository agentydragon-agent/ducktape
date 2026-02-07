"""Shared Bazel rules for building critic agent variants.

Each critic variant differs only in its system prompt markdown file.
All variants share the same agent loop code (main.py) and tools.

Architecture:
- All variants use //props/agents/critic:main_tar (shared agent loop)
- Each variant packages its own prompt into /prompt.md.mako
- PROMPT_TEMPLATE_PATH env var tells main.py to use the baked-in prompt
"""

load("@rules_oci//oci:defs.bzl", "oci_image", "oci_load", "oci_push")
load("@rules_pkg//pkg:tar.bzl", "pkg_tar")
load("//props:oci.bzl", "py_binary_distroless_cmd", "py_binary_distroless_env")

def critic_variant(name, prompt_md):
    """Build a critic variant using the new in-container model.

    All variants share:
    - //props/agents/critic:main_tar (agent loop, tool definitions)
    - Same container base, env, workdir

    Each variant differs only in:
    - The prompt template baked into /prompt.md.mako
    - PROMPT_TEMPLATE_PATH env var pointing to it

    Generates targets:
    - :<name> - OCI image
    - :<name>_load - Load into local Docker
    - :<name>_push - Push to local registry

    Args:
        name: Variant name (e.g., "dead_code")
        prompt_md: Source markdown file for system prompt
    """

    # Rename variant-specific prompt to /prompt.md.mako
    # Use _gen suffix dir to avoid conflict with oci_image output dir
    gen_dir = name + "_gen"
    native.genrule(
        name = name + "_prompt_gen",
        srcs = [prompt_md],
        outs = [gen_dir + "/prompt.md.mako"],
        cmd = "cp $< $@",
    )

    # Package renamed prompt
    pkg_tar(
        name = name + "_prompt_tar",
        srcs = [":" + name + "_prompt_gen"],
        package_dir = "/",
        strip_prefix = gen_dir,
    )

    # Build OCI image: shared main_tar + variant prompt
    oci_image(
        name = name,
        base = "@distroless_cc_linux_amd64",
        cmd = py_binary_distroless_cmd("critic", binary_package = "props/agents/critic"),
        env = py_binary_distroless_env("critic", extra_env = {
            "PROMPT_TEMPLATE_PATH": "/prompt.md.mako",
        }),
        tars = [
            "//props/agents/critic:main_tar",
            ":" + name + "_prompt_tar",
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
