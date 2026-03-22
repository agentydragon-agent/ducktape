"""Module extension that reads devinfra/image_pins.json and creates image repos.

Creates:
- @image_pins repo with RBE_CONTAINER_IMAGE constant (for BUILD.bazel platform)
- @e2e_container repo via oci_pull (replaces manual oci.pull in MODULE.bazel)

The JSON file is the single source of truth for image pins. CI updates it
with structured Python, and Bazel picks up changes automatically.
"""

load("@rules_oci//oci:pull.bzl", "oci_pull")

_IMAGE_PINS_LABEL = Label("//devinfra:image_pins.json")


def _image_pins_impl(module_ctx):
    pins = json.decode(module_ctx.read(_IMAGE_PINS_LABEL))

    # RBE worker: expose as a constant for platform exec_properties
    _pins_repo(
        name = "image_pins",
        pins_json = json.encode(pins),
    )

    # E2E container: create OCI repo (replaces oci.pull in MODULE.bazel)
    e2e = pins["e2e-container"]
    oci_pull(
        name = "e2e_container",
        image = e2e["image"],
        tag = e2e["tag"],
        digest = e2e["digest"],
        platforms = ["linux/amd64"],
    )


def _pins_repo_impl(repo_ctx):
    """Repository rule that generates a .bzl file with pin constants."""
    pins = json.decode(repo_ctx.attr.pins_json)

    rbe = pins["rbe-worker"]
    rbe_image = "docker://{image}:{tag}".format(
        image = rbe["image"],
        tag = rbe["tag"],
    )

    repo_ctx.file("BUILD.bazel", "")
    repo_ctx.file("defs.bzl", """\
# Auto-generated from devinfra/image_pins.json — do not edit.
RBE_CONTAINER_IMAGE = {rbe_image}
""".format(
        rbe_image = repr(rbe_image),
    ))


_pins_repo = repository_rule(
    implementation = _pins_repo_impl,
    attrs = {
        "pins_json": attr.string(mandatory = True),
    },
)

image_pins = module_extension(
    implementation = _image_pins_impl,
)
