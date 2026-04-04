"""Module extension for container image pins.

Reads devinfra/image_pins.json and generates @image_pins//:pins.bzl with
Starlark constants for all pinned images. BUILD files load these constants
instead of hardcoding image references.

Each JSON entry produces NAME_IMAGE and NAME_DIGEST constants.
oci.pull() calls in MODULE.bazel reference the same digests; the
update_image_pin.py script keeps both in sync.

Usage in MODULE.bazel:
    image_pins = use_extension("//devinfra:image_pins.bzl", "image_pins")
    image_pins.from_file(lockfile = "//devinfra:image_pins.json")
    use_repo(image_pins, "image_pins")

In BUILD files:
    load("@image_pins//:pins.bzl", "RBE_WORKER_IMAGE", "RBE_WORKER_DIGEST")
"""

_from_file = tag_class(attrs = {
    "lockfile": attr.label(mandatory = True, allow_single_file = True),
})

def _pins_repo_impl(rctx):
    """Generate pins.bzl with constants for all pinned images."""
    pins = json.decode(rctx.read(rctx.attr.lockfile))
    lines = ['"""Generated image pin constants. Do not edit -- update devinfra/image_pins.json."""', ""]
    for name, pin in sorted(pins.items()):
        upper = name.upper()
        lines.append('%s_IMAGE = "%s"' % (upper, pin["image"]))
        lines.append('%s_DIGEST = "%s"' % (upper, pin["digest"]))
    rctx.file("pins.bzl", "\n".join(lines) + "\n")
    rctx.file("BUILD.bazel", "")

_pins_repo = repository_rule(
    implementation = _pins_repo_impl,
    attrs = {"lockfile": attr.label(mandatory = True, allow_single_file = True)},
)

def _impl(module_ctx):
    for mod in module_ctx.modules:
        for cfg in mod.tags.from_file:
            _pins_repo(name = "image_pins", lockfile = cfg.lockfile)

    return module_ctx.extension_metadata(
        root_module_direct_deps = ["image_pins"],
        root_module_direct_dev_deps = [],
        reproducible = True,
    )

image_pins = module_extension(
    implementation = _impl,
    tag_classes = {"from_file": _from_file},
)
