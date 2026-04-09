"""Macro for per-artifact GitHub release targets."""

load("//devinfra/python:defs.bzl", "py_binary")

def github_release(name, artifact, pkg, filename, visibility = None, **kwargs):
    """Create a runnable target that releases an artifact to GitHub.

    The artifact is a data dep resolved from runfiles — no bazel-bin globbing.
    Run with: bazel run //pkg:name (requires GH_RELEASE_PAT env var).

    Args:
        name: Target name.
        artifact: Label of the artifact to release (wheel, tar, binary).
        pkg: npins package name (e.g., "claude-hooks").
        filename: Artifact filename for the GitHub release asset.
        visibility: Bazel visibility.
        **kwargs: Passed through to py_binary.
    """
    py_binary(
        name = name,
        main_module = "devinfra.ci.github_release_bin",
        data = [artifact],
        deps = ["//devinfra/ci:github_release_lib"],
        args = [
            "--pkg",
            pkg,
            "--filename",
            filename,
            "--artifact-rlocation",
            "$(rlocationpath %s)" % artifact,
        ],
        visibility = visibility,
        **kwargs
    )
