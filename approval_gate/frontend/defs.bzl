"""Shared Bazel macros for approval_gate/frontend visual regression tests."""

load("@aspect_rules_js//js:defs.bzl", "js_test")

_VISUAL_BASE_DATA = [
    "//util/frontend_visual_test:visual_test_lib",
    "//approval_gate/frontend:harness_bundle",
    "//approval_gate/frontend:harness_js",
    "//approval_gate/frontend:visual_test_assets",
    "//util/frontend_visual_test:fonts",
    "//util/frontend_visual_test:fonts_conf",
    "@playwright_browsers//:chromium-headless-shell",
]

_VISUAL_ENV = {
    "HARNESS_PATH": "$(rootpath //approval_gate/frontend:harness_js)",
    "PUPPETEER_EXECUTABLE_PATH": "$(rootpath @playwright_browsers//:chromium-headless-shell)",
    "FONTCONFIG_FILE": "$(rootpath //util/frontend_visual_test:fonts_conf)",
    "FREETYPE_PROPERTIES": "cff:no-stem-darkening=1",
}

def visual_test(name, srcs, deps = [], baseline = None, size = "small"):
    """Visual regression test for a single harness scenario.

    Args:
        name: Bazel target name (e.g., "visual_ListPage").
        srcs: Test source files (entry point first).
        deps: Additional data deps this test requires.
        baseline: Baseline PNG path.
        size: Bazel test size (default "small").
    """
    env = dict(_VISUAL_ENV)
    env["BASELINE_WORKSPACE_PATH"] = native.package_name() + "/baselines"

    baseline_data = [baseline] if baseline else native.glob(["baselines/*.png"])

    js_test(
        name = name,
        size = size,
        entry_point = srcs[0],
        data = _VISUAL_BASE_DATA + deps + baseline_data,
        env = env,
        no_copy_to_bin = _VISUAL_BASE_DATA,
    )
