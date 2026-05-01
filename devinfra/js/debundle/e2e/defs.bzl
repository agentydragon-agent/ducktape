"""Macro for end-to-end tests that drive debundler binaries as black boxes."""

load("@aspect_rules_js//js:defs.bzl", "js_test")

_JS_RUN_TRANSFORM = "//devinfra/js/debundle/transforms:run_transform"
_RUST_RUN_TRANSFORM = "//devinfra/js/debundle/rust:debundle_rust"

def e2e_test(name, **kwargs):
    """Declare an e2e test backed by `<name>.mjs`.

    The same test implementation is run against the JavaScript and Rust
    debundler CLIs. The unsuffixed target is a suite containing both variants.
    """
    _e2e_impl_test(
        name = "{}_js".format(name),
        entry = "{}.mjs".format(name),
        run_transform = _JS_RUN_TRANSFORM,
        **kwargs
    )
    _e2e_impl_test(
        name = "{}_rust".format(name),
        entry = "{}.mjs".format(name),
        run_transform = _RUST_RUN_TRANSFORM,
        **kwargs
    )
    native.test_suite(
        name = name,
        tests = [
            ":{}_js".format(name),
            ":{}_rust".format(name),
        ],
    )

def _e2e_impl_test(name, entry, run_transform, **kwargs):
    js_test(
        name = name,
        data = [
            entry,
            ":support",
            run_transform,
        ],
        entry_point = entry,
        env = {
            "DUCKTAPE_RUN_TRANSFORM_BIN": "$(rootpath {})".format(run_transform),
        },
        **kwargs
    )
