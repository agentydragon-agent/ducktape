"""OCI build helpers for this repository."""

load("@rules_oci//oci:defs.bzl", "oci_load")

def oci_tarball(name, image, repo_tags, visibility = None, testonly = False):
    """Produce a Docker-loadable tarball from an OCI image.

    Generates two targets:
    - :<name>_load     - oci_load target; runnable via `bazel run`
    - :<name>_tarball  - filegroup exposing tarball.tar; use in data= deps

    The tarball rlocation is: _main/<package>/<name>_load/tarball.tar
    Load it in tests with load_image() from util/oci.py.
    """
    oci_load(
        name = name + "_load",
        image = image,
        repo_tags = repo_tags,
        testonly = testonly,
    )
    native.filegroup(
        name = name + "_tarball",
        srcs = [":" + name + "_load"],
        output_group = "tarball",
        visibility = visibility,
        testonly = testonly,
    )
