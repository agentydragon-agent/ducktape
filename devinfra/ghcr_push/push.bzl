"""Bazel macro for pushing OCI images to GHCR with conditional tagging.

Creates a `bazel run`-able py_binary that pushes an OCI image to GHCR only
when the image digest has changed. Tagged with "ghcr_push" so targets can
be found via `bazel query 'attr(tags, "ghcr_push", //...)'`.
generate_buildbuddy.py maintains a manual PUSH_TARGETS list that must be
kept in sync (nested bazel query from bazel run is not feasible).
"""

load("@rules_python//python:defs.bzl", "py_binary")

def ghcr_push(name, image, repository, visibility = None):
    """Create a runnable target that pushes an OCI image to GHCR with conditional tagging.

    Args:
        name: Target name (e.g., "push_ghcr").
        image: Label of the oci_image target.
        repository: Full GHCR repository (e.g., "ghcr.io/agentydragon/props-backend").
        visibility: Bazel visibility.
    """
    image_label = str(native.package_relative_label(image))

    py_binary(
        name = name,
        main_module = "devinfra.ghcr_push.ghcr_push_lib",
        args = [
            "--image-target",
            image_label,
            "--repository",
            repository,
        ],
        data = [image],
        deps = ["//devinfra/ghcr_push:ghcr_push_lib"],
        tags = ["ghcr_push"],
        visibility = visibility,
    )
