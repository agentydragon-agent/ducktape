"""Bazel macro for pushing OCI images to GHCR with conditional tagging.

Creates a `bazel run`-able py_binary that pushes an OCI image to GHCR only
when the image digest has changed. Tagged with "ghcr_push" for discovery
by generate_buildbuddy.py.
"""

load("@bazel_skylib//rules:write_file.bzl", "write_file")
load("@rules_python//python:defs.bzl", "py_binary")

def ghcr_push(name, image, repository, visibility = None):
    """Create a runnable target that pushes an OCI image to GHCR with conditional tagging.

    Args:
        name: Target name (e.g., "push_ghcr").
        image: Label of the oci_image target.
        repository: Full GHCR repository (e.g., "ghcr.io/agentydragon/props-backend").
        visibility: Bazel visibility.
    """
    main_name = name + "_main"
    pkg = native.package_name()

    # Resolve to fully qualified label for embedding in generated Python.
    # The image arg is also passed to data= where Bazel resolves it natively.
    image_label = str(native.package_relative_label(image))

    write_file(
        name = main_name,
        out = name + "_main.py",
        content = [
            "from devinfra.ghcr_push.ghcr_push_lib import push_main",
            "",
            "push_main(",
            '    image_target="{}",'.format(image_label),
            '    repository="{}",'.format(repository),
            ")",
        ],
    )

    # Compute imports path from package depth to repo root
    depth = len(pkg.split("/")) if pkg else 0
    imports_path = "/".join([".."] * depth) if depth > 0 else "."

    py_binary(
        name = name,
        srcs = [":" + main_name],
        main = name + "_main.py",
        imports = [imports_path],
        data = [image],
        deps = ["//devinfra/ghcr_push:ghcr_push_lib"],
        tags = ["ghcr_push"],
        visibility = visibility,
    )
