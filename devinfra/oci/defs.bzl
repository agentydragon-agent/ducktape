"""OCI build helpers for this repository."""

load("@aspect_bazel_lib//lib:paths.bzl", "to_rlocation_path")
load("@rules_oci//oci:defs.bzl", "oci_load")

def _oci_image_info_impl(ctx):
    """Write a JSON file with the OCI layout rlocation and repo tag."""
    image = ctx.file.image
    out = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(out, json.encode({
        "oci_layout": to_rlocation_path(ctx, image),
        "tag": ctx.attr.tag,
    }))

    # Merge image runfiles so the OCI layout files are accessible in tests.
    runfiles = ctx.runfiles([out]).merge(ctx.attr.image[DefaultInfo].default_runfiles)
    return [DefaultInfo(files = depset([out]), runfiles = runfiles)]

_oci_image_info = rule(
    implementation = _oci_image_info_impl,
    attrs = {
        "image": attr.label(mandatory = True, allow_single_file = True),
        "tag": attr.string(mandatory = True),
    },
)

def oci_image_info(name, image, tag, visibility = None, testonly = False):
    """Standalone JSON info target for images that already have oci_load elsewhere.

    Use this for images that need `bazel run :load` AND a test data dep.
    Generates :<name> (JSON info file; add to data= deps in tests).

    In tests, use load_oci_image() from util/oci.py with the rlocation
    _main/<package>/<name>.json.
    """
    _oci_image_info(
        name = name,
        image = image,
        tag = tag,
        visibility = visibility,
        testonly = testonly,
    )

def oci_tarball(name, image, repo_tags, visibility = None, testonly = False):
    """OCI image target for tests and `bazel run` loading.

    Generates two targets:
    - :<name>      - JSON info file; add to data= deps in tests
    - :<name>_load - oci_load target; runnable via `bazel run`

    In tests, use load_oci_image() from util/oci.py with the rlocation
    _main/<package>/<name>.json.
    """
    _oci_image_info(
        name = name,
        image = image,
        tag = repo_tags[0],
        visibility = visibility,
        testonly = testonly,
    )
    oci_load(
        name = name + "_load",
        image = image,
        repo_tags = repo_tags,
        testonly = testonly,
    )
